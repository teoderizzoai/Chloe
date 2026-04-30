"""voice/legacy.py — Real-time voice interface for Chloe (older interface).

Usage (from project root):
    python voice/legacy.py

Controls:
    Hold SPACE  — record your voice
    Release     — transcribe + send to Chloe + speak reply
    Q / Esc     — quit

Setup:
    1. Install Fish Speech S2 from source:
          git clone https://github.com/fishaudio/fish-speech
          cd fish-speech
          pip install -e ".[cu129]"    # or [cpu] / [cu126] / [cu128]
          huggingface-cli download fishaudio/fish-speech-1.5 --local-dir checkpoints/fish-speech-1.5

    2. Start the Fish Speech inference server (separate terminal):
          python -m tools.api_server --listen 0.0.0.0:8080 \\
              --checkpoint-path checkpoints/fish-speech-1.5

    3. Record a clean 5-15s WAV of the voice you want (no background noise)
       and set REF_AUDIO + REF_TEXT below (or as env vars).

    4. Install this script's deps:
          pip install -r requirements_voice.txt

    5. Run: python voice.py

CUDA:
    Whisper uses CUDA automatically if available.
    Force CPU: set WHISPER_DEVICE=cpu
"""

import os
import sys
import time
import queue
import base64
import threading
import io
import numpy as np
import sounddevice as sd
import httpx

# ── Config ────────────────────────────────────────────────────
CHLOE_URL       = os.getenv("CHLOE_URL",        "http://localhost:8000")
PERSON_ID       = os.getenv("CHLOE_PERSON_ID",  "teo")

WHISPER_MODEL   = os.getenv("WHISPER_MODEL",    "large-v3")
WHISPER_DEVICE  = os.getenv("WHISPER_DEVICE",   "cuda")    # "cuda" | "cpu"
WHISPER_COMPUTE = os.getenv("WHISPER_COMPUTE",  "float16") # "float16" | "int8"

# Path to your reference voice clip + exact transcript of what's said in it
REF_AUDIO       = os.getenv("REF_AUDIO", os.path.join(os.path.dirname(os.path.abspath(__file__)), "sample.wav"))
REF_TEXT        = os.getenv("REF_TEXT",  "")

# Fish Speech inference server
FISH_URL        = os.getenv("FISH_URL",  "http://localhost:8080")

SAMPLE_RATE     = 16000   # whisper input
PLAY_RATE       = 44100   # fish-speech output

# ── Model handles ─────────────────────────────────────────────
_whisper = None


def _load_whisper():
    global _whisper
    if _whisper is None:
        from faster_whisper import WhisperModel
        print(f"[STT] loading whisper {WHISPER_MODEL} on {WHISPER_DEVICE}…")
        _whisper = WhisperModel(
            WHISPER_MODEL,
            device=WHISPER_DEVICE,
            compute_type=WHISPER_COMPUTE,
        )
        print("[STT] ready")
    return _whisper


# ── Transcription ─────────────────────────────────────────────

def transcribe(audio_np: np.ndarray) -> str:
    model = _load_whisper()
    segments, _ = model.transcribe(
        audio_np,
        beam_size=5,
        language="en",
        vad_filter=True,
        vad_parameters=dict(min_silence_duration_ms=300),
    )
    return " ".join(s.text.strip() for s in segments).strip()


# ── Chat ──────────────────────────────────────────────────────

def send_to_chloe(text: str) -> str:
    try:
        r = httpx.post(
            f"{CHLOE_URL}/chat",
            json={"message": text, "person_id": PERSON_ID},
            timeout=60,
        )
        r.raise_for_status()
        return r.json().get("reply", "")
    except Exception as e:
        return f"(error reaching Chloe: {e})"


# ── TTS via Fish Speech server ────────────────────────────────

def speak(text: str):
    if not text:
        return

    payload: dict = {"text": text, "format": "wav", "streaming": False}

    if os.path.exists(REF_AUDIO):
        with open(REF_AUDIO, "rb") as f:
            audio_b64 = base64.b64encode(f.read()).decode()
        payload["references"] = [{"audio": audio_b64, "text": REF_TEXT}]
    else:
        if REF_AUDIO:
            print(f"[TTS] reference audio not found: {REF_AUDIO} — using default voice")

    try:
        r = httpx.post(f"{FISH_URL}/v1/tts", json=payload, timeout=60)
        r.raise_for_status()
    except httpx.ConnectError:
        print(f"[TTS] cannot reach Fish Speech server at {FISH_URL}")
        print("[TTS] start it with: python -m tools.api_server --listen 0.0.0.0:8080")
        return
    except Exception as e:
        print(f"[TTS] error: {e}")
        return

    try:
        import soundfile as sf
        wav_io = io.BytesIO(r.content)
        wav, sr = sf.read(wav_io, dtype="float32")
        sd.play(wav, samplerate=sr)
        sd.wait()
    except Exception as e:
        print(f"[TTS] playback error: {e}")


# ── Recorder ─────────────────────────────────────────────────

class Recorder:
    def __init__(self):
        self.is_recording = False
        self._frames: list[np.ndarray] = []
        self._stream = None

    def start(self):
        self._frames.clear()
        self.is_recording = True
        self._stream = sd.InputStream(
            samplerate=SAMPLE_RATE,
            channels=1,
            dtype="float32",
            callback=self._cb,
        )
        self._stream.start()

    def stop(self) -> np.ndarray:
        self.is_recording = False
        if self._stream:
            self._stream.stop()
            self._stream.close()
            self._stream = None
        if not self._frames:
            return np.zeros(0, dtype="float32")
        return np.concatenate(self._frames).flatten()

    def _cb(self, indata, frames, time_info, status):
        if self.is_recording:
            self._frames.append(indata.copy())


# ── Main loop ─────────────────────────────────────────────────

def run(recorder: Recorder):
    from pynput import keyboard

    print("\nChloe voice interface ready.")
    if not os.path.exists(REF_AUDIO):
        print(f"[!] REF_AUDIO not found — Fish Speech will use its default voice.")
        print(f"    Set REF_AUDIO=path/to/clip.wav and REF_TEXT='transcript'\n")
    elif not REF_TEXT:
        print(f"[!] REF_TEXT is empty — voice cloning works best with a transcript.\n")
    print("Hold SPACE to speak, release to send.  Q / Esc to quit.\n")

    stop_event = threading.Event()
    holding    = threading.Event()
    process_q  = queue.Queue()

    def on_press(key):
        if key == keyboard.Key.space and not holding.is_set():
            holding.set()
            recorder.start()
            print("● recording…", end="\r", flush=True)
        elif key == keyboard.Key.esc or (hasattr(key, "char") and key.char in ("q", "Q")):
            stop_event.set()
            return False

    def on_release(key):
        if key == keyboard.Key.space and holding.is_set():
            holding.clear()
            audio = recorder.stop()
            process_q.put(audio)
            print("  processing… ", end="\r", flush=True)

    listener = keyboard.Listener(on_press=on_press, on_release=on_release)
    listener.start()

    while not stop_event.is_set():
        try:
            audio = process_q.get(timeout=0.1)
        except queue.Empty:
            continue

        if audio.size < SAMPLE_RATE * 0.3:
            print("(too short, ignored)      ")
            continue

        text = transcribe(audio)
        if not text:
            print("(nothing heard)           ")
            continue

        print(f"You:   {text}            ")
        reply = send_to_chloe(text)
        print(f"Chloe: {reply}")
        speak(reply)

    listener.stop()
    print("\n[voice] stopped")


def main():
    _load_whisper()
    recorder = Recorder()
    run(recorder)


if __name__ == "__main__":
    main()
