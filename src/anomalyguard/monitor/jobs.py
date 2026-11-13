"""Background jobs: long analyses and pipeline runs execute on a small thread pool.

Job state is kept in the metrics database so the jobs API (and the UI) can show
it after a restart; jobs that were still queued or running when the server
stopped are marked ``interrupted``.
"""

from __future__ import annotations

import json
import logging
import sqlite3
import threading
import traceback
import uuid
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from pathlib import Path
from typing import Any

from anomalyguard.monitor.store import now_iso

log = logging.getLogger("anomalyguard.jobs")

SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    id TEXT PRIMARY KEY,
    kind TEXT NOT NULL,
    label TEXT,
    status TEXT NOT NULL,
    created_at TEXT NOT NULL,
    started_at TEXT,
    finished_at TEXT,
    progress REAL DEFAULT 0,
    message TEXT,
    params_json TEXT,
    result_json TEXT,
    error TEXT
);
CREATE INDEX IF NOT EXISTS idx_jobs_created ON jobs(created_at);
"""

FINISHED = ("success", "failed", "interrupted")


class JobContext:
    """Passed to a job function so it can report progress."""

    def __init__(self, manager: JobManager, job_id: str):
        self.manager = manager
        self.job_id = job_id
        self.fraction = 0.0

    def progress(self, fraction: float, message: str | None = None) -> None:
        self.fraction = max(0.0, min(1.0, float(fraction)))
        self.manager._update(self.job_id, progress=self.fraction, message=message)


class JobManager:
    def __init__(self, db_path: str | Path, workers: int = 2):
        self.path = Path(db_path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._pool = ThreadPoolExecutor(max_workers=max(1, workers), thread_name_prefix="ag-job")
        self._lock = threading.Lock()
        with closing(self._conn()) as conn, conn:
            conn.executescript(SCHEMA)
            conn.execute(
                "UPDATE jobs SET status = 'interrupted', finished_at = ?, error = COALESCE(error,"
                " 'server stopped before the job finished') WHERE status IN ('queued', 'running')",
                (now_iso(),),
            )

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, timeout=30)
        conn.row_factory = sqlite3.Row
        return conn

    @staticmethod
    def _row(r: sqlite3.Row) -> dict[str, Any]:
        d = dict(r)
        d["params"] = json.loads(d.pop("params_json") or "{}")
        d["result"] = json.loads(d.pop("result_json") or "null")
        return d

    def _update(self, job_id: str, **fields: Any) -> None:
        fields = {k: v for k, v in fields.items() if v is not None}
        if "result" in fields:
            fields["result_json"] = json.dumps(fields.pop("result"), default=str)
        if not fields:
            return
        sets = ", ".join(f"{k} = ?" for k in fields)
        with self._lock, closing(self._conn()) as conn, conn:
            conn.execute(f"UPDATE jobs SET {sets} WHERE id = ?", (*fields.values(), job_id))

    # ------------------------------------------------------------------
    def submit(
        self,
        kind: str,
        fn: Callable[[JobContext], Any],
        label: str | None = None,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Queue ``fn(ctx)``; its return value becomes the job's ``result``."""
        job_id = uuid.uuid4().hex[:16]
        with self._lock, closing(self._conn()) as conn, conn:
            conn.execute(
                "INSERT INTO jobs (id, kind, label, status, created_at, params_json)"
                " VALUES (?, ?, ?, 'queued', ?, ?)",
                (job_id, kind, label, now_iso(), json.dumps(params or {}, default=str)),
            )
        self._pool.submit(self._run, job_id, fn)
        return self.get(job_id)  # type: ignore[return-value]

    def run_inline(
        self,
        kind: str,
        fn: Callable[[JobContext], Any],
        label: str | None = None,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Record and run a job synchronously (used by ``?wait=true`` requests)."""
        job_id = uuid.uuid4().hex[:16]
        with self._lock, closing(self._conn()) as conn, conn:
            conn.execute(
                "INSERT INTO jobs (id, kind, label, status, created_at, params_json)"
                " VALUES (?, ?, ?, 'queued', ?, ?)",
                (job_id, kind, label, now_iso(), json.dumps(params or {}, default=str)),
            )
        self._run(job_id, fn)
        return self.get(job_id)  # type: ignore[return-value]

    def _run(self, job_id: str, fn: Callable[[JobContext], Any]) -> None:
        self._update(job_id, status="running", started_at=now_iso())
        ctx = JobContext(self, job_id)
        try:
            result = fn(ctx)
        except Exception as exc:
            log.debug("job %s failed:\n%s", job_id, traceback.format_exc())
            self._update(
                job_id,
                status="failed",
                finished_at=now_iso(),
                error=f"{type(exc).__name__}: {exc}",
                message="Failed",
            )
            return
        # a job that did not report its own completion must not keep "Running..."
        message = None if ctx.fraction >= 1.0 else "Done"
        self._update(
            job_id,
            status="success",
            finished_at=now_iso(),
            progress=1.0,
            result=result,
            message=message,
        )

    def get(self, job_id: str) -> dict[str, Any] | None:
        with closing(self._conn()) as conn:
            r = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
        return self._row(r) if r else None

    def list(
        self, limit: int = 50, kind: str | None = None, status: str | None = None
    ) -> list[dict[str, Any]]:
        q, params = "SELECT * FROM jobs WHERE 1=1", []
        if kind:
            q += " AND kind = ?"
            params.append(kind)
        if status:
            q += " AND status = ?"
            params.append(status)
        q += " ORDER BY created_at DESC, rowid DESC LIMIT ?"
        params.append(int(limit))
        with closing(self._conn()) as conn:
            return [self._row(r) for r in conn.execute(q, params).fetchall()]

    def shutdown(self, wait: bool = False) -> None:
        self._pool.shutdown(wait=wait, cancel_futures=True)
