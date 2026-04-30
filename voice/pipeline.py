"""
voice/pipeline.py — Zero-latency streaming voice pipeline for Chloe.

Requirements:
    pip install deepgram-sdk>=3.0.0 sounddevice soundfile numpy httpx

    Fish Speech server must be running:
        cd /path/to/fish-speech
        python -m tools.api_server --listen 0.0.0.0:8080 \\
            --checkpoint-path checkpoints/fish-speech-1.5 --device cuda --half

Flow:
    Mic → Deepgram streaming STT
        → is_final transcript  →  interjection (immediate) + LLM call (concurrent)
        → LLM reply            →  Fish Speech streaming PCM → AudioPlayer
        → user speaks mid-TTS  →  barge-in: stop audio instantly

Usage:
    DEEPGRAM_API_KEY=... python voice_pipeline.py
"""

import asyncio
import base64
import os
import random
import threading
from pathlib import Path
from typing import AsyncIterator, Callable, Optional

import httpx
import sounddevice as sd
import soundfile as sf

# ── Config ─────────────────────────────────────────────────────────────────

DEEPGRAM_API_KEY = os.getenv("DEEPGRAM_API_KEY", "")
CHLOE_URL        = os.getenv("CHLOE_URL",        "http://localhost:8000")
PERSON_ID        = os.getenv("CHLOE_PERSON_ID",  "teo")
FISH_URL         = os.getenv("FISH_URL",          "http://localhost:8080")
REF_AUDIO        = os.getenv("REF_AUDIO",         str(Path(__file__).parent / "sample.wav"))
REF_TEXT         = os.getenv("REF_TEXT",          "")

FISH_SAMPLE_RATE = 44100   # Fish Speech PCM output rate (int16 mono)
MIC_SAMPLE_RATE  = 16000   # Deepgram input rate

SOUNDS_DIR = Path(__file__).parent.parent / "assets" / "interjections"

# ── Interjection sound mappings ─────────────────────────────────────────────
# mood takes priority; activity fills remaining candidates.
# Generate these once with: python generate_interjections.py

MOOD_SOUNDS: dict[str, list[str]] = {
    "curious":     ["hmm.wav",     "oh.wav"     ],
    "energized":   ["oh.wav",      "ah.wav"     ],
    "melancholic": ["exhale.wav",  "mhm.wav"    ],
    "restless":    ["hmm.wav",     "ah.wav"     ],
    "serene":      ["exhale.wav",  "mhm.wav"    ],
    "content":     ["mhm.wav",     "hmm.wav"    ],
    "lonely":      ["exhale.wav",  "mhm.wav"    ],
    "irritable":   ["hmm.wav",     "exhale.wav" ],
}

ACTIVITY_SOUNDS: dict[str, list[str]] = {
    "dream":   ["ah.wav",      "oh.wav",     "mhm.wav"  ],
    "read":    ["hmm.wav",     "ah.wav",     "oh.wav"   ],
    "think":   ["hmm.wav",     "mhm.wav",    "ah.wav"   ],
    "create":  ["oh.wav",      "ah.wav",     "hmm.wav"  ],
    "message": ["mhm.wav",     "oh.wav",     "hmm.wav"  ],
    "rest":    ["mhm.wav",     "exhale.wav", "hmm.wav"  ],
    "sleep":   ["exhale.wav",  "mhm.wav",    "hmm.wav"  ],
}

_FALLBACK_SOUNDS = ["hmm.wav", "oh.wav", "ah.wav"]


# ── InterjectionManager ────────────────────────────────────────────────────

class InterjectionManager:
    """Plays a short mood/activity-appropriate vocalisation the instant an utterance ends."""

    def play(
        self,
        activity: Optional[str] = None,
        mood: Optional[str] = None,
    ) -> Optional[threading.Thread]:
        # mood first, then activity to fill remaining slots (no duplicates)
        candidates: list[str] = list(MOOD_SOUNDS.get(mood or "", []))
        for s in ACTIVITY_SOUNDS.get(activity or "", []):
            if s not in candidates:
                candidates.append(s)
        if not candidates:
            candidates = list(_FALLBACK_SOUNDS)

        available = [c for c in candidates if (SOUNDS_DIR / c).exists()]
        if not available:
            available = [c for c in _FALLBACK_SOUNDS if (SOUNDS_DIR / c).exists()]
        if not available:
            return None

        path   = SOUNDS_DIR / random.choice(available)
        thread = threading.Thread(target=self._play_file, args=(path,), daemon=True)
        thread.start()
        return thread

    @staticmethod
    def _play_file(path: Path) -> None:
        try:
            data, sr = sf.read(str(path), dtype="float32")
            sd.play(data, samplerate=sr)
            sd.wait()
        except Exception as e:
            print(f"[interjection] {e}")


# ── AudioPlayer ────────────────────────────────────────────────────────────

class AudioPlayer:
    """
    Streams raw int16 PCM chunks from Fish Speech to the speaker.
    Interruption (barge-in) closes the stream immediately.
    """

    def __init__(self) -> None:
        self._stream: Optional[sd.RawOutputStream] = None
        self._lock    = threading.Lock()
        self._playing = False

    @property
    def is_playing(self) -> bool:
        return self._playing

    def interrupt(self) -> None:
        with self._lock:
            self._playing = False
            if self._stream is not None:
                try:
                    self._stream.abort()
                    self._stream.close()
                except Exception:
                    pass
                self._stream = None

    async def play_stream(self, chunks: AsyncIterator[bytes]) -> None:
        self.interrupt()
        self._playing = True

        stream = sd.RawOutputStream(
            samplerate=FISH_SAMPLE_RATE,
            channels=1,
            dtype="int16",
            blocksize=4096,
        )
        with self._lock:
            self._stream = stream

        stream.start()
        try:
            async for chunk in chunks:
                if not self._playing:
                    break
                stream.write(chunk)
        finally:
            with self._lock:
                self._playing = False
                if self._stream is stream:
                    try:
                        stream.stop()
                        stream.close()
                    except Exception:
                        pass
                    self._stream = None


# ── Fish Speech streaming TTS ──────────────────────────────────────────────

async def fish_tts_stream(text: str) -> AsyncIterator[bytes]:
    """Async generator: yields raw int16 PCM bytes from the local Fish Speech server."""
    payload: dict = {
        "text":         text,
        "format":       "pcm",
        "streaming":    True,
        "chunk_length": 100,
    }
    if os.path.exists(REF_AUDIO):
        with open(REF_AUDIO, "rb") as f:
            payload["references"] = [{"audio": base64.b64encode(f.read()).decode(), "text": REF_TEXT}]

    async with httpx.AsyncClient(timeout=None) as client:
        async with client.stream("POST", f"{FISH_URL}/v1/tts", json=payload) as resp:
            resp.raise_for_status()
            async for chunk in resp.aiter_bytes(chunk_size=4096):
                if chunk:
                    yield chunk


# ── Chloe LLM ─────────────────────────────────────────────────────────────

async def ask_chloe(text: str) -> str:
    try:
        async with httpx.AsyncClient(timeout=60) as client:
            r = await client.post(
                f"{CHLOE_URL}/chat",
                json={"message": text, "person_id": PERSON_ID, "voice": True},
            )
            r.raise_for_status()
            return r.json().get("reply", "")
    except Exception as e:
        print(f"[LLM] {e}")
        return ""


# ── Snapshot helper ────────────────────────────────────────────────────────

async def fetch_activity_mood() -> tuple[str, str]:
    """Returns (activity, mood) from the Chloe brain snapshot."""
    try:
        async with httpx.AsyncClient(timeout=2) as client:
            r = await client.get(f"{CHLOE_URL}/snapshot")
            r.raise_for_status()
            data = r.json()
            return data.get("activity", ""), data.get("affect", {}).get("mood", "")
    except Exception:
        return "", ""


# ── VoicePipeline ──────────────────────────────────────────────────────────

class VoicePipeline:
    """
    Always-on streaming voice pipeline.

    On utterance end (Deepgram is_final=True):
      1. Fetch snapshot → get current activity + mood.
      2. Fire interjection immediately.
      3. Concurrently send message to Chloe LLM.
      4. Wait for interjection to finish.
      5. Stream Fish Speech TTS → AudioPlayer.

    Barge-in (SpeechStarted while playing): AudioPlayer.interrupt().

    Optional callbacks (all called from the asyncio thread or Deepgram callback thread;
    use tkinter's after() or similar for UI thread safety):
        on_listening()        — mic detects speech start
        on_thinking()         — utterance ended, waiting for LLM
        on_speaking()         — TTS audio starting
        on_idle()             — TTS finished (or barge-in cleared it)
        on_user_said(text)    — final transcript
        on_chloe_said(text)   — LLM reply text
    """

    def __init__(
        self,
        on_listening:  Optional[Callable] = None,
        on_thinking:   Optional[Callable] = None,
        on_speaking:   Optional[Callable] = None,
        on_idle:       Optional[Callable] = None,
        on_user_said:  Optional[Callable] = None,
        on_chloe_said: Optional[Callable] = None,
    ) -> None:
        self._interjection  = InterjectionManager()
        self._player        = AudioPlayer()
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._busy          = False

        self._on_listening  = on_listening
        self._on_thinking   = on_thinking
        self._on_speaking   = on_speaking
        self._on_idle       = on_idle
        self._on_user_said  = on_user_said
        self._on_chloe_said = on_chloe_said

    # ── Deepgram callbacks ─────────────────────────────────────────────────

    def _on_transcript(self, _conn, result, **_):
        alt      = result.channel.alternatives[0]
        sentence = alt.transcript.strip()
        if not sentence:
            return

        if result.is_final and result.speech_final:
            print(f"\nYou: {sentence}")
            asyncio.run_coroutine_threadsafe(
                self._handle_utterance(sentence), self._loop
            )
        elif self._player.is_playing:
            # Interim transcript while Chloe is speaking → barge-in
            self._player.interrupt()
            if self._on_idle:
                self._on_idle()
            print("\n[barge-in]")

    def _on_speech_started(self, _conn, _event, **_):
        if self._on_listening:
            self._on_listening()
        if self._player.is_playing:
            self._player.interrupt()
            if self._on_idle:
                self._on_idle()
            print("\n[barge-in: speech start]")

    def _on_error(self, _conn, error, **_):
        print(f"[STT error] {error}")

    # ── Utterance handler ──────────────────────────────────────────────────

    async def _handle_utterance(self, text: str) -> None:
        if self._busy:
            return
        self._busy = True
        try:
            if self._on_thinking:
                self._on_thinking()
            if self._on_user_said:
                self._on_user_said(text)

            # fetch snapshot + fire interjection + LLM all start here
            activity, mood = await fetch_activity_mood()
            ij_thread = self._interjection.play(activity, mood)
            reply     = await ask_chloe(text)

            if not reply:
                return

            print(f"Chloe: {reply}")
            if self._on_chloe_said:
                self._on_chloe_said(reply)

            # let the interjection finish before Chloe speaks
            if ij_thread and ij_thread.is_alive():
                await asyncio.get_event_loop().run_in_executor(
                    None, ij_thread.join, 2.0
                )

            if self._on_speaking:
                self._on_speaking()
            await self._player.play_stream(fish_tts_stream(reply))
        finally:
            self._busy = False
            if self._on_idle:
                self._on_idle()

    # ── Main run ───────────────────────────────────────────────────────────

    async def run(self) -> None:
        from deepgram import (
            DeepgramClient,
            LiveTranscriptionEvents,
            LiveOptions,
            Microphone,
        )

        self._loop = asyncio.get_running_loop()

        dg   = DeepgramClient(DEEPGRAM_API_KEY)
        conn = dg.listen.asyncwebsocket.v("1")
        conn.on(LiveTranscriptionEvents.Transcript,    self._on_transcript)
        conn.on(LiveTranscriptionEvents.SpeechStarted, self._on_speech_started)
        conn.on(LiveTranscriptionEvents.Error,         self._on_error)

        options = LiveOptions(
            model           = "nova-2",
            language        = "en",
            smart_format    = True,
            encoding        = "linear16",
            channels        = 1,
            sample_rate     = MIC_SAMPLE_RATE,
            interim_results = True,
            utterance_end_ms= "700",
            vad_events      = True,
        )

        await conn.start(options)

        mic = Microphone(conn.send)
        mic.start()
        print("Chloe is listening.  Ctrl+C to quit.\n")

        try:
            while True:
                await asyncio.sleep(0.5)
        except asyncio.CancelledError:
            pass
        finally:
            mic.finish()
            await conn.finish()
            self._player.interrupt()
            print("\n[pipeline] stopped")


# ── Entry point ────────────────────────────────────────────────────────────

def main() -> None:
    if not DEEPGRAM_API_KEY:
        raise SystemExit("Set DEEPGRAM_API_KEY before running.")

    pipeline = VoicePipeline()
    try:
        asyncio.run(pipeline.run())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
