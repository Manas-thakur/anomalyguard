"""SQL databases. SQLite works out of the box via the standard library; any
other SQLAlchemy URL (PostgreSQL, MySQL, ...) needs the ``sql`` extra."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pandas as pd

from anomalyguard.ingest.base import IngestError, Source


def _sqlite_path(url: str) -> str | None:
    if url.startswith("sqlite:///"):
        return url[len("sqlite:///") :]
    if url.startswith("sqlite://"):
        return url[len("sqlite://") :] or ":memory:"
    if "://" not in url and url.lower().endswith((".db", ".sqlite", ".sqlite3")):
        return url
    return None


def _missing_table_message(url: str) -> str:
    msg = "Reading a database needs a table: pass --table NAME (or `table:`/`query:` in the source config)"
    path = _sqlite_path(url)
    if path and path != ":memory:" and Path(path).exists():
        try:
            conn = sqlite3.connect(path)
            try:
                names = [
                    r[0]
                    for r in conn.execute(
                        "SELECT name FROM sqlite_master WHERE type IN ('table', 'view')"
                        " AND name NOT LIKE 'sqlite_%' ORDER BY name"
                    ).fetchall()
                ]
            finally:
                conn.close()
        except sqlite3.Error:
            names = []
        msg += f". Tables in {path}: {', '.join(names) if names else '(none)'}"
    return msg


class SQLSource(Source):
    """Read a table or query.

    With ``cursor`` set, incremental reads push the watermark into SQL:
    ``SELECT * FROM (<query>) WHERE cursor > :watermark ORDER BY cursor``.
    """

    kind = "sql"

    def __init__(
        self,
        url: str,
        query: str | None = None,
        table: str | None = None,
        name: str | None = None,
        cursor: str | None = None,
    ):
        if not query and not table:
            raise ValueError(_missing_table_message(str(url)))
        super().__init__(name or table or "sql", cursor)
        self.url = str(url)
        self.table = table
        self.query = query or f'SELECT * FROM "{table}"'

    def _build_query(self) -> tuple[str, dict[str, Any]]:
        if self.cursor and self._watermark is not None:
            q = (
                f'SELECT * FROM ({self.query}) AS _ag WHERE "{self.cursor}" > :watermark '
                f'ORDER BY "{self.cursor}"'
            )
            return q, {"watermark": self._watermark}
        if self.cursor:
            return f'SELECT * FROM ({self.query}) AS _ag ORDER BY "{self.cursor}"', {}
        return self.query, {}

    def _iter_batches(self, batch_size: int) -> Iterator[pd.DataFrame]:
        query, params = self._build_query()
        path = _sqlite_path(self.url)
        if path is not None:
            if path != ":memory:" and not Path(path).exists():
                raise IngestError(f"SQLite database not found: {path}")
            conn = sqlite3.connect(path)
            try:
                yield from pd.read_sql_query(
                    query, conn, params=params or None, chunksize=batch_size
                )
            finally:
                conn.close()
            return
        try:
            from sqlalchemy import create_engine, text
        except ImportError as exc:  # pragma: no cover - depends on extras
            from anomalyguard.monitor.doctor import install_command

            raise IngestError(
                f"Non-SQLite databases need SQLAlchemy: {install_command('sql')}"
            ) from exc
        engine = create_engine(self.url)
        try:
            with engine.connect() as conn:
                yield from pd.read_sql_query(
                    text(query), conn, params=params or None, chunksize=batch_size
                )
        finally:
            engine.dispose()

    def describe(self) -> dict[str, Any]:
        safe_url = self.url.split("@")[-1] if "@" in self.url else self.url
        return {**super().describe(), "url": safe_url, "table": self.table}
