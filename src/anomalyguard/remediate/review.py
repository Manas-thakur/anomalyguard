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

# columns added after 0.1.0; created on open for older databases
MIGRATIONS = {
    "detector": "ALTER TABLE review_items ADD COLUMN detector TEXT",
    "applied_at": "ALTER TABLE review_items ADD COLUMN applied_at TEXT",
}

STATUSES = ("pending", "approved", "rejected", "applied")
SORTS = {
    "id": "id",
    "created_at": "created_at",
    "column": "column_name",
    "pipeline": "pipeline",
    "status": "status",
    "detector": "detector",
}


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

    def __init__(self, path: str | Path, create: bool = True):
        self.path = Path(path)
        if not create and not self.path.is_file():
            raise FileNotFoundError(f"Review database not found: {self.path}")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(self._conn()) as conn, conn:
            conn.executescript(SCHEMA)
            have = {r[1] for r in conn.execute("PRAGMA table_info(review_items)").fetchall()}
            for col, ddl in MIGRATIONS.items():
                if col not in have:
                    conn.execute(ddl)
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_review_filters"
                " ON review_items(status, pipeline, column_name)"
            )

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, timeout=30)
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
        detector: str | None = None,
    ) -> int:
        with closing(self._conn()) as conn, conn:
            cur = conn.execute(
                "INSERT INTO review_items (created_at, pipeline, run_id, row_index, column_name, value,"
                " reason, suggestion, suggestion_confidence, detector)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
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
                    detector,
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
                if d.get("applied"):
                    self._mark_auto_applied(existing, d.get("suggestion"))
                continue
            item_id = self.add(
                d.get("column"),
                d.get("value"),
                d.get("reason", ""),
                row_index=d.get("index"),
                pipeline=pipeline,
                run_id=run_id,
                suggestion=d.get("suggestion"),
                suggestion_confidence=d.get("suggestion_confidence"),
                detector=d.get("detector"),
            )
            if d.get("applied"):
                # the suggestion was already written to the output (LLM auto_apply)
                self._mark_auto_applied(item_id, d.get("suggestion"))
            ids.append(item_id)
        return ids

    def _mark_auto_applied(self, item_id: int, value: Any) -> None:
        now = _now()
        with closing(self._conn()) as conn, conn:
            conn.execute(
                "UPDATE review_items SET status = 'applied', resolved_value = ?, resolved_at = ?,"
                " applied_at = ?, reviewer_note = ? WHERE id = ?",
                (_dump(value), now, now, "applied automatically (LLM suggestion)", item_id),
            )

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

    @staticmethod
    def _where(
        status: str | None = None,
        pipeline: str | None = None,
        column: str | None = None,
        detector: str | None = None,
        run_id: int | None = None,
        q: str | None = None,
        ids: list[int] | None = None,
    ) -> tuple[str, list[Any]]:
        clauses, params = ["1=1"], []
        for value, sql in (
            (status, "status = ?"),
            (pipeline, "pipeline = ?"),
            (column, "column_name = ?"),
            (detector, "detector = ?"),
            (run_id, "run_id = ?"),
        ):
            if value not in (None, ""):
                clauses.append(sql)
                params.append(value)
        if q:
            clauses.append("(reason LIKE ? OR value LIKE ? OR row_index LIKE ?)")
            params += [f"%{q}%"] * 3
        if ids is not None:
            marks = ",".join("?" * len(ids)) or "NULL"
            clauses.append(f"id IN ({marks})")
            params += [int(i) for i in ids]
        return " AND ".join(clauses), params

    def query(
        self,
        status: str | None = "pending",
        pipeline: str | None = None,
        column: str | None = None,
        detector: str | None = None,
        run_id: int | None = None,
        q: str | None = None,
        offset: int = 0,
        limit: int = 50,
        sort: str = "id",
        descending: bool = True,
    ) -> tuple[list[dict[str, Any]], int]:
        """Filtered, paginated items plus the total number of matches."""
        where, params = self._where(status, pipeline, column, detector, run_id, q)
        order = SORTS.get(sort, "id")
        direction = "DESC" if descending else "ASC"
        with closing(self._conn()) as conn:
            total = conn.execute(
                f"SELECT COUNT(*) FROM review_items WHERE {where}", params
            ).fetchone()[0]
            rows = conn.execute(
                f"SELECT * FROM review_items WHERE {where} ORDER BY {order} {direction}, id DESC"
                " LIMIT ? OFFSET ?",
                [*params, int(limit), int(offset)],
            ).fetchall()
        return [self._row(r) for r in rows], int(total)

    def ids(self, **filters: Any) -> list[int]:
        """Ids of every item matching the filters (see :meth:`query`)."""
        where, params = self._where(**filters)
        with closing(self._conn()) as conn:
            return [
                int(r[0])
                for r in conn.execute(
                    f"SELECT id FROM review_items WHERE {where} ORDER BY id", params
                ).fetchall()
            ]

    def facets(self, status: str | None = None) -> dict[str, Any]:
        """Distinct pipelines, columns and detectors (for filter menus) plus status counts."""
        where, params = self._where(status=status)
        out: dict[str, Any] = {"counts": self.counts()}
        with closing(self._conn()) as conn:
            for key, col in (
                ("pipelines", "pipeline"),
                ("columns", "column_name"),
                ("detectors", "detector"),
            ):
                out[key] = [
                    {"value": r[0], "count": r[1]}
                    for r in conn.execute(
                        f"SELECT {col}, COUNT(*) FROM review_items WHERE {where}"
                        f" AND {col} IS NOT NULL GROUP BY {col} ORDER BY COUNT(*) DESC, {col}",
                        params,
                    ).fetchall()
                ]
        return out

    def mark_applied(self, item_ids: list[int]) -> int:
        if not item_ids:
            return 0
        marks = ",".join("?" * len(item_ids))
        with closing(self._conn()) as conn, conn:
            cur = conn.execute(
                "UPDATE review_items SET status = 'applied', applied_at = ?"
                f" WHERE status = 'approved' AND id IN ({marks})",
                [_now(), *[int(i) for i in item_ids]],
            )
            return int(cur.rowcount)

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
            if item["status"] in ("approved", "applied") and item["resolved_value"] is not None:
                # approving again (e.g. a bulk approve) keeps the reviewer's value
                value = item["resolved_value"]
            else:
                value = item["suggestion"] if item["suggestion"] is not None else item["value"]
        if note is None:
            note = item.get("reviewer_note")
        unchanged = item["status"] == "applied" and value == item["resolved_value"]
        status = "applied" if unchanged else "approved"
        return self._resolve(item_id, status, value, note)

    def reject(self, item_id: int, note: str | None = None) -> dict[str, Any]:
        item = self.get(item_id)
        if item is None:
            raise KeyError(f"Review item {item_id} not found")
        return self._resolve(item_id, "rejected", item["value"], note)

    def apply(
        self,
        df: pd.DataFrame,
        pipeline: str | None = None,
        item_ids: list[int] | None = None,
        mark: bool = False,
    ) -> tuple[pd.DataFrame, int]:
        """Write approved values into ``df`` (matched on index label + column).

        ``item_ids`` limits this to those items; with ``mark=True`` the items
        that were written move to the ``applied`` status.
        """
        out = df.copy()
        done: list[int] = []
        wanted = None if item_ids is None else {int(i) for i in item_ids}
        for item in self.list(status="approved", limit=1_000_000, pipeline=pipeline):
            if wanted is not None and item["id"] not in wanted:
                continue
            col, idx = item["column"], item["row_index"]
            if col in out.columns and idx in out.index:
                value = item["resolved_value"]
                kind = out[col].dtype.kind
                if kind in "iu" and isinstance(value, float):
                    out[col] = out[col].astype(float)
                elif kind in "iuf" and isinstance(value, str):
                    out[col] = out[col].astype(object)
                out.loc[idx, col] = value
                done.append(item["id"])
        if mark:
            self.mark_applied(done)
        return out, len(done)
