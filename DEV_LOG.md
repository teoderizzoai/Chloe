Session Log

Session 1 — Built all core modules in JS (soul, heart, memory, llm, graph, store, App.jsx)

Session 2 — Rebuilt everything in Python. Modules: soul.py, heart.py, memory.py, llm.py, graph.py, chloe.py

Session 3 — Added FastAPI server (server.py), HTML dashboard (index.html) with graph canvas

Session 4 — Added history.py, history tab in dashboard with soul drift charts and timeline

Session 5 — Debugged Windows setup: venv, file structure (chloe/ subfolder), API key, uvicorn boot

Session 6 — Two-tier LLM (Haiku/Opus). Layer 1 complete: circadian rhythm, night sleep scheduling, day-of-week personality, uptime tracking

Session 7 — Layer 2 complete: RSS feed reader (feeds.py), web page fetcher (bs4), weather awareness via Open-Meteo (weather.py), season/time language injected into all LLM prompts

Session 8 — Layer 3 complete: affect.py, inner.py, dreams, creative output, belief extraction, want resolution, mood pill + mind tab

Session 9 — Layer 4 complete: persons.py, extract_notable, generate_followup, person_id in chat, follow-up logic, people section in sidebar

Session 10 — Layer 5 complete: Goal dataclass, generate_reflection/continuity/goal/journal, _reflect() + _write_journal(), soul_baseline drift, goals in mind tab

Session 11 — UI redesign: 2-column layout, graph as main tab, persistent chat bar, cleaner tab bar. Designed Graph Intelligence spec (G1-G4)

Session 12 — Pivoted Layer 6 to Discord DMs. discord_bot.py; on_message callback with person_id; Discord starts in server.py lifespan; env vars DISCORD_BOT_TOKEN / DISCORD_TEO_ID / DISCORD_ZUZU_ID

Session 13 — Layer 7 complete (27-30): node resonance, threshold auto-expansion, orphan tag surfacing, dream recurrence root nodes

Session 14 — Layer 8+9 complete: items 31, 33, 35, 36, 37, 40, 41, 43, 44. Content-aware soul drift; goal completion feeling; weather mood tendency; isolation drift; activity streak effects; world event emotional weight; AffectRecord; harsh message detection; shared-interest resonance

Session 15 — Messaging reliability (message mode bypasses dice roll, protected from auto_decide override, social gate fixed). Zuzu removed (filtered on load, removed from Discord mapping). Testing/cocaine mode (POST /testing, UI toggle in admin). Discord status endpoint. Em dash stripping at _call level (covers all outputs). No-fabricated-continuity rule in autonomous messages. Active-conversation suppression (5-min window). PersonEvent — extract future plans from messages, resolve dates, inject into prompts when near. avatar.py reading image fix. Layer 6 item 23 updated (Teo only). Item 18 added (event tracking).

Session 16 — Item 32: mood-driven activity preference. Added MOOD_ACTIVITY_AFFINITY dict (all 8 moods → preferred activities). Exhaustive mood checks across all 7 activity states in auto_decide: restless/melancholic/lonely/curious/energized/irritable/serene/content each drive transitions from dream, rest, read, think, create, and message. Item 34: hit_count now drives node visual weight (log-scale radius factor, opacity/stroke boost) and displays "N resonances" in selected node panel. Items 38+39: dream recurrence now also surfaces a Want from the recurring tag (generate_dream_want in llm.py, Haiku call); seasonal_drift() added to soul.py with per-month MBTI nudges (~2 pts/trait/season at 24/7 runtime), called every tick from _tick_once.

Session 17 — Soul drift fix: ACTIVITY_DRIFT values 5× larger (0.001–0.002/tick), flutter reduced 4× (±0.0005); trait values now display to 1 decimal with trend arrows (32s rolling window). Layer 11 Personality Crystallisation complete: item 58 (soul_activity_affinity — soul traits modulate auto_decide soft-drift probabilities), item 59 (trait momentum via EMA α=0.015, amplifies/dampens drift in drift() and consolidate()), item 60 (emotional soul marks at 5 locations: harsh message +I+F, devastating article +F, beautiful article +N+P, goal completion +J, creative output +N+P), item 61 (consolidate() biased by momentum — sleep carries forward waking drift direction). Conversation soul impact: message ACTIVITY_DRIFT tripled in magnitude and now includes SN=-0.0025/tick (toward S — conversations are concrete and present); content_drift now runs on every chat() call using the full text of message + reply, so the actual content of conversations shapes the soul the same way articles do.

Session 18 — Layer 9 properly implemented. Items 41+42: preferences (lifts/drags) added to snapshot; mind tab now shows emotional history and lifts/drags sections. Item 45: explicit per-mood tone instructions in chat and autonomous message prompts. Likes/dislikes now form organically via content_affect() — scores every article/conversation/memory against soul alignment, logging affect records with real content tags. Items 43+44: replaced brittle keyword detection with read_person_emotion (Haiku, runs before reply with 6-message conversation context). Detects full emotional range (affectionate, playful, excited, grateful, tender, curious, thoughtful, neutral, tired, sad, anxious, stressed, lonely, overwhelmed, disappointed, frustrated, angry, dismissive, cold, hurt) with directed_at_chloe flag — emotions about Chloe shift her mood/soul/warmth directly; emotions about Teo's own life trigger empathy responses. _apply_emotion_reaction handles each case with graduated mood shifts, warmth boosts, feeling memories, soul marks, and meaningful affect record tags.

Session 20 — Voice app (voice_app.py) made fully functional on Linux. Fish Speech 1.5 installed in .fishvenv (Python 3.11) with patches: torchaudio.list_audio_backends removed, torchaudio.load replaced with soundfile, streaming WAV header patched for soundfile compatibility. Chloe Voice.desktop + launch_chloe.sh for no-terminal launch. Fish Speech started with --device cuda --half. Whisper on CPU (small model, int8). TTS text cleaner strips *actions* and markdown noise before sending. Voice fast path in chloe.py (_voice_chat): fires LLM immediately with minimal context, all extraction (notes, events, moments, emotion) deferred to background tasks. Voice mode uses voice=True flag through server→chloe→llm; in llm.chat this caps replies at 200 tokens and adds "spoken words only, no asterisks" instruction. Added ON/KILL buttons to voice UI. MODEL_CHAT updated to claude-sonnet-4-6.

Session 19 — Layer 10 complete: items 46+47+48+49+50+51+52 + third-party tracking extension. Item 51: _pending_outreach list on Chloe; recorded when autonomous outreach fires (both _fire_event and _send_autonomous_outreach paths); cleared immediately when person replies in chat(); _check_ignored_outreach() runs every AGE_EVERY ticks — if sent_at + 4h (10min testing) has passed and person.last_contact < sent_at, applies distance+10, warmth-0.5, mood→lonely, feeling memory + affect record; persisted across restarts. Item 50: messaging_disabled field on Person; Zuzu re-added to default_persons() with messaging_disabled=True; choose_reach_out_target filters disabled persons; discord _on_chloe_message checks flag before sending; Discord maps Zuzu for incoming but won't initiate; persons_from_dicts ensures Zuzu is always present; format_cross_person_context() matches other persons' notes/moments by tag overlap and injects naturally into chat prompt. Item 46: SharedMoment dataclass added to persons.py (text, tags, timestamp, reference_count); moments field on Person with serialization; add_moment(), format_shared_moments(), increment_moment_reference() helpers; extract_shared_moment() in llm.py (Haiku, detects memorable exchanges post-chat); _extract_and_store_moment() background task in chloe.py; shared_moments injected into chat() prompt; people tab shows moments section with reference count badges. Item 47: tone_context() rewritten with 4 distinct voice registers keyed to warmth (0–30 guarded, 30–55 warming up, 55–78 familiar, 78+ very close) — each with specific behavioral instructions about what Chloe reveals, how filtered she is, whether strangeness is allowed, whether shared history is accessible. Time-of-day modifier preserved. Applies to both chat() and generate_autonomous_message().

Session 21 (2026-04-19) — ChromaDB RAG + Idea timestamps + activity-specific RAG + deliberate graph expansion. MemoryIndex class (freshness-reranked: similarity × (0.5 + 0.5 × freshness)). Idea dataclass with timestamp+tags, migrates plain strings. _remember() helper. Chat uses RAG; background activities use meaningful query seeds (dream: last-8h tag cloud; think: active wants/goals). pick_think_expansion_target() scores leaf nodes by hit_count × recency; _think_expand_node() expands and queues labels into _graph_read_queue for read branch.

Session 22 (2026-04-19) — SQLite full migration, graph wired into all prompts and chat, cross-activity coherence, full dead-code cleanup.

Graph depth in prompts: graph_knowledge_context() — depth-3+ nodes with notes injected as "Things she's genuinely traced" in all 5 LLM call sites. match_deep_nodes_for_message() — depth-2+ nodes matching current message injected per-turn as "You've actually thought about this". _check_graph_resonance() called after every chat exchange — reinforces matching nodes, can trigger auto-expansion.
SQLite Phase 1 (store.py): ChloeDB class — WAL mode, write-through for memories/ideas/chat; lazy sync for affect_records. Auto-migration on first boot from JSON. age_memories() uses bulk SQL UPDATE.
SQLite Phase 2: Inner state tables (wants, fears, aversions, beliefs, goals, tensions) + normalised persons schema (persons + 4 sub-tables). sync_persons() upserts row then delete+reinsert sub-rows. _save() calls 8 sync methods; JSON no longer stores any list state.
Cross-activity coherence: _dream_to_idea() — 25% chance a dream generates a new Idea via Haiku; _create_to_want() — 20% chance a creative output generates a new Want.
Dead-code cleanup: removed 11 dead imports, 4 unused functions (node_exists, get_related, summarise_state, _images_root), deleted emotions.py entirely (legacy AffectEntry system, never imported).
Boot test confirmed: 153 memories, 8 wants, 5 beliefs, 2 persons all migrated correctly; JSON cleaned of list state.