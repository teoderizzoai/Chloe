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
from dotenv import load_dotenv
from pathlib import Path
load_dotenv(Path(__file__).parent / ".env", override=True)
from fastapi import FastAPI, HTTPException, Response
from typing import Optional
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
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
    message:   str
    person_id: str = "teo"

class ActivityRequest(BaseModel):
    activity_id: str

class ExpandRequest(BaseModel):
    node_id: str

class SoulRequest(BaseModel):
    trait: str   # EI | SN | TF | JP
    value: float # 0.0–100.0

class VitalsRequest(BaseModel):
    energy:    Optional[float] = None
    social:    Optional[float] = None
    curiosity: Optional[float] = None

class AffectRequest(BaseModel):
    mood: str

# ── Routes ───────────────────────────────────────────────────

@app.get("/snapshot")
def snapshot(response: Response):
    """Full state dump — called by the frontend on every poll."""
    # Browsers may cache GET responses; stale JSON meant the UI never saw `avatar`.
    response.headers["Cache-Control"] = "no-store, max-age=0"
    return chloe.snapshot()


@app.post("/chat")
async def chat(req: ChatRequest):
    """Send a message, get a reply.
    reply is null if she's in deep sleep and the message was queued."""
    if not req.message.strip():
        raise HTTPException(400, "Empty message")
    reply = await chloe.chat(req.message, person_id=req.person_id)
    return {"reply": reply, "queued": reply is None}


@app.get("/persons")
def get_persons():
    """Relationship state for all known persons."""
    return {"persons": chloe.snapshot()["persons"]}


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


@app.post("/vitals")
def set_vitals(req: VitalsRequest):
    """Manually set vitals values."""
    v = chloe.vitals
    from chloe.heart import Vitals
    chloe.vitals = Vitals(
        energy        = max(0.0, min(100.0, req.energy    if req.energy    is not None else v.energy)),
        social_battery= max(0.0, min(100.0, req.social    if req.social    is not None else v.social_battery)),
        curiosity     = max(0.0, min(100.0, req.curiosity if req.curiosity is not None else v.curiosity)),
    )
    return {"ok": True, "vitals": chloe.vitals.to_dict()}


@app.post("/affect")
def set_affect(req: AffectRequest):
    """Manually set Chloe's mood."""
    valid = {"content","restless","irritable","melancholic","curious","serene","energized","lonely"}
    if req.mood not in valid:
        raise HTTPException(400, "Unknown mood")
    from chloe.affect import Affect
    chloe.affect = Affect(mood=req.mood, intensity=chloe.affect.intensity)
    return {"ok": True}


@app.delete("/graph/{node_id}")
def delete_graph_node(node_id: str):
    """Permanently remove a node and its edges from the interest graph."""
    from chloe.graph import remove_node
    chloe.graph = remove_node(chloe.graph, node_id)
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


# Mounted **after** API routes so `/snapshot` etc. are not shadowed.
_chloe_images_dir = Path(__file__).resolve().parent / "chloe" / "images"
if _chloe_images_dir.is_dir():
    app.mount(
        "/media/chloe",
        StaticFiles(directory=str(_chloe_images_dir)),
        name="chloe_avatar_media",
    )
