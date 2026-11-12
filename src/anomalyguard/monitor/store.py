"""SQLite store for run metrics, anomalies, alerts, feedback and tuned thresholds."""

from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

DEFAULT_DB = ".anomalyguard/anomalyguard.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    pipeline TEXT NOT NULL,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    status TEXT NOT NULL,
    error TEXT,
    rows INTEGER DEFAULT 0,
    n_anomalies INTEGER DEFAULT 0,
    anomaly_rate REAL DEFAULT 0,
    quality_score REAL,
    completeness REAL,
    validity REAL,
    uniqueness REAL,
    freshness REAL,
    cells_changed INTEGER DEFAULT 0,
    rows_dropped INTEGER DEFAULT 0,
    flagged_for_review INTEGER DEFAULT 0,
    alerts_sent INTEGER DEFAULT 0,
    duration_ms REAL,
    detectors_json TEXT,
    metrics_json TEXT
);
CREATE INDEX IF NOT EXISTS idx_runs_pipeline ON runs(pipeline, id);
CREATE TABLE IF NOT EXISTS anomalies (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id INTEGER NOT NULL REFERENCES runs(id),
    row_index TEXT,
    column_name TEXT,
    detector TEXT,
    score REAL,
    value TEXT,
    reason TEXT
);
CREATE INDEX IF NOT EXISTS idx_anomalies_run ON anomalies(run_id);
CREATE TABLE IF NOT EXISTS alerts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id INTEGER,
    created_at TEXT NOT NULL,
    severity TEXT,
    title TEXT,
    status TEXT,
    channels TEXT
);
CREATE TABLE IF NOT EXISTS feedback (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    run_id INTEGER,
    anomaly_id INTEGER,
    detector TEXT NOT NULL,
    row_index TEXT,
    column_name TEXT,
    label TEXT NOT NULL,
    note TEXT
);
CREATE TABLE IF NOT EXISTS thresholds (
    detector TEXT PRIMARY KEY,
    multiplier REAL NOT NULL,
    updated_at TEXT NOT NULL,
    reason TEXT,
    last_feedback_id INTEGER DEFAULT 0
);
"""

RUN_FIELDS = (
    "rows",
    "n_anomalies",
    "anomaly_rate",
    "quality_score",
    "completeness",
    "validity",
    "uniqueness",
    "freshness",
    "cells_changed",
    "rows_dropped",
    "flagged_for_review",
    "alerts_sent",
    "duration_ms",
)


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class MetricsStore:
    def __init__(self, path: str | Path = DEFAULT_DB):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(self._conn()) as conn, conn:
            conn.executescript(SCHEMA)

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        return conn

    # -- runs -----------------------------------------------------------
    def start_run(self, pipeline: str) -> int:
        with closing(self._conn()) as conn, conn:
            cur = conn.execute(
                "INSERT INTO runs (pipeline, started_at, status) VALUES (?, ?, 'running')",
                (pipeline, now_iso()),
            )
            return int(cur.lastrowid)

    def finish_run(
        self,
        run_id: int,
        metrics: dict[str, Any],
        status: str = "success",
        error: str | None = None,
        detectors: dict[str, Any] | None = None,
    ) -> None:
        values = [metrics.get(k) for k in RUN_FIELDS]
        sets = ", ".join(f"{k} = ?" for k in RUN_FIELDS)
        with closing(self._conn()) as conn, conn:
            conn.execute(
                f"UPDATE runs SET {sets}, finished_at = ?, status = ?, error = ?, detectors_json = ?, metrics_json = ? WHERE id = ?",
                (
                    *values,
                    now_iso(),
                    status,
                    error,
                    json.dumps(detectors or {}),
                    json.dumps(metrics, default=str),
                    run_id,
                ),
            )

    def record_run(
        self, pipeline: str, metrics: dict[str, Any], status: str = "success", **kw: Any
    ) -> int:
        run_id = self.start_run(pipeline)
        self.finish_run(run_id, metrics, status, **kw)
        return run_id

    @staticmethod
    def _run_row(r: sqlite3.Row) -> dict[str, Any]:
        d = dict(r)
        d["detectors"] = json.loads(d.pop("detectors_json") or "{}")
        d.pop("metrics_json", None)
        return d

    def runs(self, limit: int = 100, pipeline: str | None = None) -> list[dict[str, Any]]:
        q = "SELECT * FROM runs"
        params: list[Any] = []
        if pipeline:
            q += " WHERE pipeline = ?"
            params.append(pipeline)
        q += " ORDER BY id DESC LIMIT ?"
        params.append(limit)
        with closing(self._conn()) as conn:
            return [self._run_row(r) for r in conn.execute(q, params).fetchall()]

    def get_run(self, run_id: int) -> dict[str, Any] | None:
        with closing(self._conn()) as conn:
            r = conn.execute("SELECT * FROM runs WHERE id = ?", (run_id,)).fetchone()
        if r is None:
            return None
        d = self._run_row(r)
        d["metrics"] = json.loads(r["metrics_json"] or "{}")
        return d

    def last_run(self, pipeline: str, status: str = "success") -> dict[str, Any] | None:
        with closing(self._conn()) as conn:
            r = conn.execute(
                "SELECT * FROM runs WHERE pipeline = ? AND status = ? ORDER BY id DESC LIMIT 1",
                (pipeline, status),
            ).fetchone()
        return self._run_row(r) if r else None

    def pipelines(self) -> list[str]:
        with closing(self._conn()) as conn:
            return [
                r[0]
                for r in conn.execute(
                    "SELECT DISTINCT pipeline FROM runs ORDER BY pipeline"
                ).fetchall()
            ]

    # -- anomalies --------------------------------------------------------
    def add_anomalies(self, run_id: int, findings: list[dict[str, Any]], limit: int = 1000) -> None:
        rows = [
            (
                run_id,
                json.dumps(f.get("index"), default=str),
                f.get("column"),
                f.get("detector"),
                f.get("score"),
                json.dumps(f.get("value"), default=str),
                f.get("reason"),
            )
            for f in findings[:limit]
        ]
        with closing(self._conn()) as conn, conn:
            conn.executemany(
                "INSERT INTO anomalies (run_id, row_index, column_name, detector, score, value, reason) VALUES (?, ?, ?, ?, ?, ?, ?)",
                rows,
            )

    def anomalies(self, run_id: int, limit: int = 500) -> list[dict[str, Any]]:
        with closing(self._conn()) as conn:
            rows = conn.execute(
                "SELECT * FROM anomalies WHERE run_id = ? ORDER BY score DESC LIMIT ?",
                (run_id, limit),
            ).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            d["row_index"] = json.loads(d["row_index"]) if d["row_index"] else None
            d["value"] = json.loads(d["value"]) if d["value"] else None
            d["column"] = d.pop("column_name")
            out.append(d)
        return out

    def get_anomaly(self, anomaly_id: int) -> dict[str, Any] | None:
        with closing(self._conn()) as conn:
            r = conn.execute("SELECT * FROM anomalies WHERE id = ?", (anomaly_id,)).fetchone()
        if r is None:
            return None
        d = dict(r)
        d["column"] = d.pop("column_name")
        return d

    # -- alerts ---------------------------------------------------------
    def add_alerts(self, run_id: int | None, records: list[dict[str, Any]]) -> None:
        with closing(self._conn()) as conn, conn:
            conn.executemany(
                "INSERT INTO alerts (run_id, created_at, severity, title, status, channels) VALUES (?, ?, ?, ?, ?, ?)",
                [
                    (
                        run_id,
                        r.get("timestamp") or now_iso(),
                        r.get("severity"),
                        r.get("title"),
                        r.get("status"),
                        ",".join(r.get("channels") or []),
                    )
                    for r in records
                ],
            )

    def alerts(self, limit: int = 100) -> list[dict[str, Any]]:
        with closing(self._conn()) as conn:
            return [
                dict(r)
                for r in conn.execute(
                    "SELECT * FROM alerts ORDER BY id DESC LIMIT ?", (limit,)
                ).fetchall()
            ]

    # -- feedback & thresholds -----------------------------------------
    def add_feedback(
        self,
        detector: str,
        label: str,
        run_id: int | None = None,
        anomaly_id: int | None = None,
        row_index: Any = None,
        column: str | None = None,
        note: str | None = None,
    ) -> int:
        if label not in ("false_positive", "true_positive"):
            raise ValueError("label must be 'false_positive' or 'true_positive'")
        with closing(self._conn()) as conn, conn:
            cur = conn.execute(
                "INSERT INTO feedback (created_at, run_id, anomaly_id, detector, row_index, column_name, label, note) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    now_iso(),
                    run_id,
                    anomaly_id,
                    detector,
                    json.dumps(row_index, default=str),
                    column,
                    label,
                    note,
                ),
            )
            return int(cur.lastrowid)

    def feedback_counts(self, since_last_tune: bool = False) -> dict[str, dict[str, int]]:
        """Feedback counts per detector; optionally only feedback newer than the
        detector's last threshold update."""
        q = "SELECT f.detector, f.label, COUNT(*) FROM feedback f"
        if since_last_tune:
            q += " LEFT JOIN thresholds t ON t.detector = f.detector WHERE t.updated_at IS NULL OR f.id > t.last_feedback_id"
        q += " GROUP BY f.detector, f.label"
        with closing(self._conn()) as conn:
            rows = conn.execute(q).fetchall()
        out: dict[str, dict[str, int]] = {}
        for det, label, n in rows:
            out.setdefault(det, {"false_positive": 0, "true_positive": 0})[label] = n
        return out

    def feedback(self, limit: int = 100) -> list[dict[str, Any]]:
        with closing(self._conn()) as conn:
            return [
                dict(r)
                for r in conn.execute(
                    "SELECT * FROM feedback ORDER BY id DESC LIMIT ?", (limit,)
                ).fetchall()
            ]

    def thresholds(self) -> dict[str, float]:
        with closing(self._conn()) as conn:
            return {
                r[0]: float(r[1])
                for r in conn.execute("SELECT detector, multiplier FROM thresholds").fetchall()
            }

    def set_threshold(self, detector: str, multiplier: float, reason: str = "") -> None:
        with closing(self._conn()) as conn, conn:
            last = conn.execute("SELECT COALESCE(MAX(id), 0) FROM feedback").fetchone()[0]
            conn.execute(
                "INSERT INTO thresholds (detector, multiplier, updated_at, reason, last_feedback_id) VALUES (?, ?, ?, ?, ?)"
                " ON CONFLICT(detector) DO UPDATE SET multiplier = excluded.multiplier, updated_at = excluded.updated_at,"
                " reason = excluded.reason, last_feedback_id = excluded.last_feedback_id",
                (detector, multiplier, now_iso(), reason, last),
            )

    def threshold_details(self) -> list[dict[str, Any]]:
        with closing(self._conn()) as conn:
            return [
                dict(r)
                for r in conn.execute("SELECT * FROM thresholds ORDER BY detector").fetchall()
            ]

    # -- summary ----------------------------------------------------------
    def summary(self) -> dict[str, Any]:
        with closing(self._conn()) as conn:
            totals = conn.execute(
                "SELECT COUNT(*), COALESCE(SUM(rows),0), COALESCE(SUM(n_anomalies),0), AVG(quality_score),"
                " COALESCE(SUM(alerts_sent),0) FROM runs WHERE status = 'success'"
            ).fetchone()
            failed = conn.execute("SELECT COUNT(*) FROM runs WHERE status = 'failed'").fetchone()[0]
        last = self.runs(limit=1)
        return {
            "runs": totals[0],
            "failed_runs": failed,
            "rows_processed": totals[1],
            "anomalies_found": totals[2],
            "avg_quality_score": None if totals[3] is None else round(totals[3], 4),
            "alerts_sent": totals[4],
            "pipelines": self.pipelines(),
            "last_run": last[0] if last else None,
        }
