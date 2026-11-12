"""SQLite-backed human review queue for flagged values."""

from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

SCHEMA = """
CREATE TABLE IF NOT EXISTS review_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    pipeline TEXT,
    run_id INTEGER,
    row_index TEXT,
    column_name TEXT,
    value TEXT,
    reason TEXT,
    suggestion TEXT,
    suggestion_confidence REAL,
    status TEXT NOT NULL DEFAULT 'pending',
    resolved_value TEXT,
    reviewer_note TEXT,
    resolved_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_review_status ON review_items(status);
"""

STATUSES = ("pending", "approved", "rejected")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _dump(v: Any) -> str | None:
    return None if v is None else json.dumps(v, default=str)


def _load(v: str | None) -> Any:
    if v is None:
        return None
    try:
        return json.loads(v)
    except (json.JSONDecodeError, TypeError):
        return v


class ReviewQueue:
    """Queue of values that need a human decision.

    ``approve(id, value=...)`` records the value to use (defaults to the
    suggestion, else the original value); ``reject`` keeps the original.
    ``apply`` writes approved values back into a DataFrame by index label.
    """

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(self._conn()) as conn, conn:
            conn.executescript(SCHEMA)

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        return conn

    def add(
        self,
        column: str | None,
        value: Any,
        reason: str,
        row_index: Any = None,
        pipeline: str | None = None,
        run_id: int | None = None,
        suggestion: Any = None,
        suggestion_confidence: float | None = None,
    ) -> int:
        with closing(self._conn()) as conn, conn:
            cur = conn.execute(
                "INSERT INTO review_items (created_at, pipeline, run_id, row_index, column_name, value, reason, suggestion, suggestion_confidence)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    _now(),
                    pipeline,
                    run_id,
                    _dump(row_index),
                    column,
                    _dump(value),
                    reason,
                    _dump(suggestion),
                    suggestion_confidence,
                ),
            )
            return int(cur.lastrowid)

    def find_pending(
        self, pipeline: str | None, row_index: Any, column: str | None, value: Any
    ) -> int | None:
        with closing(self._conn()) as conn:
            r = conn.execute(
                "SELECT id FROM review_items WHERE status = 'pending' AND pipeline IS ? AND row_index IS ?"
                " AND column_name IS ? AND value IS ?",
                (pipeline, _dump(row_index), column, _dump(value)),
            ).fetchone()
        return int(r[0]) if r else None

    def add_flagged(
        self, flagged: list[Any], pipeline: str | None = None, run_id: int | None = None
    ) -> list[int]:
        """Queue flagged items, skipping ones already pending (same pipeline, row,
        column and value) so re-running a pipeline does not duplicate work."""
        ids = []
        for f in flagged:
            d = f.to_dict() if hasattr(f, "to_dict") else dict(f)
            existing = self.find_pending(pipeline, d.get("index"), d.get("column"), d.get("value"))
            if existing is not None:
                ids.append(existing)
                continue
            ids.append(
                self.add(
                    d.get("column"),
                    d.get("value"),
                    d.get("reason", ""),
                    row_index=d.get("index"),
                    pipeline=pipeline,
                    run_id=run_id,
                    suggestion=d.get("suggestion"),
                    suggestion_confidence=d.get("suggestion_confidence"),
                )
            )
        return ids

    @staticmethod
    def _row(r: sqlite3.Row) -> dict[str, Any]:
        d = dict(r)
        for k in ("row_index", "value", "suggestion", "resolved_value"):
            d[k] = _load(d[k])
        d["column"] = d.pop("column_name")
        return d

    def get(self, item_id: int) -> dict[str, Any] | None:
        with closing(self._conn()) as conn:
            r = conn.execute("SELECT * FROM review_items WHERE id = ?", (item_id,)).fetchone()
        return self._row(r) if r else None

    def list(
        self, status: str | None = "pending", limit: int = 100, pipeline: str | None = None
    ) -> list[dict[str, Any]]:
        q = "SELECT * FROM review_items WHERE 1=1"
        params: list[Any] = []
        if status:
            q += " AND status = ?"
            params.append(status)
        if pipeline:
            q += " AND pipeline = ?"
            params.append(pipeline)
        q += " ORDER BY id DESC LIMIT ?"
        params.append(limit)
        with closing(self._conn()) as conn:
            return [self._row(r) for r in conn.execute(q, params).fetchall()]

    def counts(self) -> dict[str, int]:
        with closing(self._conn()) as conn:
            rows = conn.execute(
                "SELECT status, COUNT(*) FROM review_items GROUP BY status"
            ).fetchall()
        out = dict.fromkeys(STATUSES, 0)
        out.update({r[0]: r[1] for r in rows})
        return out

    def _resolve(self, item_id: int, status: str, value: Any, note: str | None) -> dict[str, Any]:
        item = self.get(item_id)
        if item is None:
            raise KeyError(f"Review item {item_id} not found")
        with closing(self._conn()) as conn, conn:
            conn.execute(
                "UPDATE review_items SET status = ?, resolved_value = ?, reviewer_note = ?, resolved_at = ? WHERE id = ?",
                (status, _dump(value), note, _now(), item_id),
            )
        return self.get(item_id)  # type: ignore[return-value]

    def approve(self, item_id: int, value: Any = None, note: str | None = None) -> dict[str, Any]:
        item = self.get(item_id)
        if item is None:
            raise KeyError(f"Review item {item_id} not found")
        if value is None:
            value = item["suggestion"] if item["suggestion"] is not None else item["value"]
        return self._resolve(item_id, "approved", value, note)

    def reject(self, item_id: int, note: str | None = None) -> dict[str, Any]:
        item = self.get(item_id)
        if item is None:
            raise KeyError(f"Review item {item_id} not found")
        return self._resolve(item_id, "rejected", item["value"], note)

    def apply(self, df: pd.DataFrame, pipeline: str | None = None) -> tuple[pd.DataFrame, int]:
        """Write approved values into ``df`` (matched on index label + column)."""
        out = df.copy()
        applied = 0
        for item in self.list(status="approved", limit=1_000_000, pipeline=pipeline):
            col, idx = item["column"], item["row_index"]
            if col in out.columns and idx in out.index:
                out.loc[idx, col] = item["resolved_value"]
                applied += 1
        return out, applied
