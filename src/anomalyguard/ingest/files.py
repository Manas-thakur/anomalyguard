"""File based sources: CSV/TSV, JSON/JSONL and Parquet."""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any, Literal

import pandas as pd

from anomalyguard.ingest.base import IngestError, Source


def _check_exists(path: str) -> None:
    if "://" in path:
        return  # URLs (http, s3, ...) are handled by pandas/fsspec
    if not Path(path).exists():
        raise IngestError(f"File not found: {path}")


class CSVSource(Source):
    """CSV/TSV file (local path or URL). Compression is inferred from the
    extension (``.gz``, ``.bz2``, ``.zip``, ``.xz``)."""

    kind = "csv"

    def __init__(
        self,
        path: str | Path,
        delimiter: str | None = None,
        has_header: bool = True,
        encoding: str = "utf-8",
        compression: str | None = "infer",
        name: str | None = None,
        cursor: str | None = None,
        read_options: dict[str, Any] | None = None,
    ):
        super().__init__(name or Path(str(path)).stem, cursor)
        self.path = str(path)
        if delimiter is None:
            delimiter = "\t" if self.path.lower().endswith((".tsv", ".tsv.gz", ".tab")) else ","
        self.delimiter = delimiter
        self.has_header = has_header
        self.encoding = encoding
        self.compression = compression
        self.read_options = read_options or {}

    def _iter_batches(self, batch_size: int) -> Iterator[pd.DataFrame]:
        _check_exists(self.path)
        try:
            reader = pd.read_csv(
                self.path,
                sep=self.delimiter,
                header=0 if self.has_header else None,
                encoding=self.encoding,
                compression=self.compression,
                chunksize=batch_size,
                skipinitialspace=True,
                **self.read_options,
            )
            with reader:
                for chunk in reader:
                    if not self.has_header:
                        chunk.columns = [f"col_{i}" for i in range(chunk.shape[1])]
                    yield chunk
        except pd.errors.EmptyDataError:
            return

    def describe(self) -> dict[str, Any]:
        return {**super().describe(), "path": self.path}


class JSONSource(Source):
    """JSON array/object files and JSON Lines (``.jsonl``/``.ndjson``).

    ``records_path`` is a dotted path to the list of records inside a JSON
    document (e.g. ``data.items``). ``flatten`` expands nested objects into
    ``parent.child`` columns.
    """

    kind = "json"

    def __init__(
        self,
        path: str | Path,
        format: Literal["auto", "json", "jsonl"] = "auto",
        records_path: str | None = None,
        flatten: bool = True,
        encoding: str = "utf-8",
        name: str | None = None,
        cursor: str | None = None,
    ):
        super().__init__(name or Path(str(path)).stem, cursor)
        self.path = str(path)
        if format == "auto":
            format = (
                "jsonl"
                if self.path.lower().endswith((".jsonl", ".ndjson", ".jsonl.gz"))
                else "json"
            )
        self.format = format
        self.records_path = records_path
        self.flatten = flatten
        self.encoding = encoding

    def _to_frame(self, records: list[Any]) -> pd.DataFrame:
        if self.flatten:
            return pd.json_normalize(records)
        return pd.DataFrame.from_records(records)

    def _iter_batches(self, batch_size: int) -> Iterator[pd.DataFrame]:
        _check_exists(self.path)
        if self.format == "jsonl":
            buf: list[Any] = []
            opener = _open_text(self.path, self.encoding)
            with opener as fh:
                for lineno, line in enumerate(fh, 1):
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        buf.append(json.loads(line))
                    except json.JSONDecodeError as exc:
                        raise IngestError(
                            f"{self.path}:{lineno}: invalid JSON ({exc.msg})"
                        ) from exc
                    if len(buf) >= batch_size:
                        yield self._to_frame(buf)
                        buf = []
            if buf:
                yield self._to_frame(buf)
            return

        with _open_text(self.path, self.encoding) as fh:
            try:
                doc = json.load(fh)
            except json.JSONDecodeError as exc:
                raise IngestError(f"{self.path}: invalid JSON ({exc.msg})") from exc
        records = extract_path(doc, self.records_path)
        if isinstance(records, dict):
            records = [records]
        if not isinstance(records, list):
            raise IngestError(
                f"{self.path}: expected a list of records at '{self.records_path or '$'}'"
            )
        for i in range(0, len(records), batch_size):
            yield self._to_frame(records[i : i + batch_size])

    def describe(self) -> dict[str, Any]:
        return {**super().describe(), "path": self.path, "format": self.format}


def _open_text(path: str, encoding: str):
    if path.lower().endswith(".gz"):
        import gzip

        return gzip.open(path, "rt", encoding=encoding)
    return open(path, encoding=encoding)


def extract_path(doc: Any, path: str | None) -> Any:
    """Follow a dotted path (``a.b.0.c``) into nested dicts/lists."""
    if not path:
        return doc
    cur = doc
    for part in path.split("."):
        if isinstance(cur, list) and part.isdigit():
            cur = cur[int(part)]
        elif isinstance(cur, dict):
            if part not in cur:
                raise IngestError(f"key '{part}' not found while resolving '{path}'")
            cur = cur[part]
        else:
            raise IngestError(f"cannot resolve '{part}' in '{path}'")
    return cur


class ParquetSource(Source):
    """Parquet file, read in row batches (requires the ``parquet`` extra)."""

    kind = "parquet"

    def __init__(
        self,
        path: str | Path,
        columns: list[str] | None = None,
        name: str | None = None,
        cursor: str | None = None,
    ):
        super().__init__(name or Path(str(path)).stem, cursor)
        self.path = str(path)
        self.columns = columns

    def _iter_batches(self, batch_size: int) -> Iterator[pd.DataFrame]:
        try:
            import pyarrow.parquet as pq
        except ImportError as exc:  # pragma: no cover - depends on extras
            raise IngestError(
                "Parquet support needs pyarrow: pip install 'anomalyguard[parquet]'"
            ) from exc
        _check_exists(self.path)
        pf = pq.ParquetFile(self.path)
        for batch in pf.iter_batches(batch_size=batch_size, columns=self.columns):
            yield batch.to_pandas()

    def describe(self) -> dict[str, Any]:
        return {**super().describe(), "path": self.path}
