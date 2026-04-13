# main.py
# ─────────────────────────────────────────────────────────────
# Run Chloe from the terminal.
# Type messages to chat with her.
# Type commands to change her state.
#
# Usage:
#   export ANTHROPIC_API_KEY=your_key
#   python main.py
# ─────────────────────────────────────────────────────────────

import asyncio
from chloe import Chloe

HELP = """
commands:
  /activity <id>   — set activity (sleep, dream, rest, read, think, message, create)
  /state           — print current snapshot
  /graph           — list interest graph nodes
  /memories        — list recent vivid memories
  /ideas           — list recent ideas
  /expand <id>     — expand a graph node by its id
  /quit            — save and exit
  anything else    — chat with Chloe
"""

async def main():
    print("\n── Chloe ─────────────────────────────────")
    print("Type /help for commands, or just talk.\n")

    chloe = Chloe()
    await chloe.start()

    try:
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
                chloe.set_activity(act)

            elif line == "/state":
                s = chloe.snapshot()
                print(f"\n  mbti:     {s['mbti_type']}")
                print(f"  soul:     {s['soul_desc']}")
                print(f"  energy:   {s['vitals']['energy']:.1f}%")
                print(f"  social:   {s['vitals']['social_battery']:.1f}%")
                print(f"  curiosity:{s['vitals']['curiosity']:.1f}%")
                print(f"  activity: {s['activity']}")
                print(f"  tick:     {s['tick']}\n")

            elif line == "/graph":
                for n in chloe.graph.nodes:
                    print(f"  [{n.id}] {n.label}  (depth {n.depth})")

            elif line == "/memories":
                from chloe.memory import get_vivid
                for m in get_vivid(chloe.memories, 6):
                    print(f"  [{m.type}] {m.text}")

            elif line == "/ideas":
                for idea in chloe.ideas[:5]:
                    print(f"  → {idea}")

            elif line.startswith("/expand "):
                node_id = line.split(" ", 1)[1].strip()
                await chloe.expand_node(node_id)

            elif line == "/quit":
                break

            else:
                print("chloe: ", end="", flush=True)
                reply = await chloe.chat(line)
                print(reply)

    finally:
        await chloe.stop()
        print("\nGoodbye.")


if __name__ == "__main__":
    asyncio.run(main())
