"""SQLite/FTS5 memory backend — zero-dependency default."""

from __future__ import annotations

import json
import sqlite3
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

from openjarvis.core.events import EventType, get_event_bus
from openjarvis.core.registry import MemoryRegistry
from openjarvis.tools.storage._stubs import MemoryBackend, RetrievalResult


def _check_fts5(conn: sqlite3.Connection) -> bool:
    """Return True if the SQLite build includes FTS5."""
    try:
        opts = conn.execute("PRAGMA compile_options").fetchall()
        return any("FTS5" in o[0].upper() for o in opts)
    except sqlite3.Error:
        return False


@MemoryRegistry.register("sqlite")
class SQLiteMemory(MemoryBackend):
    """Full-text search memory backend using SQLite FTS5.

    Uses the built-in ``sqlite3`` module — no extra dependencies.
    """

    backend_id: str = "sqlite"

    def __init__(self, db_path: str | Path = "") -> None:
        if not db_path:
            from openjarvis.core.config import DEFAULT_CONFIG_DIR

            db_path = str(DEFAULT_CONFIG_DIR / "memory.db")

        self._db_path = str(db_path)
        self._rust_impl = None
        self._conn: sqlite3.Connection | None = None

        # Prefer the Rust implementation when available for performance,
        # but keep a pure-Python fallback so memory works without the
        # optional openjarvis_rust extension.
        try:
            from openjarvis._rust_bridge import get_rust_module

            _rust = get_rust_module()
            self._rust_impl = _rust.SQLiteMemory(self._db_path)
        except Exception:
            self._conn = sqlite3.connect(self._db_path)
            self._conn.row_factory = sqlite3.Row
            self._create_tables()
            self._conn.commit()

    def _create_tables(self) -> None:
        assert self._conn is not None
        self._conn.executescript("""
            CREATE TABLE IF NOT EXISTS documents (
                id       TEXT PRIMARY KEY,
                content  TEXT NOT NULL,
                source   TEXT NOT NULL DEFAULT '',
                metadata TEXT NOT NULL DEFAULT '{}',
                created_at REAL NOT NULL
            );

            CREATE VIRTUAL TABLE IF NOT EXISTS documents_fts
            USING fts5(
                doc_id UNINDEXED,
                content,
                source,
                tokenize='porter unicode61'
            );
        """)

    def store(
        self,
        content: str,
        *,
        source: str = "",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Persist *content* and return a unique document id."""
        meta_json = json.dumps(metadata or {})
        if self._rust_impl is not None:
            doc_id = self._rust_impl.store(content, source, meta_json)
        else:
            assert self._conn is not None
            doc_id = str(uuid.uuid4())
            cur = self._conn.cursor()
            cur.execute(
                "INSERT INTO documents (id, content, source, metadata, created_at) VALUES (?, ?, ?, ?, strftime('%s','now'))",
                (doc_id, content, source, meta_json),
            )
            cur.execute(
                "INSERT INTO documents_fts (doc_id, content, source) VALUES (?, ?, ?)",
                (doc_id, content, source),
            )
            self._conn.commit()

        bus = get_event_bus()
        bus.publish(
            EventType.MEMORY_STORE,
            {
                "backend": self.backend_id,
                "doc_id": doc_id,
                "source": source,
            },
        )
        return doc_id

    def retrieve(
        self,
        query: str,
        *,
        top_k: int = 5,
        **kwargs: Any,
    ) -> List[RetrievalResult]:
        """Search via FTS5 MATCH with BM25 ranking — always via Rust backend."""
        if not query.strip():
            return []

        if self._rust_impl is not None:
            from openjarvis._rust_bridge import retrieval_results_from_json

            results = retrieval_results_from_json(
                self._rust_impl.retrieve(query, top_k),
            )
        else:
            assert self._conn is not None
            rows = self._conn.execute(
                """
                SELECT
                    d.content AS content,
                    d.source AS source,
                    d.metadata AS metadata,
                    bm25(documents_fts) AS score
                FROM documents_fts
                JOIN documents d ON d.id = documents_fts.doc_id
                WHERE documents_fts MATCH ?
                ORDER BY score ASC
                LIMIT ?
                """,
                (query, top_k),
            ).fetchall()
            results = [
                RetrievalResult(
                    content=r["content"],
                    score=float(-(r["score"] if r["score"] is not None else 0.0)),
                    source=r["source"] or "",
                    metadata=json.loads(r["metadata"] or "{}"),
                )
                for r in rows
            ]

        bus = get_event_bus()
        bus.publish(
            EventType.MEMORY_RETRIEVE,
            {
                "backend": self.backend_id,
                "query": query,
                "num_results": len(results),
            },
        )
        return results

    def delete(self, doc_id: str) -> bool:
        """Delete a document by id — always via Rust backend."""
        if self._rust_impl is not None:
            return self._rust_impl.delete(doc_id)

        assert self._conn is not None
        cur = self._conn.cursor()
        cur.execute("DELETE FROM documents_fts WHERE doc_id = ?", (doc_id,))
        deleted = cur.execute(
            "DELETE FROM documents WHERE id = ?",
            (doc_id,),
        ).rowcount > 0
        self._conn.commit()
        return deleted

    def clear(self) -> None:
        """Remove all stored documents — always via Rust backend."""
        if self._rust_impl is not None:
            self._rust_impl.clear()
            return

        assert self._conn is not None
        self._conn.execute("DELETE FROM documents")
        self._conn.execute("DELETE FROM documents_fts")
        self._conn.commit()

    def count(self) -> int:
        """Return the number of stored documents — always via Rust backend."""
        if self._rust_impl is not None:
            return self._rust_impl.count()

        assert self._conn is not None
        row = self._conn.execute("SELECT COUNT(*) FROM documents").fetchone()
        return int(row[0] if row else 0)

    def close(self) -> None:
        """Close the database connection."""
        if self._conn is not None:
            self._conn.close()
            self._conn = None


__all__ = ["SQLiteMemory"]
