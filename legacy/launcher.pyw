"""
Chloe Launcher — start/stop the server with a GUI.
Run with: python launcher.pyw  (or double-click if .pyw is associated with pythonw)
"""

# ── Crash logger — runs before any other import ───────────────
# Writes a log next to the exe and shows a native message box so
# errors are never silently swallowed in windowless mode.
import sys, os, traceback as _tb

def _crash_log(exc: BaseException) -> None:
    """Write full traceback to Chloe_error.log and show a message box."""
    if getattr(sys, "frozen", False):
        log_dir = os.path.dirname(sys.executable)
    else:
        log_dir = os.path.dirname(os.path.abspath(__file__))
    log_path = os.path.join(log_dir, "Chloe_error.log")
    msg = _tb.format_exc()
    try:
        with open(log_path, "w", encoding="utf-8") as f:
            f.write(msg)
    except OSError:
        pass
    # Show native Windows dialog (no tkinter needed)
    try:
        import ctypes
        ctypes.windll.user32.MessageBoxW(
            0,
            f"{type(exc).__name__}: {exc}\n\nSee {log_path} for full details.",
            "Chloe — boot error",
            0x10,  # MB_ICONERROR
        )
    except Exception:
        pass

import tkinter as tk
from tkinter import font as tkfont
import subprocess
import threading
import time, queue, urllib.request, json

# When frozen by PyInstaller, __file__ is a temp dir and sys.executable is
# the .exe itself. Walk up from the exe's location to find the project root
# (the folder that contains server.py), so the exe works from dist\ or anywhere.
if getattr(sys, 'frozen', False):
    _start = os.path.dirname(sys.executable)
    BASE_DIR = _start
    for _ in range(4):
        if os.path.exists(os.path.join(_start, 'server.py')):
            BASE_DIR = _start
            break
        _start = os.path.dirname(_start)
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PORT      = 8000
API       = f"http://localhost:{PORT}"
IMG_DIR   = os.path.join(BASE_DIR, "chloe", "images")

# Prefer venv python so all deps are present
_venv_bin = "Scripts" if sys.platform == "win32" else "bin"
_venv_exe = "python.exe" if sys.platform == "win32" else "python"
VENV_PY = os.path.join(BASE_DIR, ".venv", _venv_bin, _venv_exe)
PYTHON  = VENV_PY if os.path.exists(VENV_PY) else sys.executable

# Voice uses Python 3.11 venv (Coqui TTS doesn't support 3.12+)
VENV11_PY   = os.path.join(BASE_DIR, ".venv11", _venv_bin, _venv_exe)
VOICE_SCRIPT = os.path.join(BASE_DIR, "voice_app.py")

# ── palette (matches dashboard) ──────────────────────────────
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
GREEN   = "#3a7a5a"

# ── image map ────────────────────────────────────────────────
MOOD_IMG = {
    "content":    "Emotions/Chloe_Content.png",
    "happy":      "Emotions/Chloe_Happy.png",
    "restless":   "Emotions/Chloe_Restless.png",
    "irritable":  "Emotions/Chloe_Irritable.png",
    "melancholic":"Emotions/Chloe_Sad.png",
    "lonely":     "Emotions/Chloe_Crying.png",
    "serene":     "Emotions/Chloe_Content.png",
    "energized":  "Emotions/Chloe_Happy.png",
    "curious":    "Emotions/Chloe_Thinking.png",
}
ACTIVITY_IMG = {
    "rest":    "Actions/Chloe_Rest.png",
    "sleep":   "Actions/Chloe_Sleep.png",
    "read":    "Actions/Chloe_Reading.png",
    "think":   "Actions/Chloe_Thinking.png",
    "dream":   "Actions/Chloe_Dream.png",
    "create":  "Actions/Chloe_Create.png",
    "message": "Actions/Chloe_Texting.png",
}
OFFLINE_IMG = "Actions/Chloe_Sleep.png"


# ─────────────────────────────────────────────────────────────
class Launcher(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Chloe")
        self.resizable(False, False)
        self.configure(bg=BG)

        self._proc      = None        # uvicorn subprocess
        self._voice_proc = None       # run_voice.py subprocess
        self._log_q     = queue.Queue()
        self._running   = False
        self._voice_running = False
        self._img_cache = {}          # path → PhotoImage
        self._current_img_path = None

        self._build_ui()
        self._set_image(OFFLINE_IMG)
        self._set_status(False)
        self._drain_loop()            # start log drain
        self._poll_server()           # start snapshot poll

    # ── UI build ─────────────────────────────────────────────
    def _build_ui(self):
        try:
            from PIL import Image, ImageTk
            self._PIL = (Image, ImageTk)
        except ImportError:
            self._PIL = None

        W = 340

        # ── portrait ─────────────────────────────────────────
        self._img_label = tk.Label(self, bg=BG, bd=0, highlightthickness=0)
        self._img_label.pack()

        # ── name bar ─────────────────────────────────────────
        name_bar = tk.Frame(self, bg=BG2, pady=8)
        name_bar.pack(fill="x")

        tk.Label(name_bar, text="CHLOE", bg=BG2, fg=GOLD,
                 font=("Courier New", 15, "bold")).pack(side="left", padx=16)

        self._mood_var = tk.StringVar(value="offline")
        self._mood_lbl = tk.Label(name_bar, textvariable=self._mood_var,
                                  bg=BG2, fg=TEXT2,
                                  font=("Courier New", 8))
        self._mood_lbl.pack(side="right", padx=16)

        # ── status + button row ───────────────────────────────
        ctrl = tk.Frame(self, bg=BG2, pady=8)
        ctrl.pack(fill="x")

        self._dot = tk.Canvas(ctrl, width=10, height=10, bg=BG2,
                              bd=0, highlightthickness=0)
        self._dot.pack(side="left", padx=(16, 6))
        self._dot_oval = self._dot.create_oval(1, 1, 9, 9, fill=TEXT3, outline="")

        self._status_var = tk.StringVar(value="offline")
        tk.Label(ctrl, textvariable=self._status_var, bg=BG2, fg=TEXT2,
                 font=("Courier New", 9)).pack(side="left")

        self._btn = tk.Button(ctrl, text="TURN ON", command=self._toggle,
                              bg=BG3, fg=GOLD, activebackground=BG3,
                              activeforeground=GOLD, relief="flat",
                              font=("Courier New", 9, "bold"),
                              padx=14, pady=4, cursor="hand2",
                              bd=1, highlightthickness=1,
                              highlightbackground=GOLD2)
        self._btn.pack(side="right", padx=(4, 16))

        self._voice_btn = tk.Button(ctrl, text="VOICE", command=self._toggle_voice,
                                    bg=BG3, fg=TEXT2, activebackground=BG3,
                                    activeforeground=TEAL, relief="flat",
                                    font=("Courier New", 9, "bold"),
                                    padx=10, pady=4, cursor="hand2",
                                    bd=1, highlightthickness=1,
                                    highlightbackground=TEXT3)
        self._voice_btn.pack(side="right", padx=(4, 0))

        # separator
        tk.Frame(self, bg=BORDER, height=1).pack(fill="x")

        # ── terminal ─────────────────────────────────────────
        term_frame = tk.Frame(self, bg=BG3, pady=0)
        term_frame.pack(fill="both", expand=True)

        tk.Label(term_frame, text="TERMINAL", bg=BG3, fg=TEXT3,
                 font=("Courier New", 7), anchor="w", padx=10, pady=6
                 ).pack(fill="x")

        self._term = tk.Text(
            term_frame, bg=BG3, fg=TEXT, insertbackground=TEXT,
            font=("Courier New", 8), relief="flat", bd=0,
            wrap="word", state="disabled", width=44, height=16,
            padx=10, pady=4, selectbackground=BG2
        )
        self._term.pack(fill="both", expand=True)

        sb = tk.Scrollbar(term_frame, command=self._term.yview,
                          bg=BG3, troughcolor=BG3, relief="flat", bd=0,
                          width=6)
        sb.pack(side="right", fill="y")
        self._term.configure(yscrollcommand=sb.set)

        # tag colours
        self._term.tag_config("gold",  foreground=GOLD)
        self._term.tag_config("teal",  foreground=TEAL)
        self._term.tag_config("rose",  foreground=ROSE)
        self._term.tag_config("dim",   foreground=TEXT3)

        # window size hint (set after portrait loads)
        self.geometry(f"{W}x720")

    # ── image loading ─────────────────────────────────────────
    def _set_image(self, rel_path: str, size=(340, 340)):
        full = os.path.join(IMG_DIR, rel_path)
        if not os.path.exists(full):
            return
        if rel_path == self._current_img_path:
            return
        self._current_img_path = rel_path

        if self._PIL:
            Image, ImageTk = self._PIL
            if rel_path not in self._img_cache:
                img = Image.open(full).convert("RGB")
                img.thumbnail(size, Image.LANCZOS)
                # darken when offline
                if not self._running:
                    from PIL import ImageEnhance
                    img = ImageEnhance.Brightness(img).enhance(0.45)
                photo = ImageTk.PhotoImage(img)
                self._img_cache[rel_path] = photo
            self._img_label.configure(image=self._img_cache[rel_path],
                                      width=size[0], height=size[1])
        else:
            # fallback: coloured rectangle
            self._img_label.configure(bg=BG2, width=42, height=28, text="")

    def _refresh_image_for_state(self, snapshot=None):
        if not self._running:
            self._img_cache.clear()        # force re-darken on next call
            self._current_img_path = None
            self._set_image(OFFLINE_IMG)
            return
        if snapshot:
            # prefer avatar path from server (already has mood/activity info)
            av = snapshot.get("avatar", {})
            rel = av.get("path", "")
            # paths from server look like "/media/chloe/Emotions/Chloe_Happy.png"
            # map to local path
            for sub in ("Emotions/", "Actions/"):
                if sub in rel:
                    fname = rel.split(sub)[-1]
                    local = sub + fname
                    self._img_cache.clear()
                    self._current_img_path = None
                    self._set_image(local)
                    return
            # fallback: derive from activity
            act = snapshot.get("activity", "rest")
            self._img_cache.clear()
            self._current_img_path = None
            self._set_image(ACTIVITY_IMG.get(act, OFFLINE_IMG))

    # ── status helpers ────────────────────────────────────────
    def _set_status(self, alive: bool, mood: str = ""):
        self._running = alive
        if alive:
            self._dot.itemconfig(self._dot_oval, fill=TEAL)
            self._status_var.set("running  ·  port 8000")
            self._btn.configure(text="TURN OFF", fg=ROSE,
                                highlightbackground=ROSE)
            self._mood_var.set(mood if mood else "")
        else:
            self._dot.itemconfig(self._dot_oval, fill=TEXT3)
            self._status_var.set("offline")
            self._btn.configure(text="TURN ON", fg=GOLD,
                                highlightbackground=GOLD2)
            self._mood_var.set("offline")

    # ── start / stop ──────────────────────────────────────────
    def _toggle(self):
        if self._running:
            self._stop()
        else:
            self._start()

    def _start(self):
        self._log("starting chloe on port 8000…", "gold")
        self._btn.configure(state="disabled")
        cmd = [PYTHON, "-m", "uvicorn", "server:app", "--port", str(PORT)]
        self._proc = subprocess.Popen(
            cmd,
            cwd=BASE_DIR,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
        )
        threading.Thread(target=self._read_proc, daemon=True).start()
        self.after(2000, self._enable_btn)

    def _stop(self):
        self._log("shutting down…", "rose")
        self._btn.configure(state="disabled")
        if self._proc and self._proc.poll() is None:
            self._proc.terminate()
            threading.Thread(target=self._wait_proc, daemon=True).start()
        else:
            self._set_status(False)
            self._refresh_image_for_state()
            self._btn.configure(state="normal")

    def _wait_proc(self):
        if self._proc:
            try:
                self._proc.wait(timeout=8)
            except subprocess.TimeoutExpired:
                self._proc.kill()
        self.after(0, lambda: (
            self._set_status(False),
            self._refresh_image_for_state(),
            self._log("chloe is offline.", "dim"),
            self._btn.configure(state="normal"),
        ))

    def _enable_btn(self):
        self._btn.configure(state="normal")

    # ── voice start / stop ────────────────────────────────────
    def _toggle_voice(self):
        if self._voice_running:
            self._stop_voice()
        else:
            self._start_voice()

    def _start_voice(self):
        py = VENV11_PY if os.path.exists(VENV11_PY) else PYTHON
        if not os.path.exists(VOICE_SCRIPT):
            self._log("run_voice.py not found.", "rose")
            return
        self._log(f"starting voice ({os.path.basename(py)})…", "gold")
        self._voice_btn.configure(state="disabled")
        self._voice_proc = subprocess.Popen(
            [py, VOICE_SCRIPT],
            cwd=BASE_DIR,
            creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
        )
        self._voice_running = True
        self._set_voice_status(True)
        threading.Thread(target=self._watch_voice, daemon=True).start()

    def _stop_voice(self):
        self._log("stopping voice…", "rose")
        if self._voice_proc and self._voice_proc.poll() is None:
            self._voice_proc.terminate()
        self._voice_running = False
        self._set_voice_status(False)

    def _watch_voice(self):
        """Wait for voice process to exit, then update button state."""
        if self._voice_proc:
            self._voice_proc.wait()
        self.after(0, lambda: (
            setattr(self, "_voice_running", False),
            self._set_voice_status(False),
            self._log("voice closed.", "dim"),
        ))

    def _set_voice_status(self, active: bool):
        if active:
            self._voice_btn.configure(
                fg=TEAL, highlightbackground=TEAL, state="normal", text="VOICE ●"
            )
        else:
            self._voice_btn.configure(
                fg=TEXT2, highlightbackground=TEXT3, state="normal", text="VOICE"
            )

    # ── subprocess output reader (runs in thread) ─────────────
    def _read_proc(self):
        for line in self._proc.stdout:
            self._log_q.put(line.rstrip())
        self._log_q.put(None)   # sentinel

    # ── log drain (runs in GUI thread via after) ───────────────
    def _drain_loop(self):
        try:
            while True:
                item = self._log_q.get_nowait()
                if item is None:
                    # process ended
                    if self._running:
                        self._set_status(False)
                        self._refresh_image_for_state()
                        self._log("process exited.", "rose")
                        self._btn.configure(state="normal")
                else:
                    tag = "teal" if "Started" in item or "Application startup" in item else "dim"
                    self._log(item, tag)
        except Exception:
            pass
        self.after(120, self._drain_loop)

    def _log(self, text: str, tag: str = ""):
        self._term.configure(state="normal")
        ts = time.strftime("%H:%M:%S")
        self._term.insert("end", f"[{ts}] ", "dim")
        self._term.insert("end", text + "\n", tag or "")
        self._term.see("end")
        self._term.configure(state="disabled")

    # ── snapshot poll (checks if server is alive) ─────────────
    def _poll_server(self):
        threading.Thread(target=self._fetch_snapshot, daemon=True).start()
        self.after(4000, self._poll_server)

    def _fetch_snapshot(self):
        try:
            with urllib.request.urlopen(f"{API}/snapshot", timeout=2) as r:
                snap = json.loads(r.read())
            self.after(0, lambda: self._on_snapshot(snap))
        except Exception:
            self.after(0, self._on_server_down)

    def _on_snapshot(self, snap):
        if not self._running:
            self._set_status(True)
            self._log("chloe is online.", "teal")
        mood = snap.get("affect", {}).get("mood", "")
        self._set_status(True, mood)
        self._refresh_image_for_state(snap)

    def _on_server_down(self):
        if self._running and (self._proc is None or self._proc.poll() is not None):
            self._set_status(False)
            self._refresh_image_for_state()

    # ── clean shutdown ────────────────────────────────────────
    def destroy(self):
        if self._proc and self._proc.poll() is None:
            self._proc.terminate()
        if self._voice_proc and self._voice_proc.poll() is None:
            self._voice_proc.terminate()
        super().destroy()


if __name__ == "__main__":
    try:
        app = Launcher()
        app.mainloop()
    except BaseException as _e:
        _crash_log(_e)
        raise
