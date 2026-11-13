"""File based sources: CSV/TSV, JSON/JSONL and Parquet."""

from __future__ import annotations

import codecs
import csv
import json
import logging
import re
import warnings
from collections.abc import Iterator
from pathlib import Path
from typing import Any, Literal

import pandas as pd

from anomalyguard.ingest.base import IngestError, Source

log = logging.getLogger("anomalyguard.ingest")


def _check_exists(path: str) -> None:
    if "://" in path:
        return  # URLs (http, s3, ...) are handled by pandas/fsspec
    if not Path(path).exists():
        raise IngestError(f"File not found: {path}")


DELIMITER_CANDIDATES = (",", ";", "\t", "|")
FALLBACK_ENCODINGS = ("cp1252", "latin-1")
_SNIFF_BYTES = 64 * 1024
_COMMA_DECIMAL = re.compile(r"^[+-]?\d{1,3}(?:\.\d{3})*,\d+$|^[+-]?\d+,\d+$")


def _open_binary(path: str, compression: str | None) -> Any:
    """Open a local (possibly compressed) file for reading bytes, or None."""
    kind = compression
    if compression == "infer":
        low = path.lower()
        kind = next(
            (
                k
                for ext, k in ((".gz", "gzip"), (".bz2", "bz2"), (".xz", "xz"))
                if low.endswith(ext)
            ),
            None if not low.endswith(".zip") else "zip",
        )
    if kind == "gzip":
        import gzip

        return gzip.open(path, "rb")
    if kind == "bz2":
        import bz2

        return bz2.open(path, "rb")
    if kind == "xz":
        import lzma

        return lzma.open(path, "rb")
    if kind in (None, "infer"):
        return open(path, "rb")
    return None  # zip/zstd/...: leave detection to pandas


def detect_encoding(path: str, compression: str | None = "infer") -> tuple[str, bool]:
    """Return ``(encoding, fell_back)``: UTF-8 (with or without BOM) when the
    whole file decodes, else cp1252, else latin-1 (which never fails)."""
    probe = _open_binary(path, compression)
    if probe is None:
        return "utf-8", False
    probe.close()
    candidates = ["utf-8-sig", *FALLBACK_ENCODINGS]
    for i, enc in enumerate(candidates):
        decoder = codecs.getincrementaldecoder(enc)()
        try:
            with _open_binary(path, compression) as f:
                while block := f.read(1 << 20):
                    decoder.decode(block)
                decoder.decode(b"", final=True)
            return enc, i > 0
        except UnicodeDecodeError:
            continue
    return "latin-1", True  # pragma: no cover - latin-1 decodes any byte


def _split_counts(lines: list[str], delimiter: str) -> list[int]:
    return [len(row) for row in csv.reader(lines, delimiter=delimiter) if row]


def sniff_delimiter(sample: str, default: str = ",") -> str:
    """Guess the field delimiter from a text sample.

    ``csv.Sniffer`` (restricted to ``, ; TAB |``) proposes a delimiter; it is
    accepted when it splits the header into several fields and most rows into
    the same number of fields. Otherwise the candidate that does that best wins,
    and with no such candidate ``default`` is returned.
    """
    lines = [ln for ln in sample.splitlines()[:200] if ln.strip()]
    if len(lines) > 1 and not sample.endswith(("\n", "\r")):
        lines = lines[:-1]  # the sample may cut the last line short
    if not lines:
        return default

    def consistency(delim: str) -> float:
        counts = _split_counts(lines, delim)
        if not counts or counts[0] < 2:
            return 0.0
        return sum(c == counts[0] for c in counts) / len(counts)

    try:
        guess = csv.Sniffer().sniff("\n".join(lines), delimiters="".join(DELIMITER_CANDIDATES))
        if consistency(guess.delimiter) >= 0.9:
            return guess.delimiter
    except csv.Error:
        pass
    scored = [(consistency(d), -i, d) for i, d in enumerate(DELIMITER_CANDIDATES)]
    best = max(scored)
    return best[2] if best[0] >= 0.9 else default


class CSVSource(Source):
    """CSV/TSV file (local path or URL). Compression is inferred from the
    extension (``.gz``, ``.bz2``, ``.zip``, ``.xz``).

    * ``delimiter``: sniffed from the start of the file when not given
      (candidates ``,`` ``;`` TAB ``|``).
    * ``encoding``: when not given, UTF-8 (with or without BOM) is used if the
      file decodes as UTF-8; otherwise cp1252/latin-1 with a warning.
    * Missing values: only empty cells are missing. Text such as ``NA``,
      ``N/A``, ``null`` or ``None`` is kept as a value (``NA`` is often North
      America or Namibia); pass ``na_values=["NA", "null"]`` to treat extra
      tokens as missing.
    * ``decimal``: decimal separator; ``","`` is chosen automatically for
      semicolon files whose numbers are written like ``3,14``.
    """

    kind = "csv"

    def __init__(
        self,
        path: str | Path,
        delimiter: str | None = None,
        has_header: bool = True,
        encoding: str | None = None,
        compression: str | None = "infer",
        name: str | None = None,
        cursor: str | None = None,
        read_options: dict[str, Any] | None = None,
        na_values: list[str] | str | None = None,
        decimal: str | None = None,
    ):
        super().__init__(name or Path(str(path)).stem, cursor)
        self.path = str(path)
        self.delimiter = _unescape(delimiter) if delimiter else None
        self.has_header = has_header
        self.encoding = encoding or None
        self.compression = compression
        self.read_options = dict(read_options or {})
        if isinstance(na_values, str):
            na_values = [v.strip() for v in na_values.split(",") if v.strip()]
        extra = self.read_options.pop("na_values", None)
        if isinstance(extra, str):
            extra = [extra]
        self.na_values = [str(v) for v in [*(na_values or []), *(extra or [])]]
        self.decimal = decimal
        self.warnings: list[str] = []

    def _default_delimiter(self) -> str:
        low = self.path.lower()
        return "\t" if low.endswith((".tsv", ".tsv.gz", ".tab")) else ","

    def _resolve_format(self) -> None:
        """Pick encoding, delimiter and decimal separator (once)."""
        local = "://" not in self.path
        if self.encoding is None:
            if local:
                enc, fell_back = detect_encoding(self.path, self.compression)
                if fell_back:
                    self._warn(
                        f"{self.path} is not valid UTF-8; read it as {enc} "
                        "(pass --encoding / source.encoding to choose another)"
                    )
                self.encoding = enc
            else:
                self.encoding = "utf-8"
        sample = ""
        if local:
            fh = _open_binary(self.path, self.compression)
            if fh is not None:
                with fh:
                    sample = fh.read(_SNIFF_BYTES).decode(self.encoding, errors="replace")
        if self.delimiter is None:
            self.delimiter = (
                sniff_delimiter(sample, self._default_delimiter())
                if sample
                else (self._default_delimiter())
            )
        if self.decimal is None:
            self.decimal = "."
            if self.delimiter == ";" and sample:
                cells = [
                    c.strip().strip('"')
                    for row in csv.reader(sample.splitlines()[1:200], delimiter=";")
                    for c in row
                ]
                numeric_like = [c for c in cells if c and c[-1:].isdigit()]
                if numeric_like and (
                    sum(bool(_COMMA_DECIMAL.match(c)) for c in numeric_like) / len(numeric_like)
                    >= 0.5
                ):
                    self.decimal = ","

    def _warn(self, message: str) -> None:
        self.warnings.append(message)
        log.warning(message)

    def _iter_batches(self, batch_size: int) -> Iterator[pd.DataFrame]:
        _check_exists(self.path)
        if "://" not in self.path and Path(self.path).stat().st_size == 0:
            raise IngestError(f"{self.path}: file is empty")
        self._resolve_format()
        options = dict(self.read_options)
        options.setdefault("keep_default_na", False)
        options.setdefault("na_values", ["", *self.na_values])
        if self.decimal and self.decimal != ".":
            options.setdefault("decimal", self.decimal)
        options.setdefault("index_col", False)
        try:
            reader = pd.read_csv(
                self.path,
                sep=self.delimiter,
                header=0 if self.has_header else None,
                encoding=self.encoding,
                compression=self.compression,
                chunksize=batch_size,
                skipinitialspace=True,
                **options,
            )
            first = True
            dropped_fields = False
            with reader:
                chunks = iter(reader)
                while True:
                    # pandas warns when rows have more fields than the header;
                    # report that once, in our own words
                    with warnings.catch_warnings(record=True) as caught:
                        warnings.simplefilter("always", pd.errors.ParserWarning)
                        try:
                            chunk = next(chunks)
                        except StopIteration:
                            break
                    for w in caught:
                        if issubclass(w.category, pd.errors.ParserWarning):
                            dropped_fields = True
                        else:
                            warnings.warn(w.message, w.category, stacklevel=2)
                    if not self.has_header:
                        chunk.columns = [f"col_{i}" for i in range(chunk.shape[1])]
                    if first:
                        first = False
                        self._check_single_column(chunk)
                    yield chunk
            if dropped_fields:
                self._warn(
                    f"{self.path}: some rows have more fields than the header (delimiter "
                    f"{self.delimiter!r}); the extra fields were not read"
                )
        except pd.errors.EmptyDataError:
            return
        except pd.errors.ParserError as exc:
            raise IngestError(
                f"{self.path}: cannot parse as CSV with delimiter {self.delimiter!r} "
                f"({str(exc).strip()}); "
                "pass --delimiter / source.delimiter"
            ) from exc

    def _check_single_column(self, chunk: pd.DataFrame) -> None:
        if chunk.shape[1] != 1:
            return
        header = str(chunk.columns[0])
        others = [d for d in DELIMITER_CANDIDATES if d != self.delimiter and d in header]
        if others:
            shown = "TAB" if others[0] == "\t" else others[0]
            self._warn(
                f"{self.path} parsed as a single column {header!r}; the header contains "
                f"{shown!r}, so the delimiter is probably {shown!r} "
                f"(pass --delimiter / source.delimiter)"
            )

    def describe(self) -> dict[str, Any]:
        return {**super().describe(), "path": self.path}


def _unescape(delimiter: str) -> str:
    """Allow ``\\t``/``tab`` on the command line and in YAML."""
    return {"\\t": "\t", "tab": "\t", "TAB": "\t", "pipe": "|", "semicolon": ";"}.get(
        delimiter, delimiter
    )


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
            from anomalyguard.monitor.doctor import install_command

            raise IngestError(
                f"Parquet support needs pyarrow: {install_command('parquet')}"
            ) from exc
        _check_exists(self.path)
        pf = pq.ParquetFile(self.path)
        for batch in pf.iter_batches(batch_size=batch_size, columns=self.columns):
            yield batch.to_pandas()

    def describe(self) -> dict[str, Any]:
        return {**super().describe(), "path": self.path}
