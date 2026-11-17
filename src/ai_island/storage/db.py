"""The run database (schema v1).

One database holds one run. Events are append-only: triggers abort any UPDATE, any DELETE
and any INSERT that reuses an existing event id (so INSERT OR REPLACE cannot erase
history), and this module offers no way to change or remove an event.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from pydantic import BaseModel

from ai_island.storage.events import Event

SCHEMA_VERSION = 1

SCHEMA = """
CREATE TABLE events (
    id INTEGER PRIMARY KEY,
    tick INTEGER NOT NULL CHECK (tick >= 0),
    type TEXT NOT NULL,
    payload_json TEXT NOT NULL CHECK (json_valid(payload_json))
);
CREATE TRIGGER events_no_update BEFORE UPDATE ON events
BEGIN SELECT RAISE(ABORT, 'events are append-only: UPDATE is not allowed'); END;
CREATE TRIGGER events_no_delete BEFORE DELETE ON events
BEGIN SELECT RAISE(ABORT, 'events are append-only: DELETE is not allowed'); END;
CREATE TRIGGER events_no_duplicate_id BEFORE INSERT ON events
WHEN NEW.id IS NOT NULL AND EXISTS (SELECT 1 FROM events WHERE id = NEW.id)
BEGIN SELECT RAISE(ABORT, 'events are append-only: id already exists'); END;

CREATE TABLE ai_calls (
    id INTEGER PRIMARY KEY,
    tick INTEGER NOT NULL CHECK (tick >= 0),
    player_id TEXT NULL,
    role TEXT NOT NULL,
    provider TEXT NOT NULL,
    model_version TEXT NOT NULL,
    prompt_json TEXT NOT NULL CHECK (json_valid(prompt_json)),
    reply_json TEXT NULL CHECK (reply_json IS NULL OR json_valid(reply_json)),
    thinking_tokens INTEGER NULL CHECK (thinking_tokens IS NULL OR thinking_tokens >= 0),
    input_tokens INTEGER NOT NULL CHECK (input_tokens >= 0),
    output_tokens INTEGER NOT NULL CHECK (output_tokens >= 0),
    cache_read_tokens INTEGER NOT NULL CHECK (cache_read_tokens >= 0),
    cache_write_tokens INTEGER NOT NULL CHECK (cache_write_tokens >= 0),
    cache_hit INTEGER NOT NULL CHECK (cache_hit IN (0, 1)),
    cost_usd REAL NOT NULL CHECK (cost_usd >= 0),
    duration_ms REAL NOT NULL CHECK (duration_ms >= 0),
    status TEXT NOT NULL,
    error_json TEXT NULL CHECK (error_json IS NULL OR json_valid(error_json)),
    details_json TEXT NULL CHECK (details_json IS NULL OR json_valid(details_json))
);

CREATE TABLE choice_points (
    id INTEGER PRIMARY KEY,
    tick INTEGER NOT NULL CHECK (tick >= 0),
    player_id TEXT NOT NULL,
    situation TEXT NOT NULL,
    x REAL NOT NULL,
    feeling TEXT NOT NULL,
    tier TEXT NOT NULL,
    thought TEXT NOT NULL,
    noticer_read TEXT NULL,
    advisor_said TEXT NULL,
    advisor_followed INTEGER NULL CHECK (advisor_followed IS NULL OR advisor_followed IN (0, 1)),
    action_json TEXT NOT NULL CHECK (json_valid(action_json)),
    self_label_json TEXT NOT NULL CHECK (json_valid(self_label_json)),
    outcome_json TEXT NULL CHECK (outcome_json IS NULL OR json_valid(outcome_json)),
    insight TEXT NULL,
    ai_call_id INTEGER NULL REFERENCES ai_calls(id),
    details_json TEXT NULL CHECK (details_json IS NULL OR json_valid(details_json))
);

CREATE TABLE judge_labels (
    id INTEGER PRIMARY KEY,
    tick INTEGER NOT NULL CHECK (tick >= 0),
    choice_point_id INTEGER NOT NULL REFERENCES choice_points(id),
    ai_call_id INTEGER NULL REFERENCES ai_calls(id),
    detail_level TEXT NOT NULL,
    label_json TEXT NOT NULL CHECK (json_valid(label_json)),
    details_json TEXT NULL CHECK (details_json IS NULL OR json_valid(details_json))
);

CREATE TABLE chats (
    id INTEGER PRIMARY KEY,
    tick INTEGER NOT NULL CHECK (tick >= 0),
    speaker_id TEXT NOT NULL,
    target_ids_json TEXT NOT NULL CHECK (json_valid(target_ids_json)),
    hearer_ids_json TEXT NOT NULL CHECK (json_valid(hearer_ids_json)),
    text TEXT NOT NULL,
    details_json TEXT NULL CHECK (details_json IS NULL OR json_valid(details_json))
);

CREATE TABLE value_history (
    id INTEGER PRIMARY KEY,
    tick INTEGER NOT NULL CHECK (tick >= 0),
    player_id TEXT NOT NULL,
    game_week INTEGER NOT NULL,
    value_id TEXT NOT NULL,
    old_weight REAL NULL,
    new_weight REAL NOT NULL,
    cause_event_ids_json TEXT NOT NULL CHECK (json_valid(cause_event_ids_json)),
    reflection_ai_call_id INTEGER NULL REFERENCES ai_calls(id),
    details_json TEXT NULL CHECK (details_json IS NULL OR json_valid(details_json))
);

CREATE TABLE spend (
    id INTEGER PRIMARY KEY,
    tick INTEGER NOT NULL CHECK (tick >= 0),
    ai_call_id INTEGER NULL REFERENCES ai_calls(id),
    role TEXT NOT NULL,
    cost_usd REAL NOT NULL CHECK (cost_usd >= 0),
    cumulative_usd REAL NOT NULL CHECK (cumulative_usd >= 0),
    details_json TEXT NULL CHECK (details_json IS NULL OR json_valid(details_json))
);

CREATE TABLE snapshots (
    id INTEGER PRIMARY KEY,
    tick INTEGER NOT NULL CHECK (tick >= 0),
    last_event_id INTEGER NULL REFERENCES events(id),
    schema_version INTEGER NOT NULL,
    config_json TEXT NOT NULL CHECK (json_valid(config_json)),
    config_hash TEXT NOT NULL,
    state_json TEXT NOT NULL CHECK (json_valid(state_json)),
    rng_json TEXT NOT NULL CHECK (json_valid(rng_json)),
    spend_usd REAL NOT NULL CHECK (spend_usd >= 0)
);
"""

TABLES = (
    "events",
    "ai_calls",
    "choice_points",
    "judge_labels",
    "chats",
    "value_history",
    "spend",
    "snapshots",
)


def _chat_rows(events: list[Event]) -> list[tuple]:
    """The chats-table rows for the chat_spoken events (written in the same transaction)."""
    rows = []
    for e in events:
        if e.type == "chat_spoken":
            pl = e.payload
            rows.append(
                (
                    e.tick,
                    pl.speaker,
                    json.dumps(pl.targets),
                    json.dumps(pl.hearers),
                    pl.text,
                    json.dumps({"kind": pl.kind}),
                )
            )
    return rows


class DatabaseError(Exception):
    """The run database is missing, the wrong version, or otherwise unusable."""


class Snapshot(BaseModel):
    """A complete saved state of a run at a whole tick."""

    id: int | None = None
    tick: int
    last_event_id: int | None
    schema_version: int
    config_json: str
    config_hash: str
    state_json: str
    rng_json: str
    spend_usd: float = 0.0


@dataclass(frozen=True)
class ChatRow:
    """One row of the chats table (as stored, never recomputed)."""

    id: int
    tick: int
    speaker: str
    targets: tuple
    hearers: tuple
    text: str
    kind: str


@dataclass(frozen=True)
class ChoiceRow:
    """One choice point with the newest judge label (None while there is none)."""

    id: int
    tick: int
    player_id: str
    situation: str
    x: float
    feeling: str
    tier: str
    thought: str
    action_json: str
    self_label_json: str
    judge_label_json: str | None
    judge_detail: str | None = None  # "full" | "short" of the newest label (None: no label yet)


@dataclass(frozen=True)
class JudgeLabelRow:
    """The newest judge label of one choice point (``label`` is a plain dict)."""

    choice_point_id: int
    tick: int
    detail_level: str
    label: dict
    details: dict


@dataclass(frozen=True)
class JudgeSummaryRow:
    """One ok, schema-valid daily summary or weekly profile written by the judge."""

    tick: int
    kind: str  # "daily_summary" | "weekly_profile"
    period: int  # game day (daily) or game week (weekly)
    player_id: str | None
    text: str
    flags: list
    ai_call_id: int


@dataclass
class AiCallRow:
    """One ai_calls row (one physical attempt). ``prompt`` and ``details`` are plain dicts."""

    tick: int
    player_id: str | None
    role: str
    provider: str
    model_version: str
    prompt: dict
    reply_text: str | None
    thinking_tokens: int | None
    input_tokens: int
    output_tokens: int
    cache_read_tokens: int
    cache_write_tokens: int
    cost_usd: float
    duration_ms: float
    status: str
    details: dict
    error: dict | None = None
    id: int | None = None

    @property
    def cache_hit(self) -> bool:
        return self.cache_read_tokens > 0


@dataclass
class ChoiceDetail:
    """One choice point with every column and its details parsed."""

    id: int
    tick: int
    player_id: str
    situation: str
    x: float
    feeling: str
    tier: str
    thought: str
    noticer_read: str | None
    advisor_said: str | None
    advisor_followed: bool | None
    action: dict
    self_label: dict
    outcome: dict | None
    insight: str | None
    ai_call_id: int | None
    details: dict

    @property
    def decision_key(self) -> str:
        return str(self.details.get("decision_key", ""))


_AI_COLS = (
    "id, tick, player_id, role, provider, model_version, prompt_json, reply_json, "
    "thinking_tokens, input_tokens, output_tokens, cache_read_tokens, cache_write_tokens, "
    "cost_usd, duration_ms, status, error_json, details_json"
)


def _ai_call_row(r: tuple) -> AiCallRow:
    return AiCallRow(
        id=r[0],
        tick=r[1],
        player_id=r[2],
        role=r[3],
        provider=r[4],
        model_version=r[5],
        prompt=json.loads(r[6]),
        reply_text=None if r[7] is None else json.loads(r[7]),
        thinking_tokens=r[8],
        input_tokens=r[9],
        output_tokens=r[10],
        cache_read_tokens=r[11],
        cache_write_tokens=r[12],
        cost_usd=float(r[13]),
        duration_ms=float(r[14]),
        status=r[15],
        error=None if r[16] is None else json.loads(r[16]),
        details=json.loads(r[17]) if r[17] else {},
    )


_CHOICE_COLS = (
    "id, tick, player_id, situation, x, feeling, tier, thought, noticer_read, advisor_said, "
    "advisor_followed, action_json, self_label_json, outcome_json, insight, ai_call_id, "
    "details_json"
)


def _choice_detail(r: tuple) -> ChoiceDetail:
    return ChoiceDetail(
        id=r[0],
        tick=r[1],
        player_id=r[2],
        situation=r[3],
        x=float(r[4]),
        feeling=r[5],
        tier=r[6],
        thought=r[7],
        noticer_read=r[8],
        advisor_said=r[9],
        advisor_followed=None if r[10] is None else bool(r[10]),
        action=json.loads(r[11]),
        self_label=json.loads(r[12]),
        outcome=None if r[13] is None else json.loads(r[13]),
        insight=r[14],
        ai_call_id=r[15],
        details=json.loads(r[16]) if r[16] else {},
    )


def _chat_row(row: tuple) -> ChatRow:
    try:
        kind = str(json.loads(row[6] or "{}").get("kind", ""))
    except (ValueError, AttributeError):
        kind = ""
    return ChatRow(
        row[0], row[1], row[2], tuple(json.loads(row[3])), tuple(json.loads(row[4])), row[5], kind
    )


class RunDB:
    """One run's SQLite database."""

    def __init__(self, conn: sqlite3.Connection, path: Path | None) -> None:
        self._conn = conn
        self.path = path

    @classmethod
    def _connect(cls, target: str) -> sqlite3.Connection:
        conn = sqlite3.connect(target)
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    @classmethod
    def _init_schema(cls, conn: sqlite3.Connection) -> None:
        conn.executescript(SCHEMA)
        conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
        conn.commit()

    @classmethod
    def create(cls, path: Path) -> RunDB:
        """Create a new database file; refuses to touch an existing one."""
        path = Path(path)
        if path.exists():
            raise DatabaseError(f"{path} already exists")
        path.parent.mkdir(parents=True, exist_ok=True)
        conn = cls._connect(str(path))
        cls._init_schema(conn)
        return cls(conn, path)

    @classmethod
    def open(cls, path: Path) -> RunDB:
        """Open an existing database and check its schema version."""
        path = Path(path)
        if not path.is_file():
            raise DatabaseError(f"{path} does not exist")
        conn = cls._connect(str(path))
        version = conn.execute("PRAGMA user_version").fetchone()[0]
        if version != SCHEMA_VERSION:
            conn.close()
            raise DatabaseError(
                f"{path} has schema version {version}; this program reads version {SCHEMA_VERSION}"
            )
        return cls(conn, path)

    @classmethod
    def open_readonly(cls, path: Path) -> RunDB:
        """Open an existing database for reading only (SQLite uri mode=ro)."""
        path = Path(path).resolve()
        if not path.is_file():
            raise DatabaseError(f"{path} does not exist")
        conn = sqlite3.connect(f"{path.as_uri()}?mode=ro", uri=True)
        version = conn.execute("PRAGMA user_version").fetchone()[0]
        if version != SCHEMA_VERSION:
            conn.close()
            raise DatabaseError(
                f"{path} has schema version {version}; this program reads version {SCHEMA_VERSION}"
            )
        return cls(conn, path)

    @classmethod
    def copy_to_memory(cls, path: Path) -> RunDB:
        """A writable in-memory copy of the database at ``path`` (the file is not changed)."""
        source = cls.open_readonly(path)
        try:
            conn = cls._connect(":memory:")
            source._conn.backup(conn)
        finally:
            source.close()
        return cls(conn, None)

    @classmethod
    def memory(cls) -> RunDB:
        """A throw-away in-memory database with the full schema."""
        conn = cls._connect(":memory:")
        cls._init_schema(conn)
        return cls(conn, None)

    def close(self) -> None:
        self._conn.close()

    def table_names(self) -> list[str]:
        rows = self._conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%' "
            "ORDER BY name"
        ).fetchall()
        return [r[0] for r in rows]

    # ----------------------------------------------------------------- events (append only)

    def append_events(self, events: list[Event]) -> None:
        """Append events in one transaction. Event ids are assigned by the database."""
        if not events:
            return
        rows = [(e.tick, e.type, e.payload_json()) for e in events]
        with self._conn:
            self._conn.executemany(
                "INSERT INTO events (tick, type, payload_json) VALUES (?, ?, ?)", rows
            )
            self._insert_chats(events)

    def _insert_chats(self, events: list[Event]) -> None:
        rows = _chat_rows(events)
        if rows:
            self._conn.executemany(
                "INSERT INTO chats (tick, speaker_id, target_ids_json, hearer_ids_json, text, "
                "details_json) VALUES (?, ?, ?, ?, ?, ?)",
                rows,
            )

    def events(self) -> list[Event]:
        """Every event, ordered by id."""
        rows = self._conn.execute(
            "SELECT id, tick, type, payload_json FROM events ORDER BY id"
        ).fetchall()
        return [Event.from_row(*row) for row in rows]

    def last_event_id(self) -> int | None:
        return self._conn.execute("SELECT MAX(id) FROM events").fetchone()[0]

    def last_event_tick(self) -> int | None:
        return self._conn.execute("SELECT MAX(tick) FROM events").fetchone()[0]

    def events_after(
        self, after_id: int, types: tuple[str, ...] | None = None
    ) -> list[tuple[int, Event]]:
        """Events with id > ``after_id`` (oldest first), optionally only of ``types``."""
        sql = "SELECT id, tick, type, payload_json FROM events WHERE id > ?"
        args: list = [after_id]
        if types is not None:
            sql += f" AND type IN ({','.join('?' * len(types))})"
            args.extend(types)
        rows = self._conn.execute(sql + " ORDER BY id", args).fetchall()
        return [(r[0], Event.from_row(*r)) for r in rows]

    # ----------------------------------------------------------------------- read accessors

    _CHAT_COLS = "id, tick, speaker_id, target_ids_json, hearer_ids_json, text, details_json"

    def chats_page(self, before_id: int | None, limit: int) -> list[ChatRow]:
        """The newest ``limit`` chats with id < ``before_id`` (or overall), oldest first."""
        if before_id is None:
            rows = self._conn.execute(
                f"SELECT {self._CHAT_COLS} FROM chats ORDER BY id DESC LIMIT ?", (limit,)
            ).fetchall()
        else:
            rows = self._conn.execute(
                f"SELECT {self._CHAT_COLS} FROM chats WHERE id < ? ORDER BY id DESC LIMIT ?",
                (before_id, limit),
            ).fetchall()
        return [_chat_row(r) for r in reversed(rows)]

    def chats_after(self, after_id: int) -> list[ChatRow]:
        rows = self._conn.execute(
            f"SELECT {self._CHAT_COLS} FROM chats WHERE id > ? ORDER BY id", (after_id,)
        ).fetchall()
        return [_chat_row(r) for r in rows]

    def choice_points_all(self) -> list[ChoiceRow]:
        """Every choice point (by id) with the newest judge label for it."""
        rows = self._conn.execute(
            "SELECT c.id, c.tick, c.player_id, c.situation, c.x, c.feeling, c.tier, c.thought, "
            "c.action_json, c.self_label_json, "
            "(SELECT j.label_json FROM judge_labels j WHERE j.choice_point_id = c.id "
            " ORDER BY j.id DESC LIMIT 1), "
            "(SELECT j.detail_level FROM judge_labels j WHERE j.choice_point_id = c.id "
            " ORDER BY j.id DESC LIMIT 1) FROM choice_points c ORDER BY c.id"
        ).fetchall()
        return [ChoiceRow(*r) for r in rows]

    def labels_version(self) -> tuple[int, int]:
        """(MAX(choice_points.id), MAX(judge_labels.id)); changes when a label is added."""
        a = self._conn.execute("SELECT MAX(id) FROM choice_points").fetchone()[0]
        b = self._conn.execute("SELECT MAX(id) FROM judge_labels").fetchone()[0]
        return (a or 0, b or 0)

    def spend_total(self) -> float:
        """SUM(spend.cost_usd), 0.0 when empty."""
        return float(self._conn.execute("SELECT SUM(cost_usd) FROM spend").fetchone()[0] or 0.0)

    def spend_by_week(self, week_ticks: int) -> list[tuple[int, float]]:
        """Spend per game week (game_week formula), oldest week first."""
        rows = self._conn.execute(
            "SELECT (MAX(0, tick - 1) / ?) + 1 AS week, SUM(cost_usd) FROM spend "
            "GROUP BY week ORDER BY week",
            (week_ticks,),
        ).fetchall()
        return [(int(w), float(c)) for w, c in rows]

    def latest_values(self, player_id: str) -> tuple[tuple[str, float], ...] | None:
        """The latest new_weight per value_id for a player (None when there are no rows)."""
        rows = self._conn.execute(
            "SELECT value_id, new_weight FROM value_history WHERE id IN ("
            "SELECT MAX(id) FROM value_history WHERE player_id = ? GROUP BY value_id) "
            "ORDER BY value_id",
            (player_id,),
        ).fetchall()
        if not rows:
            return None
        return tuple((r[0], float(r[1])) for r in rows)

    # ------------------------------------------------------------------ AI records (Phase 4)

    def insert_ai_call(self, row: AiCallRow) -> int:
        """Store one physical attempt. Returns the new row id."""
        with self._conn:
            return self._insert_ai_call(row)

    def record_attempt(self, row: AiCallRow, cost_usd: float) -> int:
        """Store an attempt with a reply and its spend row in ONE transaction; returns the id.

        Either both rows exist afterwards or neither does, so a crash can never leave a paid call
        uncounted.
        """
        with self._conn:
            call_id = self._insert_ai_call(row)
            self._insert_spend(row.tick, call_id, row.role, cost_usd)
        return call_id

    def reconcile_spend(self) -> int:
        """Add a spend row for every ai_calls row that cost money but has none; returns how many.

        Idempotent (matched by ai_call_id). Repairs runs written before ``record_attempt`` existed
        or stopped between the two writes. Call it before the spend ledger is built.
        """
        with self._conn:
            rows = self._conn.execute(
                "SELECT a.id, a.tick, a.role, a.cost_usd FROM ai_calls a WHERE a.cost_usd > 0 "
                "AND NOT EXISTS (SELECT 1 FROM spend s WHERE s.ai_call_id = a.id) ORDER BY a.id"
            ).fetchall()
            for call_id, tick, role, cost in rows:
                self._insert_spend(int(tick), int(call_id), str(role), float(cost))
        return len(rows)

    def _insert_ai_call(self, row: AiCallRow) -> int:
        cur = self._conn.execute(
            "INSERT INTO ai_calls (tick, player_id, role, provider, model_version, "
            "prompt_json, reply_json, thinking_tokens, input_tokens, output_tokens, "
            "cache_read_tokens, cache_write_tokens, cache_hit, cost_usd, duration_ms, "
            "status, error_json, details_json) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                row.tick,
                row.player_id,
                row.role,
                row.provider,
                row.model_version,
                json.dumps(row.prompt, sort_keys=True),
                None if row.reply_text is None else json.dumps(row.reply_text),
                row.thinking_tokens,
                row.input_tokens,
                row.output_tokens,
                row.cache_read_tokens,
                row.cache_write_tokens,
                1 if row.cache_hit else 0,
                row.cost_usd,
                row.duration_ms,
                row.status,
                None if row.error is None else json.dumps(row.error, sort_keys=True),
                json.dumps(row.details, sort_keys=True),
            ),
        )
        return int(cur.lastrowid or 0)

    def find_ai_call(self, attempt_key: str) -> AiCallRow | None:
        """The newest stored attempt whose details carry this ``key/attempt`` identity."""
        key, _, attempt = attempt_key.rpartition("/")
        if not key or not attempt.isdigit():
            return None
        row = self._conn.execute(
            f"SELECT {_AI_COLS} FROM ai_calls WHERE json_extract(details_json, '$.key') = ? "
            "AND json_extract(details_json, '$.attempt') = ? ORDER BY id DESC LIMIT 1",
            (key, int(attempt)),
        ).fetchone()
        return None if row is None else _ai_call_row(row)

    def insert_spend(self, tick: int, ai_call_id: int | None, role: str, cost: float) -> None:
        """Store one spend row; the cumulative total is computed here."""
        with self._conn:
            self._insert_spend(tick, ai_call_id, role, cost)

    def _insert_spend(self, tick: int, ai_call_id: int | None, role: str, cost: float) -> None:
        total = self._conn.execute("SELECT SUM(cost_usd) FROM spend").fetchone()[0] or 0.0
        self._conn.execute(
            "INSERT INTO spend (tick, ai_call_id, role, cost_usd, cumulative_usd) "
            "VALUES (?, ?, ?, ?, ?)",
            (tick, ai_call_id, role, cost, float(total) + cost),
        )

    def insert_choice_point(self, rec) -> int | None:
        """Store a choice point; None (nothing stored) when its decision_key already exists."""
        if self._choice_id(rec.decision_key) is not None:
            return None
        details = dict(rec.details)
        details["decision_key"] = rec.decision_key
        with self._conn:
            cur = self._conn.execute(
                "INSERT INTO choice_points (tick, player_id, situation, x, feeling, tier, "
                "thought, noticer_read, advisor_said, advisor_followed, action_json, "
                "self_label_json, outcome_json, insight, ai_call_id, details_json) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    rec.tick,
                    rec.player_id,
                    rec.situation,
                    rec.x,
                    rec.feeling,
                    rec.tier,
                    rec.thought,
                    rec.noticer_read,
                    rec.advisor_said,
                    None if rec.advisor_followed is None else int(rec.advisor_followed),
                    json.dumps(rec.action, sort_keys=True),
                    json.dumps(rec.self_label, sort_keys=True),
                    None if rec.outcome is None else json.dumps(rec.outcome, sort_keys=True),
                    rec.insight,
                    rec.ai_call_id,
                    json.dumps(details, sort_keys=True),
                ),
            )
        return int(cur.lastrowid or 0)

    def _choice_id(self, decision_key: str) -> int | None:
        row = self._conn.execute(
            "SELECT id FROM choice_points WHERE json_extract(details_json, '$.decision_key') = ?",
            (decision_key,),
        ).fetchone()
        return None if row is None else int(row[0])

    def update_choice_outcome(self, decision_key: str, outcome: dict) -> None:
        with self._conn:
            self._conn.execute(
                "UPDATE choice_points SET outcome_json = ? "
                "WHERE json_extract(details_json, '$.decision_key') = ?",
                (json.dumps(outcome, sort_keys=True), decision_key),
            )

    def update_choice_insight(self, decision_key: str, insight: str) -> None:
        with self._conn:
            self._conn.execute(
                "UPDATE choice_points SET insight = ? "
                "WHERE json_extract(details_json, '$.decision_key') = ?",
                (insight, decision_key),
            )

    def insert_value_history(self, rows) -> int:
        """Store value history rows; a row whose reflection_key+value_id+player exists is skipped.

        Returns the number of rows stored.
        """
        stored = 0
        with self._conn:
            for r in rows:
                if r.reflection_key is not None:
                    seen = self._conn.execute(
                        "SELECT 1 FROM value_history WHERE player_id = ? AND value_id = ? "
                        "AND json_extract(details_json, '$.reflection_key') = ?",
                        (r.player_id, r.value_id, r.reflection_key),
                    ).fetchone()
                    if seen:
                        continue
                self._conn.execute(
                    "INSERT INTO value_history (tick, player_id, game_week, value_id, "
                    "old_weight, new_weight, cause_event_ids_json, reflection_ai_call_id, "
                    "details_json) VALUES (?, ?, ?, ?, ?, ?, ?, NULL, ?)",
                    (
                        r.tick,
                        r.player_id,
                        r.game_week,
                        r.value_id,
                        r.old_weight,
                        r.new_weight,
                        json.dumps(list(r.cause_event_ids)),
                        json.dumps(
                            {
                                "reflection_key": r.reflection_key,
                                "cause_kind": "memory_item",
                                "cause_items": list(r.cause_items),
                            },
                            sort_keys=True,
                        ),
                    ),
                )
                stored += 1
        return stored

    def choice_details(self, player_id: str | None = None) -> list[ChoiceDetail]:
        """Every choice point (oldest first), optionally of one player, with parsed columns."""
        sql = f"SELECT {_CHOICE_COLS} FROM choice_points"
        args: tuple = ()
        if player_id is not None:
            sql += " WHERE player_id = ?"
            args = (player_id,)
        rows = self._conn.execute(sql + " ORDER BY id", args).fetchall()
        return [_choice_detail(r) for r in rows]

    def decision_events(self, player_id: str | None = None) -> list[Event]:
        """The decision_made events (oldest first), optionally of one player."""
        rows = self._conn.execute(
            "SELECT id, tick, type, payload_json FROM events WHERE type = 'decision_made' "
            "ORDER BY id"
        ).fetchall()
        events = [Event.from_row(*r) for r in rows]
        if player_id is not None:
            events = [e for e in events if e.payload.player == player_id]
        return events

    def choice_details_after(self, after_id: int) -> list[ChoiceDetail]:
        """Choice points with id > ``after_id`` (oldest first), with parsed columns."""
        rows = self._conn.execute(
            f"SELECT {_CHOICE_COLS} FROM choice_points WHERE id > ? ORDER BY id", (after_id,)
        ).fetchall()
        return [_choice_detail(r) for r in rows]

    def choice_players(self) -> dict[int, str]:
        """choice point id -> player id (all choice points)."""
        rows = self._conn.execute("SELECT id, player_id FROM choice_points").fetchall()
        return {int(r[0]): str(r[1]) for r in rows}

    def choice_detail_by_key(self, decision_key: str) -> ChoiceDetail | None:
        row = self._conn.execute(
            f"SELECT {_CHOICE_COLS} FROM choice_points "
            "WHERE json_extract(details_json, '$.decision_key') = ?",
            (decision_key,),
        ).fetchone()
        return None if row is None else _choice_detail(row)

    def events_between(
        self, after_tick: int, until_tick: int, types: tuple[str, ...] | None = None
    ) -> list[tuple[int, Event]]:
        """Events with ``after_tick < tick <= until_tick`` (oldest first), optionally by type."""
        sql = "SELECT id, tick, type, payload_json FROM events WHERE tick > ? AND tick <= ?"
        args: list = [after_tick, until_tick]
        if types is not None:
            sql += f" AND type IN ({','.join('?' * len(types))})"
            args.extend(types)
        rows = self._conn.execute(sql + " ORDER BY id", args).fetchall()
        return [(r[0], Event.from_row(*r)) for r in rows]

    # -------------------------------------------------------------------- judge (Phase 5)

    def insert_judge_label(
        self,
        choice_point_id: int,
        tick: int,
        ai_call_id: int | None,
        detail_level: str,
        label: dict,
        details: dict,
    ) -> int | None:
        """Store a judge label; None (nothing stored) when ``details["key"]`` already exists."""
        key = details.get("key")
        if (
            key is not None
            and self._conn.execute(
                "SELECT 1 FROM judge_labels WHERE json_extract(details_json, '$.key') = ?", (key,)
            ).fetchone()
        ):
            return None
        with self._conn:
            cur = self._conn.execute(
                "INSERT INTO judge_labels (tick, choice_point_id, ai_call_id, detail_level, "
                "label_json, details_json) VALUES (?, ?, ?, ?, ?, ?)",
                (
                    tick,
                    choice_point_id,
                    ai_call_id,
                    detail_level,
                    json.dumps(label, sort_keys=True),
                    json.dumps(details, sort_keys=True),
                ),
            )
        return int(cur.lastrowid or 0)

    def judge_label_keys(self) -> set[str]:
        """Every ``details.key`` of a stored judge label (ok or failed)."""
        rows = self._conn.execute(
            "SELECT json_extract(details_json, '$.key') FROM judge_labels "
            "WHERE json_extract(details_json, '$.key') IS NOT NULL"
        ).fetchall()
        return {str(r[0]) for r in rows}

    def judge_labels_latest(self) -> list[JudgeLabelRow]:
        """The newest judge label of every labelled choice point (by choice point id)."""
        rows = self._conn.execute(
            "SELECT choice_point_id, tick, detail_level, label_json, details_json "
            "FROM judge_labels WHERE id IN (SELECT MAX(id) FROM judge_labels "
            "GROUP BY choice_point_id) ORDER BY choice_point_id"
        ).fetchall()
        return [
            JudgeLabelRow(int(r[0]), int(r[1]), r[2], json.loads(r[3]), json.loads(r[4] or "{}"))
            for r in rows
        ]

    def judge_summaries(
        self, kind: str | None = None, player_id: str | None = None
    ) -> list[JudgeSummaryRow]:
        """Daily summaries and weekly profiles: ok, schema-valid replies, one per key.

        The newest valid reply of a key wins. Ordered by tick, kind, period, player.
        """
        from ai_island.measure.judge_schemas import DailySummaryReply, ProfileReply

        rows = self._conn.execute(
            "SELECT id, tick, reply_json, details_json FROM ai_calls WHERE role = 'judge' "
            "AND status = 'ok' AND json_extract(details_json, '$.judge_kind') IS NOT NULL "
            "ORDER BY id"
        ).fetchall()
        found: dict[str, JudgeSummaryRow] = {}
        for call_id, tick, reply, details_json in rows:
            details = json.loads(details_json or "{}")
            kind_found = details.get("judge_kind")
            try:
                if kind_found == "daily_summary":
                    parsed: DailySummaryReply | ProfileReply = DailySummaryReply.model_validate(
                        json.loads(json.loads(reply))
                    )
                    text = parsed.summary  # type: ignore[union-attr]
                    flags = [f.model_dump(mode="json") for f in parsed.flags]  # type: ignore[union-attr]
                elif kind_found == "weekly_profile":
                    parsed = ProfileReply.model_validate(json.loads(json.loads(reply)))
                    text = parsed.profile
                    flags = []
                else:
                    continue
            except (ValueError, TypeError):
                continue
            key = str(details.get("key") or f"{kind_found}/{details.get('period')}/{call_id}")
            found[key] = JudgeSummaryRow(
                int(tick),
                kind_found,
                int(details.get("period", 0)),
                details.get("subject_id"),
                text,
                flags,
                int(call_id),
            )
        out = [
            r
            for r in found.values()
            if (kind is None or r.kind == kind) and (player_id is None or r.player_id == player_id)
        ]
        return sorted(out, key=lambda r: (r.tick, r.kind, r.period, r.player_id or ""))

    def judge_summary_keys(self) -> set[str]:
        """Keys of the ok daily summaries and weekly profiles already stored."""
        rows = self._conn.execute(
            "SELECT json_extract(details_json, '$.key') FROM ai_calls WHERE role = 'judge' "
            "AND status = 'ok' AND json_extract(details_json, '$.judge_kind') IS NOT NULL"
        ).fetchall()
        return {str(r[0]) for r in rows if r[0] is not None}

    def summaries_version(self) -> int:
        """MAX(id) of the judge's summary/profile calls; changes when one is added."""
        return int(
            self._conn.execute(
                "SELECT MAX(id) FROM ai_calls WHERE role = 'judge' "
                "AND json_extract(details_json, '$.judge_kind') IS NOT NULL"
            ).fetchone()[0]
            or 0
        )

    def values_version(self) -> int:
        """MAX(value_history.id), 0 when empty; changes whenever a value row is added."""
        return int(self._conn.execute("SELECT MAX(id) FROM value_history").fetchone()[0] or 0)

    def ai_call_count(self) -> int:
        return int(self._conn.execute("SELECT COUNT(*) FROM ai_calls").fetchone()[0])

    def count(self, table: str) -> int:
        if table not in TABLES:
            raise DatabaseError(f"unknown table '{table}'")
        return int(self._conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])

    # ------------------------------------------------------------------------- snapshots

    def save_snapshot(self, snapshot: Snapshot) -> int:
        """Store a snapshot. Never adds an event. Returns the snapshot id."""
        with self._conn:
            cur = self._conn.execute(
                "INSERT INTO snapshots (tick, last_event_id, schema_version, config_json, "
                "config_hash, state_json, rng_json, spend_usd) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    snapshot.tick,
                    snapshot.last_event_id,
                    snapshot.schema_version,
                    snapshot.config_json,
                    snapshot.config_hash,
                    snapshot.state_json,
                    snapshot.rng_json,
                    snapshot.spend_usd,
                ),
            )
        return int(cur.lastrowid or 0)

    def save_checkpoint(self, events: list[Event], snapshot: Snapshot) -> None:
        """Append pending events and store a snapshot in one transaction.

        The snapshot's ``last_event_id`` is filled in from the database after the append.
        """
        with self._conn:
            if events:
                self._conn.executemany(
                    "INSERT INTO events (tick, type, payload_json) VALUES (?, ?, ?)",
                    [(e.tick, e.type, e.payload_json()) for e in events],
                )
                self._insert_chats(events)
            last = self._conn.execute("SELECT MAX(id) FROM events").fetchone()[0]
            self._conn.execute(
                "INSERT INTO snapshots (tick, last_event_id, schema_version, config_json, "
                "config_hash, state_json, rng_json, spend_usd) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    snapshot.tick,
                    last,
                    snapshot.schema_version,
                    snapshot.config_json,
                    snapshot.config_hash,
                    snapshot.state_json,
                    snapshot.rng_json,
                    snapshot.spend_usd,
                ),
            )

    def snapshot_states_after(self, after_id: int) -> list[tuple[int, int, str, str]]:
        """(id, tick, state_json, config_json) of snapshots with id > ``after_id``, by id."""
        rows = self._conn.execute(
            "SELECT id, tick, state_json, config_json FROM snapshots WHERE id > ? ORDER BY id",
            (after_id,),
        ).fetchall()
        return [(int(r[0]), int(r[1]), r[2], r[3]) for r in rows]

    def latest_snapshot(self) -> Snapshot | None:
        row = self._conn.execute(
            "SELECT id, tick, last_event_id, schema_version, config_json, config_hash, "
            "state_json, rng_json, spend_usd FROM snapshots ORDER BY id DESC LIMIT 1"
        ).fetchone()
        if row is None:
            return None
        return Snapshot(
            id=row[0],
            tick=row[1],
            last_event_id=row[2],
            schema_version=row[3],
            config_json=row[4],
            config_hash=row[5],
            state_json=row[6],
            rng_json=row[7],
            spend_usd=row[8],
        )
