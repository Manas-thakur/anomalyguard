"""Write cleaned data to CSV, JSON Lines, Parquet or a SQLite table."""

from __future__ import annotations

import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Any

import pandas as pd


def write_frame(
    df: pd.DataFrame,
    path: str | Path,
    kind: str | None = None,
    table: str | None = None,
    mode: str = "overwrite",
) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    kind = (kind or _guess(path)).lower()
    append = mode == "append"
    if kind == "csv":
        df.to_csv(
            path,
            index=False,
            mode="a" if append else "w",
            header=not (append and path.exists() and path.stat().st_size > 0),
        )
    elif kind in ("jsonl", "ndjson"):
        text = df.to_json(orient="records", lines=True, date_format="iso")
        with path.open("a" if append else "w", encoding="utf-8") as fh:
            fh.write(text if text.endswith("\n") or not text else text + "\n")
    elif kind == "json":
        df.to_json(path, orient="records", indent=2, date_format="iso")
    elif kind == "parquet":
        df.to_parquet(path, index=False)
    elif kind in ("sqlite", "sql"):
        with closing(sqlite3.connect(path)) as conn:
            df.to_sql(
                table or "cleaned", conn, if_exists="append" if append else "replace", index=False
            )
    else:
        raise ValueError(f"Unknown sink type '{kind}'")
    return path


SINK_SUFFIXES = {
    ".csv": "csv",
    ".jsonl": "jsonl",
    ".ndjson": "jsonl",
    ".json": "json",
    ".parquet": "parquet",
    ".db": "sqlite",
    ".sqlite": "sqlite",
}


def _guess(path: Path) -> str:
    suffix = path.suffix.lower()
    if not suffix:
        return "csv"
    if suffix not in SINK_SUFFIXES:
        raise ValueError(
            f"Cannot write '{path.name}': unsupported file type '{suffix}' "
            "(use .csv, .jsonl, .json, .parquet, .db or .sqlite)"
        )
    return SINK_SUFFIXES[suffix]


def write_sink(df: pd.DataFrame, cfg: dict[str, Any], resolve) -> Path:
    return write_frame(
        df, resolve(cfg["path"]), cfg.get("type"), cfg.get("table"), cfg.get("mode", "overwrite")
    )
