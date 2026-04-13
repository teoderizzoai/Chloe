# chloe/feeds.py
# ─────────────────────────────────────────────────────────────
# RSS feed reader and web page fetcher.
# During read states, Chloe absorbs real articles from the world.
#
# Feature 5: fetch_random_article() — picks from curated RSS feeds
# Feature 6: fetch_article_text()  — pulls full page when curiosity is high
# ─────────────────────────────────────────────────────────────

import asyncio
import re
from dataclasses import dataclass
from typing import Optional

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
_seen_urls: list[str] = []   # last 20 read article URLs to avoid repeats


@dataclass
class Article:
    title:   str
    url:     str
    summary: str    # short excerpt from feed
    source:  str    # feed name


async def fetch_random_article(interests: list[str]) -> Optional[Article]:
    """Fetch articles from all RSS feeds, pick one weighted toward current interests.
    Returns None if all feeds are unreachable."""
    import random

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

    # Score by overlap with current interests
    interest_words = {w.lower() for phrase in interests for w in phrase.split()}
    scored: list[tuple[int, float, Article]] = []
    for a in all_articles:
        haystack = (a.title + " " + a.summary).lower()
        score    = sum(1 for w in interest_words if w in haystack)
        scored.append((score, random.random(), a))   # random() breaks ties

    scored.sort(reverse=True)
    chosen = scored[0][2]

    _seen_urls.append(chosen.url)
    if len(_seen_urls) > 20:
        _seen_urls.pop(0)

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
