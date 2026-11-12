"""Build sources from config dicts and read files by extension."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd

from anomalyguard.ingest.base import IngestError, Source
from anomalyguard.ingest.files import CSVSource, JSONSource, ParquetSource
from anomalyguard.ingest.rest import RESTSource
from anomalyguard.ingest.sql import SQLSource

SOURCE_TYPES: dict[str, type[Source]] = {
    "csv": CSVSource,
    "tsv": CSVSource,
    "json": JSONSource,
    "jsonl": JSONSource,
    "ndjson": JSONSource,
    "parquet": ParquetSource,
    "sql": SQLSource,
    "sqlite": SQLSource,
    "database": SQLSource,
    "rest": RESTSource,
    "api": RESTSource,
    "http": RESTSource,
}


def guess_type(path: str) -> str:
    p = path.lower()
    for suffix in (".gz", ".bz2", ".zip", ".xz"):
        if p.endswith(suffix):
            p = p[: -len(suffix)]
    if p.endswith((".csv", ".tsv", ".txt", ".tab")):
        return "csv"
    if p.endswith((".jsonl", ".ndjson")):
        return "jsonl"
    if p.endswith(".json"):
        return "json"
    if p.endswith((".parquet", ".pq")):
        return "parquet"
    if p.endswith((".db", ".sqlite", ".sqlite3")) or p.startswith(
        ("sqlite:", "postgresql:", "mysql:")
    ):
        return "sql"
    if p.startswith(("http://", "https://")):
        return "rest"
    raise IngestError(f"Cannot guess source type for '{path}'; pass type explicitly")


def _resolve(path: str, base_dir: str | Path | None) -> str:
    if base_dir is None or "://" in path or Path(path).is_absolute():
        return path
    return str(Path(base_dir) / path)


def create_source(config: dict[str, Any], base_dir: str | Path | None = None) -> Source:
    """Create a source from a config mapping such as
    ``{"type": "csv", "path": "data.csv", "cursor": "timestamp"}``."""
    cfg = dict(config)
    stype = str(cfg.pop("type", "") or "").lower()
    if not stype:
        target = cfg.get("path") or cfg.get("url")
        if not target:
            raise IngestError("Source config needs a 'type' or a 'path'/'url'")
        stype = guess_type(str(target))
    if stype not in SOURCE_TYPES:
        raise IngestError(f"Unknown source type '{stype}'. Known: {sorted(set(SOURCE_TYPES))}")
    cls = SOURCE_TYPES[stype]
    if "path" in cfg:
        cfg["path"] = _resolve(str(cfg["path"]), base_dir)
    if cls is SQLSource:
        url = str(cfg.pop("url", cfg.pop("path", "")))
        if _looks_like_sqlite_file(url):
            url = _resolve(url, base_dir)
        cfg["url"] = url
    if cls is JSONSource and stype in ("jsonl", "ndjson"):
        cfg.setdefault("format", "jsonl")
    try:
        return cls(**cfg)
    except TypeError as exc:
        raise IngestError(f"Invalid options for source '{stype}': {exc}") from exc


def _looks_like_sqlite_file(url: str) -> bool:
    return "://" not in url and url.lower().endswith((".db", ".sqlite", ".sqlite3"))


def read_any(path: str | Path, limit: int | None = None, **options: Any) -> pd.DataFrame:
    """Read a CSV/TSV/JSON/JSONL/Parquet file (or SQLite with ``table=``) into a DataFrame."""
    path = str(path)
    cfg: dict[str, Any] = {"type": options.pop("type", None) or guess_type(path), **options}
    if cfg["type"] == "sql":
        cfg["url"] = path
    else:
        cfg["path"] = path
    with create_source(cfg) as src:
        return src.read(limit=limit)
