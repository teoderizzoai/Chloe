# server.py
# ─────────────────────────────────────────────────────────────
# FastAPI server — wraps Chloe and exposes her over HTTP.
#
# Install: pip install fastapi uvicorn
# Run:     uvicorn server:app --reload --port 8000
#
# The frontend connects to this. When deployed on a VPS,
# this is what runs 24/7.
# ─────────────────────────────────────────────────────────────

import asyncio
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
import json

from chloe import Chloe

# ── App lifecycle ─────────────────────────────────────────────

chloe: Chloe = None

@asynccontextmanager
async def lifespan(app: FastAPI):
    global chloe
    chloe = Chloe()
    await chloe.start()
    yield
    await chloe.stop()

app = FastAPI(title="Chloe", lifespan=lifespan)

# Allow the frontend (any origin during dev) to connect
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Models ────────────────────────────────────────────────────

class ChatRequest(BaseModel):
    message: str

class ActivityRequest(BaseModel):
    activity_id: str

class ExpandRequest(BaseModel):
    node_id: str

class SoulRequest(BaseModel):
    trait: str   # EI | SN | TF | JP
    value: float # 0.0–100.0

# ── Routes ───────────────────────────────────────────────────

@app.get("/snapshot")
def snapshot():
    """Full state dump — called by the frontend on every poll."""
    return chloe.snapshot()


@app.post("/chat")
async def chat(req: ChatRequest):
    """Send a message, get a reply."""
    if not req.message.strip():
        raise HTTPException(400, "Empty message")
    reply = await chloe.chat(req.message)
    return {"reply": reply}


@app.post("/activity")
def set_activity(req: ActivityRequest):
    """Manually change Chloe's current activity."""
    chloe.set_activity(req.activity_id)
    return {"ok": True, "activity": chloe.activity}


@app.post("/expand")
async def expand_node(req: ExpandRequest):
    """Expand an interest graph node."""
    await chloe.expand_node(req.node_id)
    return {"ok": True}


@app.post("/soul")
def set_soul_trait(req: SoulRequest):
    """Manually nudge a soul slider."""
    if req.trait not in ("EI", "SN", "TF", "JP"):
        raise HTTPException(400, "Unknown trait")
    val = max(0.0, min(100.0, req.value))
    setattr(chloe.soul, req.trait, val)
    return {"ok": True}


@app.get("/log")
def get_log():
    """Recent activity log."""
    return {"log": chloe.log[:40]}


@app.get("/weather")
def get_weather():
    """Current weather state and season."""
    import time
    from chloe.weather import describe_season
    t = time.localtime()
    return {
        "weather": chloe.weather.to_dict() if chloe.weather else None,
        "season":  describe_season(t.tm_mon),
    }


@app.get("/health")
def health():
    return {"alive": True, "tick": chloe._tick}
