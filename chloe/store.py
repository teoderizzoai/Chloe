# chloe/store.py
# ─────────────────────────────────────────────────────────────
# SQLite persistence for all list-type state.
#
# Phase 1 tables (unbounded, write-through):
#   memories, ideas, affect_records, chat
# Phase 2 tables (bounded working sets, synced on _save()):
#   wants, fears, aversions, beliefs, goals, tensions
#   persons + person_notes, person_events, person_moments, person_third_parties
#
# Soul, vitals, affect, arc, graph stay in chloe_state.json —
# they are scalar/struct state that changes atomically, not lists.
# ─────────────────────────────────────────────────────────────

import json
import sqlite3
import time
import uuid
from pathlib import Path


DB_FILE = Path("chloe.db")


class ChloeDB:
    def __init__(self, path: Path = DB_FILE):
        self._path = path
        self._con  = sqlite3.connect(str(path), check_same_thread=False)
        self._con.row_factory = sqlite3.Row
        self._con.execute("PRAGMA journal_mode=WAL")  # safe concurrent reads
        self._create_tables()

    def _create_tables(self):
        self._con.executescript("""
            CREATE TABLE IF NOT EXISTS memories (
                id         TEXT PRIMARY KEY,
                text       TEXT NOT NULL,
                type       TEXT NOT NULL DEFAULT 'observation',
                tags       TEXT NOT NULL DEFAULT '[]',
                weight     REAL NOT NULL DEFAULT 1.0,
                confidence REAL NOT NULL DEFAULT 1.0,
                timestamp  REAL NOT NULL
            );
            CREATE TABLE IF NOT EXISTS ideas (
                id        TEXT PRIMARY KEY,
                text      TEXT NOT NULL,
                timestamp REAL NOT NULL,
                tags      TEXT NOT NULL DEFAULT '[]'
            );
            CREATE TABLE IF NOT EXISTS affect_records (
                id        TEXT PRIMARY KEY,
                mood      TEXT NOT NULL,
                cause     TEXT NOT NULL DEFAULT '',
                tags      TEXT NOT NULL DEFAULT '[]',
                timestamp REAL NOT NULL
            );
            CREATE TABLE IF NOT EXISTS chat (
                rowid      INTEGER PRIMARY KEY AUTOINCREMENT,
                from_who   TEXT    NOT NULL,
                text       TEXT    NOT NULL,
                time       TEXT    NOT NULL DEFAULT '',
                autonomous INTEGER NOT NULL DEFAULT 0,
                person_id  TEXT    NOT NULL DEFAULT 'teo',
                session    INTEGER NOT NULL DEFAULT 0,
                timestamp  REAL    NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_mem_ts   ON memories(timestamp DESC);
            CREATE INDEX IF NOT EXISTS idx_chat_pid ON chat(person_id, timestamp DESC);

            -- ── Inner state (bounded working sets, synced on save) ──
            CREATE TABLE IF NOT EXISTS wants (
                id         TEXT PRIMARY KEY,
                text       TEXT NOT NULL,
                tags       TEXT NOT NULL DEFAULT '[]',
                created_at REAL NOT NULL,
                resolved   INTEGER NOT NULL DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS fears (
                id         TEXT PRIMARY KEY,
                text       TEXT NOT NULL,
                tags       TEXT NOT NULL DEFAULT '[]',
                created_at REAL NOT NULL,
                resolved   INTEGER NOT NULL DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS aversions (
                id         TEXT PRIMARY KEY,
                text       TEXT NOT NULL,
                tags       TEXT NOT NULL DEFAULT '[]',
                created_at REAL NOT NULL
            );
            CREATE TABLE IF NOT EXISTS beliefs (
                id           TEXT PRIMARY KEY,
                text         TEXT NOT NULL,
                confidence   REAL NOT NULL DEFAULT 0.55,
                tags         TEXT NOT NULL DEFAULT '[]',
                created_at   REAL NOT NULL,
                last_updated REAL NOT NULL
            );
            CREATE TABLE IF NOT EXISTS goals (
                id         TEXT PRIMARY KEY,
                text       TEXT NOT NULL,
                tags       TEXT NOT NULL DEFAULT '[]',
                created_at REAL NOT NULL,
                resolved   INTEGER NOT NULL DEFAULT 0,
                progress   INTEGER NOT NULL DEFAULT 0,
                threshold  INTEGER NOT NULL DEFAULT 5
            );
            CREATE TABLE IF NOT EXISTS tensions (
                id          TEXT PRIMARY KEY,
                text        TEXT NOT NULL,
                tags        TEXT NOT NULL DEFAULT '[]',
                intensity   REAL NOT NULL DEFAULT 0.5,
                belief_ids  TEXT NOT NULL DEFAULT '[]',
                want_ids    TEXT NOT NULL DEFAULT '[]',
                created_at  REAL NOT NULL,
                last_fired  REAL NOT NULL
            );

            -- ── Persons (normalised relational tables) ──
            CREATE TABLE IF NOT EXISTS persons (
                id                  TEXT PRIMARY KEY,
                name                TEXT NOT NULL,
                warmth              REAL NOT NULL DEFAULT 50.0,
                distance            REAL NOT NULL DEFAULT 50.0,
                messaging_disabled  INTEGER NOT NULL DEFAULT 0,
                impression          TEXT NOT NULL DEFAULT '',
                conflict_level      REAL NOT NULL DEFAULT 0.0,
                conflict_note       TEXT NOT NULL DEFAULT '',
                conversation_count  INTEGER NOT NULL DEFAULT 0,
                last_contact        REAL,
                response_hours      TEXT NOT NULL DEFAULT '{}'
            );
            CREATE TABLE IF NOT EXISTS person_notes (
                id          TEXT PRIMARY KEY,
                person_id   TEXT NOT NULL REFERENCES persons(id) ON DELETE CASCADE,
                text        TEXT NOT NULL,
                tags        TEXT NOT NULL DEFAULT '[]',
                timestamp   REAL NOT NULL,
                followed_up INTEGER NOT NULL DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS person_events (
                id          TEXT PRIMARY KEY,
                person_id   TEXT NOT NULL REFERENCES persons(id) ON DELETE CASCADE,
                text        TEXT NOT NULL,
                date        TEXT NOT NULL DEFAULT '',
                uncertain   INTEGER NOT NULL DEFAULT 0,
                created_at  REAL NOT NULL,
                followed_up INTEGER NOT NULL DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS person_moments (
                id              TEXT PRIMARY KEY,
                person_id       TEXT NOT NULL REFERENCES persons(id) ON DELETE CASCADE,
                text            TEXT NOT NULL,
                tags            TEXT NOT NULL DEFAULT '[]',
                timestamp       REAL NOT NULL,
                reference_count INTEGER NOT NULL DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS person_third_parties (
                person_id       TEXT NOT NULL REFERENCES persons(id) ON DELETE CASCADE,
                name            TEXT NOT NULL,
                sentiment       REAL NOT NULL DEFAULT 0.0,
                note            TEXT NOT NULL DEFAULT '',
                last_mentioned  REAL NOT NULL,
                PRIMARY KEY (person_id, name)
            );
            CREATE INDEX IF NOT EXISTS idx_notes_pid  ON person_notes(person_id);
            CREATE INDEX IF NOT EXISTS idx_events_pid ON person_events(person_id);
        """)
        self._con.commit()
        self._migrate()

    def _migrate(self):
        """Add columns introduced after initial schema creation."""
        migrations = [
            ("wants",    "ALTER TABLE wants    ADD COLUMN pressure       REAL NOT NULL DEFAULT 0.0"),
            ("wants",    "ALTER TABLE wants    ADD COLUMN pressure_since REAL NOT NULL DEFAULT 0.0"),
            ("fears",    "ALTER TABLE fears    ADD COLUMN pressure       REAL NOT NULL DEFAULT 0.0"),
            ("goals",    "ALTER TABLE goals    ADD COLUMN pressure       REAL NOT NULL DEFAULT 0.0"),
            ("tensions", "ALTER TABLE tensions ADD COLUMN pressure       REAL NOT NULL DEFAULT 0.0"),
        ]
        for _, sql in migrations:
            try:
                self._con.execute(sql)
            except sqlite3.OperationalError:
                pass  # column already exists
        self._con.commit()

    # ── MEMORIES ──────────────────────────────────────────────

    def add_memory(self, m) -> None:
        self._con.execute(
            "INSERT OR REPLACE INTO memories VALUES (?,?,?,?,?,?,?)",
            (m.id, m.text, m.type, json.dumps(m.tags),
             m.weight, m.confidence, m.timestamp),
        )
        self._con.commit()

    def age_memories(self) -> None:
        """Decay all weights/confidences in a single SQL pass."""
        self._con.execute("""
            UPDATE memories SET
                weight     = MAX(0.05, weight     * 0.997),
                confidence = MAX(0.10, confidence * 0.998)
        """)
        self._con.commit()

    def load_memories(self) -> list:
        from .memory import Memory
        rows = self._con.execute(
            "SELECT * FROM memories ORDER BY timestamp DESC"
        ).fetchall()
        return [Memory(
            id=r["id"], text=r["text"], type=r["type"],
            tags=json.loads(r["tags"]),
            weight=r["weight"], confidence=r["confidence"],
            timestamp=r["timestamp"],
        ) for r in rows]

    # ── IDEAS ─────────────────────────────────────────────────

    def add_idea(self, idea) -> None:
        self._con.execute(
            "INSERT OR REPLACE INTO ideas VALUES (?,?,?,?)",
            (idea.id, idea.text, idea.timestamp, json.dumps(idea.tags)),
        )
        self._con.commit()

    def load_ideas(self) -> list:
        from .memory import Idea
        rows = self._con.execute(
            "SELECT * FROM ideas ORDER BY timestamp DESC"
        ).fetchall()
        return [Idea(
            id=r["id"],
            text=r["text"],
            timestamp=r["timestamp"],
            tags=json.loads(r["tags"]),
        ) for r in rows]

    # ── AFFECT RECORDS ────────────────────────────────────────

    def sync_affect_records(self, records: list) -> None:
        """Upsert the full in-memory list. Called from _save() every ~5 min."""
        self._con.executemany(
            "INSERT OR REPLACE INTO affect_records VALUES (?,?,?,?,?)",
            [(r.id, r.mood, r.cause, json.dumps(r.tags), r.timestamp)
             for r in records],
        )
        self._con.commit()

    def load_affect_records(self) -> list:
        from .inner import AffectRecord
        rows = self._con.execute(
            "SELECT * FROM affect_records ORDER BY timestamp DESC"
        ).fetchall()
        return [AffectRecord(
            id=r["id"], mood=r["mood"], cause=r["cause"],
            tags=json.loads(r["tags"]),
            timestamp=r["timestamp"],
        ) for r in rows]

    # ── CHAT HISTORY ──────────────────────────────────────────

    def add_chat(self, row: dict) -> None:
        self._con.execute(
            "INSERT INTO chat (from_who, text, time, autonomous, person_id, session, timestamp)"
            " VALUES (?,?,?,?,?,?,?)",
            (row["from"], row["text"], row.get("time", ""),
             1 if row.get("autonomous") else 0,
             row.get("person_id", "teo"),
             row.get("session", 0),
             time.time()),
        )
        self._con.commit()

    def load_chat(self, limit: int = 500) -> list[dict]:
        rows = self._con.execute(
            "SELECT * FROM chat ORDER BY timestamp DESC LIMIT ?", (limit,)
        ).fetchall()
        result = [{
            "from": r["from_who"], "text": r["text"],
            "time": r["time"], "autonomous": bool(r["autonomous"]),
            "person_id": r["person_id"], "session": r["session"],
        } for r in rows]
        result.reverse()
        return result

    def load_chat_for_person(self, person_id: str, limit: int = 200) -> list[dict]:
        rows = self._con.execute(
            "SELECT * FROM chat WHERE person_id=? ORDER BY timestamp DESC LIMIT ?",
            (person_id, limit),
        ).fetchall()
        result = [{
            "from": r["from_who"], "text": r["text"],
            "time": r["time"], "autonomous": bool(r["autonomous"]),
            "person_id": r["person_id"], "session": r["session"],
        } for r in rows]
        result.reverse()
        return result

    # ── ONE-TIME MIGRATION ────────────────────────────────────

    def import_from_state(self, data: dict) -> None:
        """Import memories/ideas/affect_records/chat from old JSON state dict.
        Safe to call multiple times — INSERT OR REPLACE/IGNORE is idempotent."""
        from .memory import Memory, Idea
        from .inner  import AffectRecord

        for m in data.get("memories", []):
            try:
                self.add_memory(Memory.from_dict(m))
            except Exception:
                pass

        for i in data.get("ideas", []):
            try:
                idea = Idea.from_dict(i)
                self.add_idea(idea)
            except Exception:
                pass

        for r in data.get("affect_records", []):
            try:
                self._con.execute(
                    "INSERT OR IGNORE INTO affect_records VALUES (?,?,?,?,?)",
                    (r.get("id", str(uuid.uuid4())[:8]),
                     r["mood"], r.get("cause", ""),
                     json.dumps(r.get("tags", [])),
                     float(r.get("timestamp", time.time()))),
                )
            except Exception:
                pass

        for row in data.get("chat", []):
            try:
                self._con.execute(
                    "INSERT INTO chat (from_who, text, time, autonomous, person_id, session, timestamp)"
                    " VALUES (?,?,?,?,?,?,?)",
                    (row["from"], row["text"], row.get("time", ""),
                     1 if row.get("autonomous") else 0,
                     row.get("person_id", "teo"),
                     row.get("session", 0),
                     float(row.get("timestamp", time.time()))),
                )
            except Exception:
                pass

        self._con.commit()

    # ── INNER STATE (sync-on-save) ────────────────────────────

    def sync_wants(self, wants: list) -> None:
        self._con.execute("DELETE FROM wants")
        self._con.executemany(
            "INSERT INTO wants (id,text,tags,created_at,resolved,pressure,pressure_since) VALUES (?,?,?,?,?,?,?)",
            [(w.id, w.text, json.dumps(w.tags), w.created_at, int(w.resolved),
              w.pressure, w.pressure_since)
             for w in wants])
        self._con.commit()

    def load_wants(self) -> list:
        from .inner import Want
        return [Want(id=r["id"], text=r["text"], tags=json.loads(r["tags"]),
                     created_at=r["created_at"], resolved=bool(r["resolved"]),
                     pressure=r["pressure"], pressure_since=r["pressure_since"])
                for r in self._con.execute("SELECT * FROM wants ORDER BY created_at DESC")]

    def sync_fears(self, fears: list) -> None:
        self._con.execute("DELETE FROM fears")
        self._con.executemany(
            "INSERT INTO fears (id,text,tags,created_at,resolved,pressure) VALUES (?,?,?,?,?,?)",
            [(f.id, f.text, json.dumps(f.tags), f.created_at, int(f.resolved), f.pressure)
             for f in fears])
        self._con.commit()

    def load_fears(self) -> list:
        from .inner import Fear
        return [Fear(id=r["id"], text=r["text"], tags=json.loads(r["tags"]),
                     created_at=r["created_at"], resolved=bool(r["resolved"]),
                     pressure=r["pressure"])
                for r in self._con.execute("SELECT * FROM fears ORDER BY created_at DESC")]

    def sync_aversions(self, aversions: list) -> None:
        self._con.execute("DELETE FROM aversions")
        self._con.executemany("INSERT INTO aversions VALUES (?,?,?,?)",
            [(a.id, a.text, json.dumps(a.tags), a.created_at) for a in aversions])
        self._con.commit()

    def load_aversions(self) -> list:
        from .inner import Aversion
        return [Aversion(id=r["id"], text=r["text"], tags=json.loads(r["tags"]),
                         created_at=r["created_at"])
                for r in self._con.execute("SELECT * FROM aversions ORDER BY created_at DESC")]

    def sync_beliefs(self, beliefs: list) -> None:
        self._con.execute("DELETE FROM beliefs")
        self._con.executemany("INSERT INTO beliefs VALUES (?,?,?,?,?,?)",
            [(b.id, b.text, b.confidence, json.dumps(b.tags), b.created_at, b.last_updated)
             for b in beliefs])
        self._con.commit()

    def load_beliefs(self) -> list:
        from .inner import Belief
        return [Belief(id=r["id"], text=r["text"], confidence=r["confidence"],
                       tags=json.loads(r["tags"]), created_at=r["created_at"],
                       last_updated=r["last_updated"])
                for r in self._con.execute("SELECT * FROM beliefs ORDER BY confidence DESC")]

    def sync_goals(self, goals: list) -> None:
        self._con.execute("DELETE FROM goals")
        self._con.executemany(
            "INSERT INTO goals (id,text,tags,created_at,resolved,progress,threshold,pressure) VALUES (?,?,?,?,?,?,?,?)",
            [(g.id, g.text, json.dumps(g.tags), g.created_at,
              int(g.resolved), g.progress, g.threshold, g.pressure) for g in goals])
        self._con.commit()

    def load_goals(self) -> list:
        from .inner import Goal
        return [Goal(id=r["id"], text=r["text"], tags=json.loads(r["tags"]),
                     created_at=r["created_at"], resolved=bool(r["resolved"]),
                     progress=r["progress"], threshold=r["threshold"],
                     pressure=r["pressure"])
                for r in self._con.execute("SELECT * FROM goals ORDER BY created_at DESC")]

    def sync_tensions(self, tensions: list) -> None:
        self._con.execute("DELETE FROM tensions")
        self._con.executemany(
            "INSERT INTO tensions (id,text,tags,intensity,belief_ids,want_ids,created_at,last_fired,pressure) VALUES (?,?,?,?,?,?,?,?,?)",
            [(t.id, t.text, json.dumps(t.tags), t.intensity,
              json.dumps(t.belief_ids), json.dumps(t.want_ids),
              t.created_at, t.last_fired, t.pressure) for t in tensions])
        self._con.commit()

    def load_tensions(self) -> list:
        from .inner import Tension
        return [Tension(id=r["id"], text=r["text"], tags=json.loads(r["tags"]),
                        intensity=r["intensity"],
                        belief_ids=json.loads(r["belief_ids"]),
                        want_ids=json.loads(r["want_ids"]),
                        created_at=r["created_at"], last_fired=r["last_fired"],
                        pressure=r["pressure"])
                for r in self._con.execute("SELECT * FROM tensions ORDER BY intensity DESC")]

    # ── PERSONS ───────────────────────────────────────────────

    def sync_persons(self, persons: list) -> None:
        """Upsert every person and their sub-lists. Sub-rows are replaced wholesale."""
        for p in persons:
            self._con.execute(
                "INSERT OR REPLACE INTO persons VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (p.id, p.name, p.warmth, p.distance,
                 int(p.messaging_disabled), p.impression,
                 p.conflict_level, p.conflict_note,
                 p.conversation_count, p.last_contact,
                 json.dumps(p.response_hours)),
            )
            # Replace all sub-rows for this person
            self._con.execute("DELETE FROM person_notes         WHERE person_id=?", (p.id,))
            self._con.execute("DELETE FROM person_events        WHERE person_id=?", (p.id,))
            self._con.execute("DELETE FROM person_moments       WHERE person_id=?", (p.id,))
            self._con.execute("DELETE FROM person_third_parties WHERE person_id=?", (p.id,))

            self._con.executemany(
                "INSERT INTO person_notes VALUES (?,?,?,?,?,?)",
                [(n.id, p.id, n.text, json.dumps(n.tags), n.timestamp, int(n.followed_up))
                 for n in p.notes],
            )
            self._con.executemany(
                "INSERT INTO person_events VALUES (?,?,?,?,?,?,?)",
                [(e.id, p.id, e.text, e.date, int(e.uncertain), e.created_at, int(e.followed_up))
                 for e in p.events],
            )
            self._con.executemany(
                "INSERT INTO person_moments VALUES (?,?,?,?,?,?)",
                [(m.id, p.id, m.text, json.dumps(m.tags), m.timestamp, m.reference_count)
                 for m in p.moments],
            )
            self._con.executemany(
                "INSERT INTO person_third_parties VALUES (?,?,?,?,?)",
                [(p.id, tp.name, tp.sentiment, tp.note, tp.last_mentioned)
                 for tp in p.third_parties],
            )
        self._con.commit()

    def load_persons(self) -> list:
        from .persons import Person, PersonNote, PersonEvent, SharedMoment, ThirdParty

        persons = []
        for row in self._con.execute("SELECT * FROM persons"):
            pid = row["id"]

            notes = [PersonNote(
                id=n["id"], text=n["text"], tags=json.loads(n["tags"]),
                timestamp=n["timestamp"], followed_up=bool(n["followed_up"]),
            ) for n in self._con.execute(
                "SELECT * FROM person_notes WHERE person_id=? ORDER BY timestamp DESC", (pid,))]

            events = [PersonEvent(
                id=e["id"], text=e["text"], date=e["date"],
                uncertain=bool(e["uncertain"]), created_at=e["created_at"],
                followed_up=bool(e["followed_up"]),
            ) for e in self._con.execute(
                "SELECT * FROM person_events WHERE person_id=? ORDER BY created_at DESC", (pid,))]

            moments = [SharedMoment(
                id=m["id"], text=m["text"], tags=json.loads(m["tags"]),
                timestamp=m["timestamp"], reference_count=m["reference_count"],
            ) for m in self._con.execute(
                "SELECT * FROM person_moments WHERE person_id=? ORDER BY timestamp DESC", (pid,))]

            third_parties = [ThirdParty(
                name=t["name"], sentiment=t["sentiment"],
                note=t["note"], last_mentioned=t["last_mentioned"],
            ) for t in self._con.execute(
                "SELECT * FROM person_third_parties WHERE person_id=?", (pid,))]

            persons.append(Person(
                id=pid, name=row["name"],
                warmth=row["warmth"], distance=row["distance"],
                messaging_disabled=bool(row["messaging_disabled"]),
                impression=row["impression"],
                conflict_level=row["conflict_level"],
                conflict_note=row["conflict_note"],
                conversation_count=row["conversation_count"],
                last_contact=row["last_contact"],
                response_hours=json.loads(row["response_hours"]),
                notes=notes, events=events, moments=moments,
                third_parties=third_parties,
            ))
        return persons

    # ── PHASE 2 MIGRATION ─────────────────────────────────────

    def import_inner_state(self, data: dict) -> None:
        """One-time migration of inner state from old JSON state dict."""
        from .inner import Want, Fear, Aversion, Belief, Goal, Tension
        from .persons import persons_from_dicts

        for d in data.get("wants", []):
            try: self._con.execute(
                "INSERT OR IGNORE INTO wants (id,text,tags,created_at,resolved,pressure,pressure_since) VALUES (?,?,?,?,?,?,?)",
                (d.get("id","?"), d["text"], json.dumps(d.get("tags",[])),
                 float(d.get("created_at", 0)), int(d.get("resolved", False)),
                 float(d.get("pressure", 0.0)), float(d.get("pressure_since", 0.0))))
            except Exception: pass

        for d in data.get("fears", []):
            try: self._con.execute(
                "INSERT OR IGNORE INTO fears (id,text,tags,created_at,resolved,pressure) VALUES (?,?,?,?,?,?)",
                (d.get("id","?"), d["text"], json.dumps(d.get("tags",[])),
                 float(d.get("created_at", 0)), int(d.get("resolved", False)),
                 float(d.get("pressure", 0.0))))
            except Exception: pass

        for d in data.get("aversions", []):
            try: self._con.execute("INSERT OR IGNORE INTO aversions VALUES (?,?,?,?)",
                (d.get("id","?"), d["text"], json.dumps(d.get("tags",[])),
                 float(d.get("created_at", 0))))
            except Exception: pass

        for d in data.get("beliefs", []):
            try: self._con.execute("INSERT OR IGNORE INTO beliefs VALUES (?,?,?,?,?,?)",
                (d.get("id","?"), d["text"], float(d.get("confidence", 0.55)),
                 json.dumps(d.get("tags",[])), float(d.get("created_at", 0)),
                 float(d.get("last_updated", 0))))
            except Exception: pass

        for d in data.get("goals", []):
            try: self._con.execute(
                "INSERT OR IGNORE INTO goals (id,text,tags,created_at,resolved,progress,threshold,pressure) VALUES (?,?,?,?,?,?,?,?)",
                (d.get("id","?"), d["text"], json.dumps(d.get("tags",[])),
                 float(d.get("created_at", 0)), int(d.get("resolved", False)),
                 int(d.get("progress", 0)), int(d.get("threshold", 5)),
                 float(d.get("pressure", 0.0))))
            except Exception: pass

        for d in data.get("tensions", []):
            try: self._con.execute(
                "INSERT OR IGNORE INTO tensions (id,text,tags,intensity,belief_ids,want_ids,created_at,last_fired,pressure) VALUES (?,?,?,?,?,?,?,?,?)",
                (d.get("id","?"), d["text"], json.dumps(d.get("tags",[])),
                 float(d.get("intensity", 0.5)), json.dumps(d.get("belief_ids",[])),
                 json.dumps(d.get("want_ids",[])), float(d.get("created_at", 0)),
                 float(d.get("last_fired", 0)), float(d.get("pressure", 0.0))))
            except Exception: pass

        for p_dict in data.get("persons", []):
            try:
                persons_list = persons_from_dicts([p_dict])
                if persons_list:
                    self.sync_persons(persons_list)
            except Exception: pass

        self._con.commit()

    def close(self) -> None:
        self._con.close()
