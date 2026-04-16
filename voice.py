"""voice.py — Real-time voice interface for Chloe.

Usage:
    python voice.py

Controls:
    Hold SPACE  — record your voice
    Release     — transcribe + send to Chloe + speak reply
    Q / Esc     — quit

Setup:
    1. pip install -r requirements_voice.txt
    2. Record a clean 5-15s WAV of the voice you want (no background noise)
    3. Set REF_AUDIO and REF_TEXT below (or as env vars)
    4. Run — F5-TTS downloads its model (~3 GB) on first use

CUDA:
    Both Whisper and F5-TTS use CUDA automatically if available.
    Force CPU: set WHISPER_DEVICE=cpu and F5_DEVICE=cpu
"""

import os
import sys
import time
import queue
import threading
import numpy as np
import sounddevice as sd
import httpx

# ── Config ────────────────────────────────────────────────────
CHLOE_URL       = os.getenv("CHLOE_URL",       "http://localhost:8000")
PERSON_ID       = os.getenv("CHLOE_PERSON_ID", "teo")

WHISPER_MODEL   = os.getenv("WHISPER_MODEL",   "large-v3")
WHISPER_DEVICE  = os.getenv("WHISPER_DEVICE",  "cuda")    # "cuda" | "cpu"
WHISPER_COMPUTE = os.getenv("WHISPER_COMPUTE", "float16") # "float16" | "int8"

# Path to your reference voice clip + exact transcript of what's said in it
REF_AUDIO       = os.getenv("REF_AUDIO", "voice_sample.wav")
REF_TEXT        = os.getenv("REF_TEXT",  "")   # transcript of voice_sample.wav

F5_DEVICE       = os.getenv("F5_DEVICE", "cuda")

SAMPLE_RATE     = 16000   # whisper input
PLAY_RATE       = 24000   # f5-tts output

# ── Model handles ─────────────────────────────────────────────
_whisper = None
_f5      = None


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


def _load_f5():
    global _f5
    if _f5 is None:
        from f5_tts.api import F5TTS
        print(f"[TTS] loading F5-TTS on {F5_DEVICE}…")
        print("[TTS] (first run downloads ~3 GB — subsequent runs are instant)")
        _f5 = F5TTS(device=F5_DEVICE)
        print("[TTS] ready")
    return _f5


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


# ── TTS ───────────────────────────────────────────────────────

def speak(text: str):
    if not text or not REF_AUDIO:
        return

    if not os.path.exists(REF_AUDIO):
        print(f"[TTS] reference audio not found: {REF_AUDIO}")
        print("[TTS] set REF_AUDIO env var to your voice sample path")
        return

    tts = _load_f5()
    try:
        wav, sr, _ = tts.infer(
            ref_file=REF_AUDIO,
            ref_text=REF_TEXT,
            gen_text=text,
        )
        # wav may be a torch tensor or numpy array
        if hasattr(wav, "numpy"):
            wav = wav.numpy()
        wav = np.array(wav, dtype="float32")
        sd.play(wav, samplerate=sr)
        sd.wait()
    except Exception as e:
        print(f"[TTS] error: {e}")


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
        print(f"[!] REF_AUDIO not set — TTS disabled until you add a voice sample.")
        print(f"    Set REF_AUDIO=path/to/clip.wav and REF_TEXT='transcript'\n")
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
    if not REF_TEXT and os.path.exists(REF_AUDIO):
        print("[!] REF_TEXT is empty — F5-TTS works best when you provide the")
        print("    transcript of your reference clip. Set REF_TEXT env var.")

    _load_whisper()
    if os.path.exists(REF_AUDIO):
        _load_f5()

    recorder = Recorder()
    run(recorder)


if __name__ == "__main__":
    main()
