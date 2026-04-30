#!/usr/bin/env python3
"""
generate_interjections.py — Pre-bake interjection .wav files using Cartesia.

Run once:
    python generate_interjections.py

Output: assets/interjections/{hmm,oh,ah,mhm,exhale}.wav
"""

import os
import sys
from pathlib import Path

import soundfile as sf
import numpy as np
from dotenv import load_dotenv

load_dotenv()

CARTESIA_API_KEY  = os.getenv("CARTESIA_API_KEY", "")
CARTESIA_VOICE_ID = os.getenv("CARTESIA_VOICE_ID", "")
SAMPLE_RATE = 44100

OUT_DIR = Path(__file__).parent / "assets" / "interjections"

CLIPS = [
    ("uhm_1.wav",  "Uuuuhm..."),
    ("uhm_2.wav",  "Uhmmm..."),
    ("mmm_1.wav",  "Mmmmmm..."),
    ("mmm_2.wav",  "Mmmmmmmmm..."),
    ("hmm_1.wav",  "Hmmmmm..."),
    ("hmm_2.wav",  "Hmmmmmmmm..."),
    ("well_1.wav", "Weeell..."),
    ("aah_1.wav",  "Aaahh..."),
]


def generate(filename: str, text: str) -> bool:
    from cartesia import Cartesia
    client = Cartesia(api_key=CARTESIA_API_KEY)

    frames = []
    try:
        for chunk in client.tts.generate_sse(
            model_id="sonic-2",
            transcript=text,
            voice={"mode": "id", "id": CARTESIA_VOICE_ID},
            output_format={
                "container": "raw",
                "encoding": "pcm_f32le",
                "sample_rate": SAMPLE_RATE,
            },
        ):
            if chunk.audio:
                frames.append(np.frombuffer(chunk.audio, dtype="float32"))
    except Exception as e:
        print(f"  [error] {e}")
        return False

    if not frames:
        print(f"  [error] no audio received")
        return False

    audio = np.concatenate(frames)
    out_path = OUT_DIR / filename
    sf.write(str(out_path), audio, SAMPLE_RATE)
    print(f"  saved  {out_path}  ({len(audio)} samples @ {SAMPLE_RATE} Hz)")
    return True


def main() -> None:
    if not CARTESIA_API_KEY:
        raise SystemExit("Set CARTESIA_API_KEY in .env before running.")
    if not CARTESIA_VOICE_ID:
        raise SystemExit("Set CARTESIA_VOICE_ID in .env before running.")

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    print(f"Voice ID: {CARTESIA_VOICE_ID}")
    print(f"Output:   {OUT_DIR}\n")

    ok = total = 0
    for filename, text in CLIPS:
        total += 1
        print(f"generating  {filename!r}  <- {text!r}")
        if generate(filename, text):
            ok += 1

    print(f"\n{ok}/{total} clips generated.")
    if ok < total:
        sys.exit(1)


if __name__ == "__main__":
    main()
