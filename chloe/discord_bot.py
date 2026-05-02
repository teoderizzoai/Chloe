# chloe/discord_bot.py
# ─────────────────────────────────────────────────────────────
# Discord DM bridge for Chloe.
#
# Message pipeline (per person):
#
#   ┌─ on_message arrives
#   │    → appended to _pending[person_id]
#   │    → if INTERRUPTIBLE (debounce/think phase):
#   │         cancel current task, restart (batch is restored + combined)
#   │    → if NON-INTERRUPTIBLE (LLM/typing/sending):
#   │         leave in queue — processed after current reply is sent
#   │
#   └─ _process_pending(person_id, debounce)
#        1. [interruptible] debounce sleep   ← cancel restores pending
#        2. batch = pop(pending)
#        3. [interruptible] think sleep      ← cancel restores batch→pending
#        4. [non-interruptible] LLM call     ← new msgs queue in pending
#        5. [non-interruptible] typing delay + send
#        6. if pending non-empty → restart with short debounce
#
# Typing behaviour:
#   • Think time — 0.8–2.5s before indicator, scales with message length
#   • Typing indicator — shown during LLM call + natural hold after
#     (1.2s + len(reply)/45, max 8s)
#   • Interruptions — 38% chance to pause+resume for longer replies
# ─────────────────────────────────────────────────────────────

import asyncio
import os
import random
import re
import time
from pathlib import Path
from typing import Optional, TYPE_CHECKING

try:
    import discord
    DISCORD_AVAILABLE = True
except ImportError:
    DISCORD_AVAILABLE = False

if TYPE_CHECKING:
    from .chloe import Chloe

_AVATAR_COOLDOWN    = 330     # 5.5 min between avatar changes
_IMAGES_ROOT        = Path(__file__).resolve().parent / "images"

# ── Timing constants ──────────────────────────────────────────
_DEBOUNCE_SECS      = 2.2    # wait after last message before processing
_DEBOUNCE_FOLLOWUP  = 0.8    # shorter debounce when restarting after a reply
_THINK_MIN          = 0.8    # min think time (silent reading pause)
_THINK_MAX          = 2.5    # max think time
_THINK_PER_100CHAR  = 0.8    # extra think per 100 chars of input
_THINK_PER_FRAG     = 0.40   # extra think per additional incoming fragment

# Realistic casual texting speed — not professional typing.
# At ~6 chars/sec: a 40-char message takes ~8s to visibly type.
_TYPE_CHARS_PER_SEC = 6.0    # chars/sec (casual phone-style)
_TYPE_MIN           = 1.5    # minimum typing time per message/fragment
_TYPE_MAX           = 22.0   # maximum typing time per message/fragment

# Interruption: she pauses mid-type, reconsidering — then resumes.
_INTERRUPT_PROB     = 0.38   # probability of one pause+resume
_INTERRUPT_THRESH   = 6.0    # only interrupt if remaining typing > this
_INTERRUPT_MIN      = 1.8    # pause duration min
_INTERRUPT_MAX      = 4.5    # pause duration max

# Message fragmentation: she splits one reply into rapid-fire short messages.
# Pause is the gap between *sending* one fragment and *starting to type* the next.
_FRAG_INTER_PAUSE   = (2.0, 4.5)  # (min, max) seconds between fragments


class ChloeDiscordBot:

    def __init__(self):
        self._client:  Optional["discord.Client"] = None
        self._chloe:   Optional["Chloe"]           = None
        self._task:    Optional[asyncio.Task]       = None
        self._ready:   bool                         = False

        self._person_to_discord: dict[str, int] = {}
        self._discord_to_person: dict[int, str] = {}

        self._current_avatar_key: str   = ""
        self._last_avatar_change: float = 0.0

        # Per-person message pipeline state
        self._pending:       dict[str, list[str]]    = {}  # waiting to be processed
        self._batch:         dict[str, list[str]]    = {}  # currently in-flight
        self._timer:         dict[str, asyncio.Task] = {}  # active processing task
        self._interruptible: dict[str, bool]         = {}  # safe to cancel+restart?
        self._channels:      dict[str, "discord.DMChannel"] = {}

    # ── PUBLIC ───────────────────────────────────────────────

    async def start(self, chloe: "Chloe"):
        if not DISCORD_AVAILABLE:
            print("[discord] discord.py not installed — run: pip install discord.py")
            return
        token = os.environ.get("DISCORD_BOT_TOKEN", "").strip()
        if not token:
            print("[discord] DISCORD_BOT_TOKEN not set — Discord DMs disabled")
            return

        self._chloe = chloe
        self._load_mappings()

        intents = discord.Intents.default()
        intents.message_content = True
        self._client = discord.Client(intents=intents)

        @self._client.event
        async def on_ready():
            self._ready = True
            print(f"[discord] online as {self._client.user} "
                  f"({len(self._person_to_discord)} person(s) mapped)")
            snap = chloe.snapshot()
            await self._maybe_update_avatar(snap["avatar"]["key"], snap["avatar"]["path"])

        @self._client.event
        async def on_message(message: discord.Message):
            if not isinstance(message.channel, discord.DMChannel):
                return
            if message.author == self._client.user:
                return
            if not message.content.strip():
                return

            discord_uid = message.author.id
            person_id   = self._discord_to_person.get(discord_uid)
            if person_id is None:
                return

            self._channels[person_id] = message.channel
            self._pending.setdefault(person_id, []).append(message.content.strip())

            if self._interruptible.get(person_id, True):
                # Still in debounce or think phase → safe to cancel and restart.
                # Any in-flight batch will be restored to _pending via the
                # CancelledError handlers in _process_pending.
                old = self._timer.get(person_id)
                if old and not old.done():
                    old.cancel()
                self._timer[person_id] = asyncio.create_task(
                    self._process_pending(person_id)
                )
            # else: LLM is running — message is in _pending and will be
            # picked up automatically after the current reply is sent.

        chloe.on_message = self._on_chloe_message
        chloe.on_tick    = self._on_chloe_tick
        self._task = asyncio.create_task(self._run_bot(token))

    @property
    def is_ready(self) -> bool:
        return self._ready

    def status(self) -> dict:
        return {
            "available":      DISCORD_AVAILABLE,
            "ready":          self._ready,
            "persons_mapped": list(self._person_to_discord.keys()),
            "task_alive":     self._task is not None and not self._task.done(),
            "task_error": (
                str(self._task.exception())
                if self._task and self._task.done() and not self._task.cancelled()
                   and self._task.exception()
                else None
            ),
        }

    async def stop(self):
        if self._client and not self._client.is_closed():
            await self._client.close()
        if self._task:
            self._task.cancel()

    # ── PROCESSING PIPELINE ──────────────────────────────────

    async def _process_pending(self, person_id: str, debounce: float = None):
        """Full pipeline: debounce → think → LLM → typing → send.

        Interruptible during debounce and think phases.  If cancelled there,
        the in-flight batch is merged back into _pending so the new task gets
        the complete combined message.
        """
        db = debounce if debounce is not None else _DEBOUNCE_SECS

        # ── 1. Debounce (interruptible) ────────────────────────
        self._interruptible[person_id] = True
        try:
            await asyncio.sleep(db)
        except asyncio.CancelledError:
            self._interruptible.pop(person_id, None)
            raise   # new task already started by on_message

        # ── 2. Snapshot the pending batch ──────────────────────
        batch = list(self._pending.pop(person_id, []))
        channel = self._channels.get(person_id)
        if not batch or not channel:
            self._interruptible.pop(person_id, None)
            return

        self._batch[person_id] = batch
        combined    = " ".join(batch)
        n_fragments = len(batch)

        # ── 3. Think time (still interruptible) ────────────────
        think = self._think_time(combined, n_fragments)
        try:
            await asyncio.sleep(think)
        except asyncio.CancelledError:
            # Restore batch → pending so the new task sees everything
            saved = self._batch.pop(person_id, [])
            leftovers = self._pending.pop(person_id, [])
            self._pending[person_id] = saved + leftovers
            self._interruptible.pop(person_id, None)
            raise

        # ── 4. LLM phase (non-interruptible from here) ─────────
        self._interruptible[person_id] = False
        self._batch.pop(person_id, None)

        reply_task = asyncio.create_task(self._chloe.chat(combined, person_id=person_id))

        try:
            await self._run_typing_and_send(channel, reply_task)
        finally:
            self._interruptible.pop(person_id, None)

        # ── 5. Follow-up messages that arrived during LLM phase ─
        if self._pending.get(person_id):
            self._timer[person_id] = asyncio.create_task(
                self._process_pending(person_id, debounce=_DEBOUNCE_FOLLOWUP)
            )

    async def _run_typing_and_send(self, channel, reply_task: asyncio.Task):
        """Show typing indicator, wait for LLM, fragment if appropriate, then send."""
        typing_start = time.monotonic()

        # Show typing indicator while LLM generates the reply
        if not reply_task.done():
            async with channel.typing():
                reply = await reply_task
        else:
            reply = reply_task.result()

        if not reply:
            return   # sleeping / queued internally

        typing_elapsed = time.monotonic() - typing_start

        # Maybe split into multiple rapid-fire fragments
        fragments = self._fragment_message(reply)

        # First fragment: subtract LLM typing time already shown
        first_natural = min(_TYPE_MAX, _TYPE_MIN + len(fragments[0]) / _TYPE_CHARS_PER_SEC)
        first_extra   = first_natural - typing_elapsed

        if first_extra > 0.3:
            await self._typing_delay(channel, first_extra)

        try:
            await channel.send(fragments[0])
        except Exception as e:
            print(f"[discord] send failed: {e}")
            return

        # Subsequent fragments: typing indicator covers both the pause and the typing time,
        # so the indicator stays on continuously between fragments.
        for frag in fragments[1:]:
            pause       = random.uniform(*_FRAG_INTER_PAUSE)
            frag_natural = min(_TYPE_MAX, _TYPE_MIN + len(frag) / _TYPE_CHARS_PER_SEC)
            await self._typing_delay(channel, pause + frag_natural)
            try:
                await channel.send(frag)
            except Exception as e:
                print(f"[discord] send fragment failed: {e}")
                break

    def _fragment_message(self, text: str) -> list[str]:
        """Maybe split a reply into multiple short messages like a real texter would.

        Logic: look for natural break points (sentence endings, newlines, comma lists).
        Longer / more complex replies are more likely to be fragmented.
        Never fragments short single-thought messages.
        """
        text = text.strip()

        # Newlines are intentional breaks — always split on them regardless of length
        if '\n' in text:
            parts = [p.strip() for p in re.split(r'\n+', text) if p.strip()]
            if len(parts) > 1:
                return parts

        # Never fragment very short single-line messages
        if len(text) < 38:
            return [text]

        # Probability of fragmentation scales with content structure
        has_multi_sentence = bool(re.search(r'[.!?…]\s+\w', text))
        has_newline        = '\n' in text
        has_comma_list     = bool(re.search(r',\s+\w', text))

        if len(text) > 110 and (has_multi_sentence or has_newline):
            frag_prob = 0.48
        elif len(text) > 75 and (has_multi_sentence or has_newline):
            frag_prob = 0.28
        elif has_comma_list and len(text) > 65:
            frag_prob = 0.18
        elif len(text) > 60:
            frag_prob = 0.08
        else:
            frag_prob = 0.0

        if random.random() > frag_prob:
            return [text]

        # ── Split on sentence endings and newlines ──────────────
        parts = re.split(r'(?<=[.!?…])\s+|\n+', text)
        parts = [p.strip().rstrip('.').strip() for p in parts if p.strip()]

        # ── For longer sentence fragments, also split on comma lists ──
        result = []
        for part in parts:
            if len(part) > 45 and re.search(r',\s+\w', part) and random.random() < 0.55:
                # Split on each ", " to create atomic fragments
                sub = re.split(r',\s+', part)
                sub = [s.strip() for s in sub if s.strip()]
                result.extend(sub)
            else:
                result.append(part)

        # Filter empty, deduplicate, ensure at least 2
        result = [f for f in result if f and len(f) > 2]
        if len(result) <= 1:
            return [text]

        return result

    # ── TYPING HELPERS ───────────────────────────────────────

    def _think_time(self, combined: str, n_fragments: int) -> float:
        base = _THINK_MIN + min(len(combined) / 100, 1.0) * (_THINK_PER_100CHAR * 2)
        t    = base * random.uniform(0.85, 1.15)
        if n_fragments > 1:
            t += (n_fragments - 1) * _THINK_PER_FRAG
        return min(t, _THINK_MAX)

    async def _typing_delay(self, channel, duration: float):
        """Show typing indicator for `duration` seconds, with possible interruption."""
        if duration > _INTERRUPT_THRESH and random.random() < _INTERRUPT_PROB:
            split = duration * random.uniform(0.30, 0.55)
            pause = random.uniform(_INTERRUPT_MIN, _INTERRUPT_MAX)
            await self._trigger_typing_for(channel, split)
            await asyncio.sleep(pause)         # indicator fades — she's reconsidering
            await self._trigger_typing_for(channel, duration - split)
        else:
            await self._trigger_typing_for(channel, duration)

    async def _trigger_typing_for(self, channel, duration: float):
        """Hold the typing indicator for exactly `duration` seconds."""
        deadline = time.monotonic() + duration
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            try:
                await channel.trigger_typing()
            except Exception:
                break
            await asyncio.sleep(min(7.0, remaining))

    # ── AUTONOMOUS OUTREACH ──────────────────────────────────

    async def send_dm(self, person_id: str, message: str):
        """Autonomous DM — show natural typing delay before sending."""
        if not self._client or not self._ready:
            return
        discord_uid = self._person_to_discord.get(person_id)
        if not discord_uid:
            return
        try:
            user = await self._client.fetch_user(discord_uid)
            dm   = await user.create_dm()
            type_dur  = min(6.0, _TYPE_MIN + len(message) / _TYPE_CHARS_PER_SEC)
            type_dur *= random.uniform(0.85, 1.15)
            await self._typing_delay(dm, type_dur)
            await dm.send(message)
            print(f"[discord] → DM sent to {person_id}")
        except discord.Forbidden:
            print(f"[discord] can't DM {person_id} — DMs may be disabled")
        except Exception as e:
            print(f"[discord] DM to {person_id} failed: {e}")

    # ── CALLBACKS ────────────────────────────────────────────

    def _on_chloe_message(self, message: str, person_id: Optional[str]):
        if not person_id or not self._person_to_discord.get(person_id):
            return
        if self._chloe:
            from .persons import get_person
            p = get_person(self._chloe.persons, person_id)
            if p and p.messaging_disabled:
                return
        asyncio.ensure_future(self.send_dm(person_id, message))

    def _on_chloe_tick(self, snapshot: dict):
        avatar = snapshot.get("avatar", {})
        key  = avatar.get("key",  "")
        path = avatar.get("path", "")
        if key and key != self._current_avatar_key:
            asyncio.ensure_future(self._maybe_update_avatar(key, path))

    # ── INTERNAL ─────────────────────────────────────────────

    async def _run_bot(self, token: str):
        try:
            await self._client.start(token)
        except Exception as e:
            print(f"[discord] bot crashed: {e}")
            self._ready = False

    def _load_mappings(self):
        mapping = {
            "teo":  os.environ.get("DISCORD_TEO_ID",  "").strip(),
            "zuzu": os.environ.get("DISCORD_ZUZU_ID", "").strip(),
        }
        for person_id, raw_id in mapping.items():
            if raw_id:
                try:
                    uid = int(raw_id)
                    self._person_to_discord[person_id] = uid
                    self._discord_to_person[uid]       = person_id
                except ValueError:
                    print(f"[discord] invalid ID for {person_id}: {raw_id!r}")

    async def _maybe_update_avatar(self, key: str, path: Optional[str]):
        if not self._client or not self._ready or not path:
            return
        now = time.monotonic()
        if now - self._last_avatar_change < _AVATAR_COOLDOWN:
            return
        rel      = path.removeprefix("/media/chloe/")
        img_path = _IMAGES_ROOT / rel
        if not img_path.is_file():
            return
        try:
            await self._client.user.edit(avatar=img_path.read_bytes())
            self._current_avatar_key = key
            self._last_avatar_change = now
            print(f"[discord] avatar → {key}")
        except discord.HTTPException as e:
            if e.status == 429:
                print("[discord] avatar rate-limited — will retry next state change")
            else:
                print(f"[discord] avatar update failed: {e}")
        except Exception as e:
            print(f"[discord] avatar update error: {e}")
