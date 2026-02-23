"""SQLite-backed job store — survives restarts."""

from __future__ import annotations

import sqlite3
import threading
from pathlib import Path
from typing import Optional

from bot.pipeline.models import PipelineResult, PipelineStage


class SqliteJobStore:
    """Thread-safe SQLite store for PipelineResult objects.

    Stores the full PipelineResult as JSON with denormalized columns
    for fast queries (stage, created_at, prompt).
    """

    def __init__(self, db_path: Path) -> None:
        self._db_path = db_path
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._local = threading.local()
        self._init_schema(self._conn)

    @property
    def _conn(self) -> sqlite3.Connection:
        """One connection per thread (SQLite requirement)."""
        conn = getattr(self._local, "conn", None)
        if conn is None:
            conn = sqlite3.connect(str(self._db_path), check_same_thread=False)
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=NORMAL")
            conn.row_factory = sqlite3.Row
            self._local.conn = conn
        return conn

    @staticmethod
    def _init_schema(conn: sqlite3.Connection) -> None:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS jobs (
                job_id      TEXT PRIMARY KEY,
                data        TEXT NOT NULL,
                stage       TEXT NOT NULL,
                created_at  TEXT NOT NULL,
                completed_at TEXT,
                prompt      TEXT NOT NULL DEFAULT ''
            )
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_jobs_created
            ON jobs (created_at DESC)
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_jobs_stage
            ON jobs (stage)
        """)
        conn.commit()

    @staticmethod
    def _serialize(result: PipelineResult) -> str:
        return result.model_dump_json()

    @staticmethod
    def _deserialize(data: str) -> PipelineResult:
        return PipelineResult.model_validate_json(data)

    # ── CRUD ──────────────────────────────────────────────

    def create(self, result: PipelineResult) -> None:
        self._conn.execute(
            """INSERT OR REPLACE INTO jobs
               (job_id, data, stage, created_at, completed_at, prompt)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (
                result.job_id,
                self._serialize(result),
                result.stage.value,
                result.request.created_at.isoformat(),
                result.completed_at.isoformat() if result.completed_at else None,
                result.request.user_prompt,
            ),
        )
        self._conn.commit()

    def get(self, job_id: str) -> Optional[PipelineResult]:
        row = self._conn.execute(
            "SELECT data FROM jobs WHERE job_id = ?", (job_id,)
        ).fetchone()
        if row is None:
            return None
        return self._deserialize(row["data"])

    def update_result(self, result: PipelineResult) -> None:
        """Persist the full current state of a PipelineResult."""
        self._conn.execute(
            """UPDATE jobs SET
                data = ?, stage = ?, completed_at = ?, prompt = ?
               WHERE job_id = ?""",
            (
                self._serialize(result),
                result.stage.value,
                result.completed_at.isoformat() if result.completed_at else None,
                result.request.user_prompt,
                result.job_id,
            ),
        )
        self._conn.commit()

    def list_all(self) -> list[PipelineResult]:
        rows = self._conn.execute(
            "SELECT data FROM jobs ORDER BY created_at DESC"
        ).fetchall()
        return [self._deserialize(r["data"]) for r in rows]

    def list_active(self) -> list[PipelineResult]:
        rows = self._conn.execute(
            "SELECT data FROM jobs WHERE stage NOT IN (?, ?)",
            (PipelineStage.COMPLETE.value, PipelineStage.FAILED.value),
        ).fetchall()
        return [self._deserialize(r["data"]) for r in rows]

    def search(self, query: str) -> list[PipelineResult]:
        """Full-text search on prompt column."""
        rows = self._conn.execute(
            "SELECT data FROM jobs WHERE prompt LIKE ? ORDER BY created_at DESC",
            (f"%{query}%",),
        ).fetchall()
        return [self._deserialize(r["data"]) for r in rows]
