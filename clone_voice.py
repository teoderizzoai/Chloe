#!/usr/bin/env python3
"""
clone_voice.py — Upload voice_sample.wav to Cartesia and print the voice ID.

Run once:
    python clone_voice.py

Then add the printed CARTESIA_VOICE_ID to your .env file.
"""

import os
import sys
from pathlib import Path

import httpx
from dotenv import load_dotenv

load_dotenv()

CARTESIA_API_KEY = os.getenv("CARTESIA_API_KEY", "")
REF_AUDIO        = Path(os.getenv("REF_AUDIO", "voice_sample.wav"))

if not CARTESIA_API_KEY:
    raise SystemExit("Set CARTESIA_API_KEY in .env before running.")
if not REF_AUDIO.exists():
    raise SystemExit(f"Reference audio not found: {REF_AUDIO}")

print(f"Cloning voice from {REF_AUDIO} ...")

resp = httpx.post(
    "https://api.cartesia.ai/voices/clone/clip",
    headers={
        "X-API-Key": CARTESIA_API_KEY,
        "Cartesia-Version": "2024-06-10",
    },
    data={
        "name": "Chloe",
        "description": "Chloe AI companion voice",
        "language": "en",
        "mode": "similarity",
    },
    files={"clip": (REF_AUDIO.name, REF_AUDIO.open("rb"), "audio/wav")},
    timeout=60,
)

if resp.status_code != 200:
    print(f"Error {resp.status_code}: {resp.text}")
    sys.exit(1)

clone_data = resp.json()
embedding = clone_data.get("embedding")
if not embedding:
    print(f"Unexpected response: {clone_data}")
    sys.exit(1)

# Save the embedding as a named voice to get a reusable ID
save_resp = httpx.post(
    "https://api.cartesia.ai/voices",
    headers={
        "X-API-Key": CARTESIA_API_KEY,
        "Cartesia-Version": "2024-06-10",
        "Content-Type": "application/json",
    },
    json={
        "name": "Chloe",
        "description": "Chloe AI companion voice",
        "embedding": embedding,
        "language": "en",
    },
    timeout=30,
)

if save_resp.status_code not in (200, 201):
    print(f"Error saving voice {save_resp.status_code}: {save_resp.text}")
    sys.exit(1)

voice = save_resp.json()
voice_id = voice.get("id", "")

print(f"\nVoice cloned and saved successfully!")
if voice_id:
    print(f"\nAdd this to your .env:")
    print(f"CARTESIA_VOICE_ID={voice_id}")
else:
    print(f"Unexpected save response: {voice}")
