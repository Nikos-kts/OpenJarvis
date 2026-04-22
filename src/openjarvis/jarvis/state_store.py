"""SQLite-backed runtime state store for Jarvis.

Jarvis is a singleton, so this store is deliberately trivial: one row
per key/value in ``jarvis_state``, plus append-only logs for
delegations and mood transitions.  Kept separate from
``.openJarvis/db/agents.db`` (sub-agents) so the two lifecycles never
interfere.

Schema
------
``jarvis_state``       — single-row-per-key K/V for persona hash, metrics,
                         mood, last_reload_at.
``jarvis_delegations`` — append-only log of delegations: who, when,
                         brief, status, result_summary, latency.
``jarvis_events``      — compact trace of notable moments (turn start,
                         user interrupt, mood change).  The HUD can
                         surface the tail for a "recent activity"
                         panel.
"""

from __future__ import annotations

import json
import logging
import sqlite3
import threading
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, List, Optional

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Records
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class DelegationRecord:
    id: str
    sub_agent: str
    brief: str
    mode: str              # "sync" | "async"
    status: str            # "running" | "completed" | "failed" | "aborted"
    started_at: float
    ended_at: float = 0.0
    result_summary: str = ""
    latency_ms: int = 0
    error: str = ""


@dataclass(slots=True)
class JarvisMetrics:
    total_turns: int = 0
    total_tokens_in: int = 0
    total_tokens_out: int = 0
    total_delegations: int = 0
    total_errors: int = 0
    uptime_started_at: float = field(default_factory=time.time)


# ---------------------------------------------------------------------------
# Store
# ---------------------------------------------------------------------------


class JarvisStateStore:
    """Thin SQLite wrapper.

    Thread-safe via a re-entrant lock: every write is short and
    serialised.  Reads go through the same lock to keep the sqlite3
    connection single-threaded.
    """

    def __init__(self, db_path: str | Path) -> None:
        self._path = Path(db_path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(
            str(self._path),
            isolation_level=None,  # autocommit
            check_same_thread=False,
        )
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL;")
        self._conn.execute("PRAGMA foreign_keys=ON;")
        self._init_schema()

    # ------------------------------------------------------------------
    # Schema
    # ------------------------------------------------------------------

    def _init_schema(self) -> None:
        with self._lock:
            cur = self._conn.cursor()
            cur.executescript(
                """
                CREATE TABLE IF NOT EXISTS jarvis_state (
                    key          TEXT PRIMARY KEY,
                    value        TEXT NOT NULL,
                    updated_at   REAL NOT NULL
                );

                CREATE TABLE IF NOT EXISTS jarvis_delegations (
                    id              TEXT PRIMARY KEY,
                    sub_agent       TEXT NOT NULL,
                    brief           TEXT NOT NULL,
                    mode            TEXT NOT NULL,
                    status          TEXT NOT NULL,
                    started_at      REAL NOT NULL,
                    ended_at        REAL NOT NULL DEFAULT 0,
                    result_summary  TEXT NOT NULL DEFAULT '',
                    latency_ms      INTEGER NOT NULL DEFAULT 0,
                    error           TEXT NOT NULL DEFAULT ''
                );
                CREATE INDEX IF NOT EXISTS idx_delegations_started
                    ON jarvis_delegations(started_at DESC);

                CREATE TABLE IF NOT EXISTS jarvis_events (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    kind        TEXT NOT NULL,
                    payload     TEXT NOT NULL,
                    ts          REAL NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_events_ts
                    ON jarvis_events(ts DESC);
                """
            )

    # ------------------------------------------------------------------
    # Key / value
    # ------------------------------------------------------------------

    def get(self, key: str, default: Any = None) -> Any:
        with self._lock:
            row = self._conn.execute(
                "SELECT value FROM jarvis_state WHERE key = ?",
                (key,),
            ).fetchone()
        if row is None:
            return default
        try:
            return json.loads(row["value"])
        except (ValueError, TypeError):
            return row["value"]

    def set(self, key: str, value: Any) -> None:
        with self._lock:
            self._conn.execute(
                """
                INSERT INTO jarvis_state(key, value, updated_at)
                VALUES(?, ?, ?)
                ON CONFLICT(key) DO UPDATE
                    SET value = excluded.value,
                        updated_at = excluded.updated_at
                """,
                (key, json.dumps(value), time.time()),
            )

    # ------------------------------------------------------------------
    # Metrics helpers
    # ------------------------------------------------------------------

    def get_metrics(self) -> JarvisMetrics:
        raw = self.get("metrics", {})
        if isinstance(raw, dict):
            return JarvisMetrics(**{**asdict(JarvisMetrics()), **raw})
        return JarvisMetrics()

    def update_metrics(self, **delta: int) -> JarvisMetrics:
        m = self.get_metrics()
        for k, v in delta.items():
            if hasattr(m, k):
                setattr(m, k, getattr(m, k) + v)
        self.set("metrics", asdict(m))
        return m

    # ------------------------------------------------------------------
    # Delegations
    # ------------------------------------------------------------------

    def start_delegation(
        self,
        *,
        delegation_id: str,
        sub_agent: str,
        brief: str,
        mode: str,
    ) -> DelegationRecord:
        rec = DelegationRecord(
            id=delegation_id,
            sub_agent=sub_agent,
            brief=brief,
            mode=mode,
            status="running",
            started_at=time.time(),
        )
        with self._lock:
            self._conn.execute(
                """
                INSERT INTO jarvis_delegations
                    (id, sub_agent, brief, mode, status, started_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (rec.id, rec.sub_agent, rec.brief, rec.mode, rec.status, rec.started_at),
            )
        return rec

    def finish_delegation(
        self,
        delegation_id: str,
        *,
        status: str,
        result_summary: str = "",
        error: str = "",
    ) -> None:
        now = time.time()
        with self._lock:
            self._conn.execute(
                """
                UPDATE jarvis_delegations
                   SET status = ?,
                       ended_at = ?,
                       result_summary = ?,
                       latency_ms = CAST((? - started_at) * 1000 AS INTEGER),
                       error = ?
                 WHERE id = ?
                """,
                (status, now, result_summary, now, error, delegation_id),
            )

    def recent_delegations(self, limit: int = 20) -> List[DelegationRecord]:
        with self._lock:
            rows = self._conn.execute(
                """
                SELECT id, sub_agent, brief, mode, status, started_at,
                       ended_at, result_summary, latency_ms, error
                  FROM jarvis_delegations
                 ORDER BY started_at DESC
                 LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [DelegationRecord(**dict(r)) for r in rows]

    # ------------------------------------------------------------------
    # Events (compact trace)
    # ------------------------------------------------------------------

    def log_event(self, kind: str, payload: Optional[dict] = None) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO jarvis_events(kind, payload, ts) VALUES(?, ?, ?)",
                (kind, json.dumps(payload or {}), time.time()),
            )

    def recent_events(self, limit: int = 50) -> List[dict]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT kind, payload, ts FROM jarvis_events ORDER BY ts DESC LIMIT ?",
                (limit,),
            ).fetchall()
        out: List[dict] = []
        for r in rows:
            try:
                payload = json.loads(r["payload"])
            except (ValueError, TypeError):
                payload = {}
            out.append({"kind": r["kind"], "payload": payload, "ts": r["ts"]})
        return out

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def close(self) -> None:
        with self._lock:
            self._conn.close()
