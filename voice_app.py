#!/usr/bin/env python3
"""
voice_app.py — Self-contained Chloe voice chat.

Starts the Chloe brain server and Fish Speech TTS server automatically,
then runs the voice UI. Hold F1 anywhere to speak; release to send.
Everything shuts down cleanly when the window is closed.

Run:
    python voice_app.py

    # Or after: chmod +x voice_app.py
    ./voice_app.py

Config (env vars):
    CHLOE_DIR         — path to Chloe project root   (default: dir of this file)
    FISH_SPEECH_DIR   — path to fish-speech repo root (required if not next to Chloe)
    FISH_CHECKPOINT   — checkpoint folder name        (default: fish-speech-1.5)
    CHLOE_PORT        — brain server port             (default: 8000)
    FISH_PORT         — Fish Speech server port       (default: 8080)
    REF_AUDIO         — voice clone reference wav     (default: voice_sample.wav)
    REF_TEXT          — transcript of REF_AUDIO
    WHISPER_MODEL     — faster-whisper model size     (default: large-v3)
    WHISPER_DEVICE    — cuda | cpu                    (default: cuda)
    WHISPER_COMPUTE   — float16 | int8                (default: float16)
"""

import base64
import io
import json
import os
import queue
import signal
import subprocess
import sys
import threading
import time
import tkinter as tk
import urllib.request

import numpy as np
import sounddevice as sd
import soundfile as sf
import httpx
from pynput import keyboard

# ── Paths ─────────────────────────────────────────────────────
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

_venv_bin = "Scripts" if sys.platform == "win32" else "bin"
_venv_exe = "python.exe" if sys.platform == "win32" else "python"
VENV_PY   = os.path.join(BASE_DIR, ".venv", _venv_bin, _venv_exe)
PYTHON    = VENV_PY if os.path.exists(VENV_PY) else sys.executable

# Fish Speech repo location — look next to Chloe by default
_default_fish_dir = os.path.join(os.path.dirname(BASE_DIR), "fish-speech")
FISH_SPEECH_DIR   = os.getenv("FISH_SPEECH_DIR", _default_fish_dir)
FISH_CHECKPOINT   = os.getenv("FISH_CHECKPOINT", "fish-speech-1.5")

IMG_DIR    = os.path.join(BASE_DIR, "chloe", "images")
OFFLINE_IMG = "Actions/Chloe_Sleep.png"

# ── Network ───────────────────────────────────────────────────
CHLOE_PORT  = int(os.getenv("CHLOE_PORT", "8000"))
FISH_PORT   = int(os.getenv("FISH_PORT",  "8080"))
CHLOE_URL   = f"http://localhost:{CHLOE_PORT}"
FISH_URL    = f"http://localhost:{FISH_PORT}"

# ── Voice config ──────────────────────────────────────────────
PERSON_ID       = "teo"
REF_AUDIO       = os.getenv("REF_AUDIO", os.path.join(BASE_DIR, "voice_sample.wav"))
REF_TEXT        = os.getenv("REF_TEXT",  "")
WHISPER_MODEL   = os.getenv("WHISPER_MODEL",   "small")
WHISPER_DEVICE  = os.getenv("WHISPER_DEVICE",  "cpu")
WHISPER_COMPUTE = os.getenv("WHISPER_COMPUTE", "int8")
SAMPLE_RATE     = 16000

# ── Palette ───────────────────────────────────────────────────
BG      = "#07080a"
BG2     = "#0d0f12"
BG3     = "#121519"
BORDER  = "#1c2028"
TEXT    = "#8a9ab0"
TEXT2   = "#4a5568"
TEXT3   = "#2a3040"
GOLD    = "#c8a96e"
GOLD2   = "#8a6d3e"
TEAL    = "#3a8a7a"
ROSE    = "#8a4a5a"
AMBER   = "#b87333"

# ── Voice state machine ───────────────────────────────────────
IDLE      = "idle"
LISTENING = "listening"
THINKING  = "thinking"
SPEAKING  = "speaking"

_STATUS_LABEL = {
    IDLE:      "hold F1 to speak",
    LISTENING: "● listening",
    THINKING:  "thinking…",
    SPEAKING:  "speaking…",
}
_STATUS_COLOR = {
    IDLE:      TEXT2,
    LISTENING: ROSE,
    THINKING:  GOLD,
    SPEAKING:  TEAL,
}

# ── Lazy Whisper ──────────────────────────────────────────────
_whisper = None

def _load_whisper():
    global _whisper
    if _whisper is None:
        from faster_whisper import WhisperModel
        print(f"[STT] loading {WHISPER_MODEL} on {WHISPER_DEVICE}…")
        _whisper = WhisperModel(WHISPER_MODEL, device=WHISPER_DEVICE,
                                compute_type=WHISPER_COMPUTE)
        print("[STT] ready")
    return _whisper


# ── Audio / chat helpers ──────────────────────────────────────

def transcribe(audio_np: np.ndarray) -> str:
    model = _load_whisper()
    segs, _ = model.transcribe(
        audio_np, beam_size=5, language="en",
        vad_filter=True,
        vad_parameters=dict(min_silence_duration_ms=300),
    )
    return " ".join(s.text.strip() for s in segs).strip()


def _tts_clean(text: str) -> str:
    import re
    text = re.sub(r"\*[^*]+\*", "", text)   # remove *stage directions*
    text = re.sub(r"_[^_]+_", "", text)      # remove _emphasis_
    text = re.sub(r"\([^)]+\)", "", text)    # remove (parentheticals)
    text = re.sub(r"[#`]", "", text)         # remove markdown noise
    text = re.sub(r"\s+", " ", text).strip()
    return text


def speak(text: str):
    import ormsgpack
    text = _tts_clean(text)
    if not text:
        return
    payload: dict = {"text": text, "format": "wav", "streaming": True}
    if os.path.exists(REF_AUDIO):
        with open(REF_AUDIO, "rb") as f:
            payload["references"] = [{"audio": f.read(), "text": REF_TEXT}]
    try:
        # Collect full WAV then play — streaming WAV chunks can't be decoded mid-stream
        with httpx.stream(
            "POST",
            f"{FISH_URL}/v1/tts",
            content=ormsgpack.packb(payload),
            headers={"Content-Type": "application/msgpack"},
            timeout=60,
        ) as r:
            r.raise_for_status()
            buf = io.BytesIO()
            for chunk in r.iter_bytes(chunk_size=4096):
                buf.write(chunk)
        data = buf.getvalue()
        print(f"[TTS] received {len(data)} bytes")
        # Fix streaming WAV header: patch RIFF size and data chunk size
        if data[:4] == b"RIFF":
            import struct
            total = len(data) - 8
            data = data[:4] + struct.pack("<I", total) + data[8:]
            # find "data" chunk and patch its size
            idx = data.find(b"data", 36)
            if idx != -1:
                chunk_size = len(data) - idx - 8
                data = data[:idx+4] + struct.pack("<I", chunk_size) + data[idx+8:]
        wav, sr = sf.read(io.BytesIO(data), dtype="float32")
        print(f"[TTS] playing {len(wav)} samples at {sr} Hz")
        sd.play(wav, samplerate=sr, blocksize=4096)
        sd.wait()
    except httpx.ConnectError:
        print(f"[TTS] Fish Speech not reachable at {FISH_URL}")
    except httpx.HTTPStatusError as e:
        r.read()
        print(f"[TTS] error: {e} — body: {e.response.text[:300]}")
    except Exception as e:
        print(f"[TTS] error: {e}")


def chat(message: str) -> str:
    try:
        r = httpx.post(f"{CHLOE_URL}/chat",
                       json={"message": message, "person_id": PERSON_ID, "voice": True},
                       timeout=60)
        r.raise_for_status()
        return r.json().get("reply") or ""
    except Exception as e:
        return f"(error: {e})"


# ── Server management ─────────────────────────────────────────

def _wait_for_http(url: str, timeout: float = 60.0) -> bool:
    """Poll url until it responds 200 or timeout is reached."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            urllib.request.urlopen(url, timeout=1)
            return True
        except Exception:
            time.sleep(0.5)
    return False


class ServerManager:
    """Starts and owns the brain + TTS subprocesses."""

    def __init__(self, log_cb):
        self._log    = log_cb
        self._brain  = None
        self._fish   = None

    # ── Brain (uvicorn) ───────────────────────────────────────

    def start_brain(self) -> bool:
        self._log("starting brain server…", "gold")
        cmd = [PYTHON, "-m", "uvicorn", "server:app", "--port", str(CHLOE_PORT)]
        self._brain = subprocess.Popen(
            cmd, cwd=BASE_DIR,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, bufsize=1,
        )
        threading.Thread(target=self._drain, args=(self._brain, "[brain]"), daemon=True).start()
        ok = _wait_for_http(f"{CHLOE_URL}/health")
        if ok:
            self._log("brain server online.", "teal")
        else:
            self._log("brain server failed to start.", "rose")
        return ok

    # ── Fish Speech ───────────────────────────────────────────

    def start_fish(self) -> bool:
        if not os.path.isdir(FISH_SPEECH_DIR):
            self._log(f"fish-speech not found at {FISH_SPEECH_DIR}", "rose")
            self._log("set FISH_SPEECH_DIR env var to fix this", "rose")
            return False

        ckpt = os.path.join(FISH_SPEECH_DIR, "checkpoints", FISH_CHECKPOINT)
        if not os.path.isdir(ckpt):
            self._log(f"checkpoint not found: checkpoints/{FISH_CHECKPOINT}", "rose")
            self._log("download: huggingface-cli download fishaudio/fish-speech-1.5", "rose")
            return False

        # Fish Speech must be run from its own repo dir with its own Python env
        fish_venv_py = os.path.join(FISH_SPEECH_DIR, ".fishvenv", _venv_bin, _venv_exe)
        fish_py = fish_venv_py if os.path.exists(fish_venv_py) else PYTHON

        decoder_ckpt = os.path.join(ckpt, "firefly-gan-vq-fsq-8x1024-21hz-generator.pth")
        self._log("starting Fish Speech server…", "gold")
        cmd = [
            fish_py, "-m", "tools.api_server",
            "--listen", f"0.0.0.0:{FISH_PORT}",
            "--llama-checkpoint-path", ckpt,
            "--decoder-checkpoint-path", decoder_ckpt,
        ]
        self._fish = subprocess.Popen(
            cmd, cwd=FISH_SPEECH_DIR,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, bufsize=1,
        )
        threading.Thread(target=self._drain, args=(self._fish, "[fish]"), daemon=True).start()
        ok = _wait_for_http(f"{FISH_URL}/heartbeat", timeout=90)
        if ok:
            self._log("Fish Speech server online.", "teal")
        else:
            self._log("Fish Speech server failed to start (TTS will be silent).", "rose")
        return ok

    # ── Stop ──────────────────────────────────────────────────

    def stop(self):
        for proc, name in [(self._fish, "Fish Speech"), (self._brain, "brain")]:
            if proc and proc.poll() is None:
                print(f"[shutdown] stopping {name}…")
                proc.terminate()
                try:
                    proc.wait(timeout=6)
                except subprocess.TimeoutExpired:
                    proc.kill()

    # ── Log drain ─────────────────────────────────────────────

    def _drain(self, proc: subprocess.Popen, prefix: str):
        for line in proc.stdout:
            print(f"{prefix} {line.rstrip()}")


# ── Main app ──────────────────────────────────────────────────

class VoiceApp(tk.Tk):

    def __init__(self):
        super().__init__()
        self.title("Chloe")
        self.resizable(False, False)
        self.configure(bg=BG)
        self.attributes("-topmost", True)

        self._state     = IDLE
        self._recording = False
        self._frames: list[np.ndarray] = []
        self._stream    = None
        self._work_q: queue.Queue = queue.Queue()
        self._img_cache = {}
        self._current_img_path = None
        self._ready     = False   # True once both servers are up

        self._build_ui()
        self._set_image(OFFLINE_IMG)

        self._servers = ServerManager(log_cb=self._schedule_log)

        # Start servers + Whisper in background; enable UI when ready
        threading.Thread(target=self._startup_sequence, daemon=True).start()

        # Worker thread for transcription / chat / TTS
        threading.Thread(target=self._worker, daemon=True).start()

        # Snapshot poll for portrait / mood
        self._poll_snapshot()

        # Global key listener (disabled until servers are ready)
        self._kb_listener = keyboard.Listener(
            on_press=self._on_key_press,
            on_release=self._on_key_release,
        )
        self._kb_listener.start()

        self.protocol("WM_DELETE_WINDOW", self._on_close)

    # ── UI ────────────────────────────────────────────────────

    def _build_ui(self):
        try:
            from PIL import Image, ImageTk
            self._PIL = (Image, ImageTk)
        except ImportError:
            self._PIL = None

        # Portrait
        self._img_label = tk.Label(self, bg=BG, bd=0, highlightthickness=0)
        self._img_label.pack()

        # Name + mood + power button
        name_bar = tk.Frame(self, bg=BG2, pady=8)
        name_bar.pack(fill="x")
        tk.Label(name_bar, text="CHLOE", bg=BG2, fg=GOLD,
                 font=("Courier New", 15, "bold")).pack(side="left", padx=16)
        self._power_btn = tk.Button(
            name_bar, text="ON", bg=TEAL, fg=BG, relief="flat",
            font=("Courier New", 8, "bold"), padx=8, pady=2,
            cursor="hand2", command=self._toggle_servers,
        )
        self._power_btn.pack(side="right", padx=4)
        tk.Button(
            name_bar, text="KILL", bg=ROSE, fg=BG, relief="flat",
            font=("Courier New", 8, "bold"), padx=8, pady=2,
            cursor="hand2", command=self._kill_servers,
        ).pack(side="right", padx=4)
        self._mood_var = tk.StringVar(value="starting…")
        tk.Label(name_bar, textvariable=self._mood_var, bg=BG2, fg=TEXT2,
                 font=("Courier New", 8)).pack(side="right", padx=16)

        # Voice status
        status_bar = tk.Frame(self, bg=BG2, pady=6)
        status_bar.pack(fill="x")
        self._status_var = tk.StringVar(value="starting…")
        self._status_lbl = tk.Label(status_bar, textvariable=self._status_var,
                                    bg=BG2, fg=TEXT2,
                                    font=("Courier New", 10, "bold"))
        self._status_lbl.pack()

        # Server status dots
        dot_bar = tk.Frame(self, bg=BG2, pady=4)
        dot_bar.pack(fill="x")

        self._brain_dot, _ = self._make_dot(dot_bar, "brain")
        self._fish_dot,  _ = self._make_dot(dot_bar, "fish speech")

        tk.Frame(self, bg=BORDER, height=1).pack(fill="x")

        # Conversation log
        log_frame = tk.Frame(self, bg=BG3)
        log_frame.pack(fill="both", expand=True)
        tk.Label(log_frame, text="CONVERSATION", bg=BG3, fg=TEXT3,
                 font=("Courier New", 7), anchor="w", padx=10, pady=6).pack(fill="x")

        self._log_widget = tk.Text(
            log_frame, bg=BG3, fg=TEXT, insertbackground=TEXT,
            font=("Courier New", 8), relief="flat", bd=0,
            wrap="word", state="disabled", width=44, height=14,
            padx=10, pady=4, selectbackground=BG2,
        )
        self._log_widget.pack(fill="both", expand=True)

        sb = tk.Scrollbar(log_frame, command=self._log_widget.yview,
                          bg=BG3, troughcolor=BG3, relief="flat", bd=0, width=6)
        sb.pack(side="right", fill="y")
        self._log_widget.configure(yscrollcommand=sb.set)

        self._log_widget.tag_config("you",   foreground=GOLD)
        self._log_widget.tag_config("chloe", foreground=TEAL)
        self._log_widget.tag_config("dim",   foreground=TEXT3)
        self._log_widget.tag_config("gold",  foreground=GOLD)
        self._log_widget.tag_config("teal",  foreground=TEAL)
        self._log_widget.tag_config("rose",  foreground=ROSE)

        self.geometry("340x700")

    def _make_dot(self, parent, label: str):
        frame = tk.Frame(parent, bg=BG2)
        frame.pack(side="left", padx=(16, 4))
        dot = tk.Canvas(frame, width=8, height=8, bg=BG2, bd=0, highlightthickness=0)
        dot.pack(side="left", padx=(0, 4))
        oval = dot.create_oval(1, 1, 7, 7, fill=TEXT3, outline="")
        tk.Label(frame, text=label, bg=BG2, fg=TEXT3,
                 font=("Courier New", 7)).pack(side="left")
        return dot, oval

    def _set_dot(self, dot_canvas: tk.Canvas, alive: bool):
        oval = dot_canvas.find_all()[0]
        dot_canvas.itemconfig(oval, fill=TEAL if alive else TEXT3)

    def _set_voice_state(self, state: str):
        self._state = state
        self._status_var.set(_STATUS_LABEL[state])
        self._status_lbl.configure(fg=_STATUS_COLOR[state])

    def _write_log(self, speaker: str, text: str, tag: str = ""):
        self._log_widget.configure(state="normal")
        ts = time.strftime("%H:%M")
        self._log_widget.insert("end", f"[{ts}] ", "dim")
        if speaker:
            self._log_widget.insert("end", f"{speaker}: ", tag or speaker)
        self._log_widget.insert("end", text + "\n", tag or "")
        self._log_widget.see("end")
        self._log_widget.configure(state="disabled")

    def _schedule_log(self, text: str, tag: str = ""):
        self.after(0, lambda: self._write_log("", text, tag))

    # ── Image helpers ─────────────────────────────────────────

    def _set_image(self, rel_path: str, size=(340, 340)):
        full = os.path.join(IMG_DIR, rel_path)
        if not os.path.exists(full) or rel_path == self._current_img_path:
            return
        self._current_img_path = rel_path
        if self._PIL:
            Image, ImageTk = self._PIL
            if rel_path not in self._img_cache:
                img = Image.open(full).convert("RGB")
                img.thumbnail(size, Image.LANCZOS)
                self._img_cache[rel_path] = ImageTk.PhotoImage(img)
            self._img_label.configure(image=self._img_cache[rel_path],
                                      width=size[0], height=size[1])
        else:
            self._img_label.configure(bg=BG2, width=42, height=22, text="")

    def _apply_snapshot(self, snap: dict):
        self._mood_var.set(snap.get("affect", {}).get("mood", ""))
        av  = snap.get("avatar", {})
        rel = av.get("path", "")
        _ACT = {
            "rest": "Actions/Chloe_Rest.png", "sleep": "Actions/Chloe_Sleep.png",
            "read": "Actions/Chloe_Reading.png", "think": "Actions/Chloe_Thinking.png",
            "dream": "Actions/Chloe_Dream.png", "create": "Actions/Chloe_Create.png",
            "message": "Actions/Chloe_Texting.png",
        }
        for sub in ("Emotions/", "Actions/"):
            if sub in rel:
                self._img_cache.clear(); self._current_img_path = None
                self._set_image(sub + rel.split(sub)[-1])
                return
        self._img_cache.clear(); self._current_img_path = None
        self._set_image(_ACT.get(snap.get("activity", "rest"), OFFLINE_IMG))

    def _poll_snapshot(self):
        threading.Thread(target=self._fetch_snapshot, daemon=True).start()
        self.after(4000, self._poll_snapshot)

    def _fetch_snapshot(self):
        try:
            with urllib.request.urlopen(f"{CHLOE_URL}/snapshot", timeout=2) as r:
                snap = json.loads(r.read())
            self.after(0, lambda: self._apply_snapshot(snap))
        except Exception:
            pass

    # ── Startup ───────────────────────────────────────────────

    def _startup_sequence(self):
        # Brain server
        brain_ok = self._servers.start_brain()
        self.after(0, lambda: self._set_dot(self._brain_dot, brain_ok))

        # Fish Speech server (can start in parallel with Whisper load)
        fish_thread  = threading.Thread(target=self._start_fish_async,  daemon=True)
        whisper_thread = threading.Thread(target=_load_whisper, daemon=True)
        fish_thread.start()
        whisper_thread.start()
        fish_thread.join()
        whisper_thread.join()

        if brain_ok:
            self._ready = True
            self.after(0, lambda: self._set_voice_state(IDLE))
            self.after(0, lambda: self._mood_var.set(""))
        else:
            self.after(0, lambda: self._status_var.set("brain server failed"))
        self.after(0, lambda: self._on_startup_complete(brain_ok))

    def _start_fish_async(self):
        fish_ok = self._servers.start_fish()
        self.after(0, lambda: self._set_dot(self._fish_dot, fish_ok))

    # ── Key handler (global) ──────────────────────────────────

    def _on_key_press(self, key):
        if key != keyboard.Key.f1:
            return
        if not self._ready or self._recording or self._state != IDLE:
            return
        self._recording = True
        self._frames.clear()
        self._stream = sd.InputStream(
            samplerate=SAMPLE_RATE, channels=1, dtype="float32",
            callback=self._audio_cb,
        )
        self._stream.start()
        self.after(0, lambda: self._set_voice_state(LISTENING))

    def _on_key_release(self, key):
        if key != keyboard.Key.f1 or not self._recording:
            return
        self._recording = False
        if self._stream:
            self._stream.stop()
            self._stream.close()
            self._stream = None
        audio = (np.concatenate(self._frames).flatten()
                 if self._frames else np.zeros(0, dtype="float32"))
        self._frames.clear()
        self._work_q.put(audio)
        self.after(0, lambda: self._set_voice_state(THINKING))

    def _audio_cb(self, indata, frames, time_info, status):
        if self._recording:
            self._frames.append(indata.copy())

    # ── Worker ────────────────────────────────────────────────

    def _worker(self):
        while True:
            audio = self._work_q.get()

            if audio.size < SAMPLE_RATE * 0.3:
                self.after(0, lambda: self._set_voice_state(IDLE))
                continue

            text = transcribe(audio)
            if not text:
                self.after(0, lambda: (
                    self._set_voice_state(IDLE),
                    self._write_log("", "(nothing heard)", "dim"),
                ))
                continue

            t = text
            self.after(0, lambda t=t: self._write_log("you", t, "you"))

            reply = chat(text)
            r = reply
            self.after(0, lambda r=r: self._write_log("chloe", r, "chloe"))

            self.after(0, lambda: self._set_voice_state(SPEAKING))
            speak(reply)
            self.after(0, lambda: self._set_voice_state(IDLE))

    # ── Power toggle ──────────────────────────────────────────

    def _kill_servers(self):
        import subprocess as _sp
        self._ready = False
        self._servers.stop()
        _sp.run(["fuser", "-k", f"{CHLOE_PORT}/tcp", f"{FISH_PORT}/tcp"],
                capture_output=True)
        self._set_dot(self._brain_dot, False)
        self._set_dot(self._fish_dot, False)
        self._power_btn.configure(text="OFF", bg=ROSE)
        self._status_var.set("killed")
        self._schedule_log("servers killed.", "rose")

    def _toggle_servers(self):
        if self._ready:
            # Turn off
            self._ready = False
            self._servers.stop()
            self._set_voice_state(IDLE)
            self._status_var.set("offline")
            self._power_btn.configure(text="OFF", bg=ROSE)
            self._set_dot(self._brain_dot, False)
            self._set_dot(self._fish_dot, False)
            self._schedule_log("servers stopped.", "rose")
        else:
            # Turn on
            self._power_btn.configure(text="...", bg=GOLD2, state="disabled")
            self._status_var.set("starting…")
            threading.Thread(target=self._startup_sequence, daemon=True).start()

    def _on_startup_complete(self, ok: bool):
        if ok:
            self._power_btn.configure(text="ON", bg=TEAL, state="normal")
        else:
            self._power_btn.configure(text="ERR", bg=ROSE, state="normal")

    # ── Shutdown ──────────────────────────────────────────────

    def _on_close(self):
        self._kb_listener.stop()
        if self._stream:
            self._stream.stop()
            self._stream.close()
        self._servers.stop()
        self.destroy()


if __name__ == "__main__":
    app = VoiceApp()
    app.mainloop()
