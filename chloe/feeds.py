# chloe/feeds.py
# ─────────────────────────────────────────────────────────────
# RSS feed reader and web page fetcher.
# During read states, Chloe absorbs real articles from the world.
#
# Feature 5: fetch_random_article() — picks from curated RSS feeds
# Feature 6: fetch_article_text()  — pulls full page when curiosity is high
# ─────────────────────────────────────────────────────────────

import asyncio
import math
import re
from dataclasses import dataclass
from typing import Optional
import random

import httpx
import feedparser
from bs4 import BeautifulSoup

# Curated feeds — chosen for Chloe's sensibility
FEED_URLS = [
    "https://feeds.aeon.co/aeon/magazine-articles",      # Aeon — philosophy & essays
    "https://nautil.us/feed/",                            # Nautilus — science + ideas
    "https://www.theguardian.com/science/rss",            # Guardian Science
    "https://www.themarginalian.org/feed/",               # The Marginalian — culture
    "https://www.theguardian.com/artanddesign/rss",       # Guardian Art & Design
]

_HEADERS    = {"User-Agent": "Mozilla/5.0 (compatible; Chloe/1.0)"}
_seen_urls:         list[str] = []   # last 20 article URLs — avoids exact repeats
_recent_title_words: set[str] = set()  # words from last ~5 articles — novelty penalty
_read_counts:       dict[str, int] = {}  # source → times read — balances feed exposure

# How often to force exploration mode from the caller side (every Nth read event)
EXPLORE_EVERY = 3


@dataclass
class Article:
    title:   str
    url:     str
    summary: str    # short excerpt from feed
    source:  str    # feed name


async def fetch_random_article(interests: list[str],
                                explore: bool = False) -> Optional[Article]:
    """Fetch articles from all RSS feeds and pick one.

    Selection strategy:
    - Interest overlap raises an article's base score (deepening).
    - Overlap with recently-read title words lowers it (novelty penalty).
    - Under-read sources get a small boost (feed diversity).
    - Final pick is probabilistic via softmax (temperature=2.0) rather than
      deterministic top-1, so lower-scored articles still get picked sometimes.
    - explore=True zeroes out interest scores so she reads something unexpected.
    """

    all_articles: list[Article] = []

    async def _load_feed(url: str):
        try:
            async with httpx.AsyncClient(timeout=8.0, follow_redirects=True) as client:
                r = await client.get(url, headers=_HEADERS)
            feed = await asyncio.to_thread(feedparser.parse, r.text)
            source = feed.feed.get("title", url)
            for entry in feed.entries[:15]:
                link = entry.get("link", "")
                if link and link not in _seen_urls:
                    all_articles.append(Article(
                        title=_strip_html(entry.get("title", "")),
                        url=link,
                        summary=_strip_html(entry.get("summary", ""))[:500],
                        source=source,
                    ))
        except Exception:
            pass

    await asyncio.gather(*(_load_feed(u) for u in FEED_URLS))

    if not all_articles:
        return None

    interest_words = {w.lower() for phrase in interests for w in phrase.split()
                      if len(w) > 3}   # skip short words to reduce false matches

    max_reads = max(_read_counts.values()) if _read_counts else 1

    scores: list[float] = []
    for a in all_articles:
        haystack = (a.title + " " + a.summary).lower()

        # Interest overlap (0 during exploration mode)
        interest_score = 0.0 if explore else sum(
            1 for w in interest_words if w in haystack
        )

        # Novelty penalty — penalise overlap with recently-read title words
        recent_overlap = sum(1 for w in _recent_title_words if w in haystack)
        novelty_penalty = recent_overlap * 0.6

        # Feed diversity bonus — favour under-read sources
        times_read = _read_counts.get(a.source, 0)
        diversity_bonus = 0.5 * (1.0 - times_read / (max_reads + 1))

        scores.append(max(0.0, interest_score - novelty_penalty + diversity_bonus))

    # Softmax selection (temperature=2.0 — higher → more random)
    temperature = 2.0
    weights = [math.exp(s / temperature) for s in scores]
    chosen = random.choices(all_articles, weights=weights, k=1)[0]

    # Update recency tracking
    _seen_urls.append(chosen.url)
    if len(_seen_urls) > 20:
        _seen_urls.pop(0)

    new_words = {w.lower() for w in chosen.title.split() if len(w) > 3}
    _recent_title_words.update(new_words)
    if len(_recent_title_words) > 80:   # keep window bounded
        # Drop a random subset — can't pop from a set by index easily
        excess = len(_recent_title_words) - 60
        for w in random.sample(list(_recent_title_words), excess):
            _recent_title_words.discard(w)

    _read_counts[chosen.source] = _read_counts.get(chosen.source, 0) + 1

    return chosen


async def fetch_article_text(url: str, max_chars: int = 2500) -> str:
    """Fetch a full web page and return clean readable text (up to max_chars).
    Uses BeautifulSoup to strip navigation/boilerplate."""
    try:
        async with httpx.AsyncClient(timeout=12.0, follow_redirects=True) as client:
            r = await client.get(url, headers=_HEADERS)
        text = await asyncio.to_thread(_parse_html, r.text)
        return text[:max_chars]
    except Exception:
        return ""


def _parse_html(html: str) -> str:
    """Strip HTML to readable prose. Runs in a thread (blocking)."""
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "nav", "footer", "header", "aside"]):
        tag.decompose()
    text = soup.get_text(separator=" ", strip=True)
    return re.sub(r"\s+", " ", text).strip()


def _strip_html(text: str) -> str:
    """Quick regex strip for RSS summary fields (already mostly clean)."""
    text = re.sub(r"<[^>]+>", " ", text)
    text = (text.replace("&amp;", "&").replace("&lt;", "<")
                .replace("&gt;", ">").replace("&nbsp;", " "))
    return re.sub(r"\s+", " ", text).strip()
