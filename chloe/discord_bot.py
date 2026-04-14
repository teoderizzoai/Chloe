# chloe/discord_bot.py
# ─────────────────────────────────────────────────────────────
# Discord DM bridge for Chloe.
#
# Chloe talks to Teo and Zuzu via Discord DMs — never in a server.
# Incoming DMs → routed to chloe.chat() → reply sent back.
# Autonomous outreach → Chloe sends a DM unprompted.
# Avatar → updates to match Chloe's activity/mood (rate-limited).
#
# Setup (Discord Developer Portal):
#   1. Create a bot at https://discord.com/developers/applications
#   2. Under Bot → Privileged Gateway Intents:
#      enable "Message Content Intent"
#   3. Copy the bot token → DISCORD_BOT_TOKEN in .env
#   4. Get each person's Discord user ID (Settings → Advanced → Developer Mode,
#      then right-click their name → Copy User ID)
#      → DISCORD_TEO_ID and DISCORD_ZUZU_ID in .env
#   5. Invite the bot to your server so it can DM members:
#      OAuth2 → URL Generator → scope: bot → permission: Send Messages → invite
#
# Environment variables (.env):
#   DISCORD_BOT_TOKEN=...
#   DISCORD_TEO_ID=123456789
#   DISCORD_ZUZU_ID=987654321
# ─────────────────────────────────────────────────────────────

import asyncio
import os
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

# Discord rate-limits avatar changes to ~2 per 10 minutes.
# We wait at least this many seconds between updates.
_AVATAR_COOLDOWN = 330   # 5.5 min — safe margin

# Absolute path to the images folder
_IMAGES_ROOT = Path(__file__).resolve().parent / "images"


class ChloeDiscordBot:
    """Discord DM bridge. Runs as a background task in the same event loop as FastAPI."""

    def __init__(self):
        self._client: Optional["discord.Client"] = None
        self._chloe:  Optional["Chloe"] = None
        self._task:   Optional[asyncio.Task] = None
        self._ready:  bool = False

        # person_id ("teo" | "roommate") ↔ Discord user ID (int)
        self._person_to_discord: dict[str, int] = {}
        self._discord_to_person: dict[int, str] = {}

        # Avatar state tracking
        self._current_avatar_key: str  = ""     # e.g. "activity:sleep"
        self._last_avatar_change: float = 0.0   # monotonic timestamp

    # ── PUBLIC ───────────────────────────────────────────────

    async def start(self, chloe: "Chloe"):
        """Start the bot. Registers itself as Chloe's on_message and on_tick callbacks."""
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
        intents.message_content = True   # privileged — must be enabled in Dev Portal

        self._client = discord.Client(intents=intents)

        @self._client.event
        async def on_ready():
            self._ready = True
            print(f"[discord] online as {self._client.user} "
                  f"({len(self._person_to_discord)} person(s) mapped)")
            # Set avatar immediately on boot to match current state
            snap = chloe.snapshot()
            await self._maybe_update_avatar(
                snap["avatar"]["key"],
                snap["avatar"]["path"],
            )

        @self._client.event
        async def on_message(message: discord.Message):
            # Only handle DMs, never server messages
            if not isinstance(message.channel, discord.DMChannel):
                return
            # Ignore the bot's own messages
            if message.author == self._client.user:
                return
            # Ignore empty messages
            if not message.content.strip():
                return

            discord_uid = message.author.id
            person_id   = self._discord_to_person.get(discord_uid)

            if person_id is None:
                # Unknown user — silently ignore
                return

            # Route to Chloe and send reply
            async with message.channel.typing():
                reply = await self._chloe.chat(message.content.strip(), person_id=person_id)

            if reply:
                await message.channel.send(reply)

        # Register outbound callbacks on Chloe
        chloe.on_message = self._on_chloe_message
        chloe.on_tick    = self._on_chloe_tick

        # Start the Discord client as a background task
        self._task = asyncio.create_task(self._run_bot(token))

    @property
    def is_ready(self) -> bool:
        return self._ready

    def status(self) -> dict:
        """Return connection status — used by the /discord/status endpoint."""
        return {
            "available":  DISCORD_AVAILABLE,
            "ready":      self._ready,
            "persons_mapped": list(self._person_to_discord.keys()),
            "task_alive": self._task is not None and not self._task.done(),
            "task_error": (
                str(self._task.exception())
                if self._task and self._task.done() and not self._task.cancelled()
                and self._task.exception()
                else None
            ),
        }

    async def stop(self):
        """Graceful shutdown."""
        if self._client and not self._client.is_closed():
            await self._client.close()
        if self._task:
            self._task.cancel()

    # ── INTERNAL ─────────────────────────────────────────────

    async def _run_bot(self, token: str):
        """Wrapper around client.start() that logs errors instead of silently dying."""
        try:
            await self._client.start(token)
        except Exception as e:
            print(f"[discord] bot crashed: {e}")
            self._ready = False

    def _load_mappings(self):
        """Read Discord user IDs from environment variables."""
        mapping = {
            "teo": os.environ.get("DISCORD_TEO_ID", "").strip(),
        }
        for person_id, raw_id in mapping.items():
            if raw_id:
                try:
                    uid = int(raw_id)
                    self._person_to_discord[person_id] = uid
                    self._discord_to_person[uid]       = person_id
                except ValueError:
                    print(f"[discord] invalid ID for {person_id}: {raw_id!r}")

    def _on_chloe_message(self, message: str, person_id: Optional[str]):
        """Called by chloe.py when she fires an autonomous message."""
        if person_id and self._person_to_discord.get(person_id):
            asyncio.ensure_future(self.send_dm(person_id, message))

    def _on_chloe_tick(self, snapshot: dict):
        """Called every heartbeat tick with the full snapshot.
        Schedules an avatar update if the key has changed and cooldown allows."""
        avatar = snapshot.get("avatar", {})
        key  = avatar.get("key",  "")
        path = avatar.get("path", "")
        if key and key != self._current_avatar_key:
            asyncio.ensure_future(self._maybe_update_avatar(key, path))

    async def _maybe_update_avatar(self, key: str, path: Optional[str]):
        """Update the bot's avatar if the key changed and cooldown has passed."""
        if not self._client or not self._ready:
            return
        if not path:
            return

        now = time.monotonic()
        if now - self._last_avatar_change < _AVATAR_COOLDOWN:
            return   # too soon — skip this change, next tick will retry

        # path is like "/media/chloe/Actions/Chloe_Sleep.png"
        # strip the "/media/chloe/" prefix to get the relative path
        rel = path.removeprefix("/media/chloe/")
        img_path = _IMAGES_ROOT / rel

        if not img_path.is_file():
            print(f"[discord] avatar image not found: {img_path}")
            return

        try:
            image_bytes = img_path.read_bytes()
            await self._client.user.edit(avatar=image_bytes)
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

    async def send_dm(self, person_id: str, message: str):
        """Send a DM to a person identified by their person_id."""
        if not self._client or not self._ready:
            return

        discord_uid = self._person_to_discord.get(person_id)
        if not discord_uid:
            return

        try:
            user = await self._client.fetch_user(discord_uid)
            dm   = await user.create_dm()
            await dm.send(message)
            print(f"[discord] → DM sent to {person_id}")
        except discord.Forbidden:
            print(f"[discord] can't DM {person_id} — they may have DMs disabled")
        except Exception as e:
            print(f"[discord] DM to {person_id} failed: {e}")
