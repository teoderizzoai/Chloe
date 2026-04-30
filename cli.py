# cli.py
# ─────────────────────────────────────────────────────────────
# Terminal client — talks to the running server at localhost:8000.
# One Chloe instance lives in the server; this is just a thin CLI.
#
# Usage (server must already be running):
#   uvicorn server:app --port 8000   ← in one terminal
#   python cli.py                    ← in another terminal
# ─────────────────────────────────────────────────────────────

import asyncio
import httpx
import json

API = "http://localhost:8000"
PERSON_ID = "teo"

HELP = """
commands:
  /activity <id>   — set activity (sleep, dream, rest, read, think, message, create)
  /state           — print current snapshot summary
  /graph           — list interest graph nodes
  /memories        — list recent vivid memories
  /ideas           — list recent ideas
  /expand <id>     — expand a graph node by its id
  /quit            — exit terminal (server keeps running)
  anything else    — chat with Chloe
"""


async def get(path: str):
    async with httpx.AsyncClient(timeout=30) as c:
        r = await c.get(f"{API}{path}")
        r.raise_for_status()
        return r.json()


async def post(path: str, body: dict):
    async with httpx.AsyncClient(timeout=60) as c:
        r = await c.post(f"{API}{path}", json=body)
        r.raise_for_status()
        return r.json()


async def main():
    # Check server is up
    try:
        await get("/health")
    except Exception:
        print("✗  Server not reachable at localhost:8000")
        print("   Start it first: uvicorn server:app --port 8000")
        return

    print("\n── Chloe ─────────────────────────────────")
    print("Connected to server. Type /help for commands.\n")

    while True:
        try:
            line = await asyncio.to_thread(input, "you: ")
        except (EOFError, KeyboardInterrupt):
            break

        line = line.strip()
        if not line:
            continue

        if line == "/help":
            print(HELP)

        elif line.startswith("/activity "):
            act = line.split(" ", 1)[1].strip()
            try:
                await post("/activity", {"activity_id": act})
                print(f"  activity → {act}")
            except Exception as e:
                print(f"  error: {e}")

        elif line == "/state":
            try:
                s = await get("/snapshot")
                print(f"\n  mbti:     {s['mbti_type']}")
                print(f"  soul:     {s['soul_desc']}")
                print(f"  energy:   {s['vitals']['energy']:.1f}%")
                print(f"  social:   {s['vitals']['social_battery']:.1f}%")
                print(f"  curiosity:{s['vitals']['curiosity']:.1f}%")
                print(f"  activity: {s['activity']}")
                print(f"  mood:     {s.get('affect', {}).get('mood', '?')}")
                print(f"  tick:     {s['tick']}\n")
            except Exception as e:
                print(f"  error: {e}")

        elif line == "/graph":
            try:
                s = await get("/snapshot")
                for n in s.get("graph", {}).get("nodes", []):
                    print(f"  [{n['id']}] {n['label']}  (depth {n['depth']})")
            except Exception as e:
                print(f"  error: {e}")

        elif line == "/memories":
            try:
                s = await get("/snapshot")
                mems = sorted(s.get("memories", []), key=lambda m: m.get("weight", 0), reverse=True)[:6]
                for m in mems:
                    print(f"  [{m['type']}] {m['text']}")
            except Exception as e:
                print(f"  error: {e}")

        elif line == "/ideas":
            try:
                s = await get("/snapshot")
                for idea in s.get("ideas", [])[:5]:
                    print(f"  → {idea}")
            except Exception as e:
                print(f"  error: {e}")

        elif line.startswith("/expand "):
            node_id = line.split(" ", 1)[1].strip()
            try:
                await post("/expand", {"node_id": node_id})
                print(f"  expanded {node_id}")
            except Exception as e:
                print(f"  error: {e}")

        elif line == "/quit":
            break

        else:
            print("chloe: ", end="", flush=True)
            try:
                data = await post("/chat", {"message": line, "person_id": PERSON_ID})
                if data.get("queued"):
                    print("(she's asleep — message queued)")
                else:
                    print(data.get("reply", ""))
            except Exception as e:
                print(f"  error: {e}")

    print("\nGoodbye.")


if __name__ == "__main__":
    asyncio.run(main())
