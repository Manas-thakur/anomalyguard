"""Source interface, checkpoints and watermark helpers."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Iterator
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any

import pandas as pd


class IngestError(RuntimeError):
    """Raised when a source cannot be read."""


@dataclass
class Checkpoint:
    """Position of a source: rows consumed and the highest cursor value seen."""

    source: str
    offset: int = 0
    watermark: Any = None
    record_count: int = 0
    updated_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    extra: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Checkpoint:
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


def _jsonable_scalar(v: Any) -> Any:
    if v is None:
        return None
    if isinstance(v, pd.Timestamp):
        return v.isoformat()
    if hasattr(v, "item"):
        return v.item()
    return v


def filter_after_watermark(df: pd.DataFrame, column: str, watermark: Any) -> pd.DataFrame:
    """Keep rows whose ``column`` value is strictly greater than ``watermark``."""
    if watermark is None or column not in df.columns or df.empty:
        return df
    col = df[column]
    try:
        wm_num = float(watermark)
        nums = pd.to_numeric(col, errors="coerce")
        if nums.notna().all():
            return df[nums > wm_num]
    except (TypeError, ValueError):
        pass
    ts = pd.to_datetime(col, errors="coerce", format="mixed")
    wm_ts = pd.to_datetime(watermark, errors="coerce")
    if ts.notna().any() and wm_ts is not pd.NaT:
        if ts.dt.tz is not None and wm_ts.tzinfo is None:
            wm_ts = wm_ts.tz_localize(ts.dt.tz)
        elif ts.dt.tz is None and wm_ts.tzinfo is not None:
            wm_ts = wm_ts.tz_localize(None)
        return df[ts > wm_ts]
    return df[col.astype(str) > str(watermark)]


def max_cursor(df: pd.DataFrame, column: str) -> Any:
    if column not in df.columns or df.empty:
        return None
    col = df[column].dropna()
    if col.empty:
        return None
    nums = pd.to_numeric(col, errors="coerce")
    if nums.notna().all():
        return _jsonable_scalar(nums.max())
    ts = pd.to_datetime(col, errors="coerce", format="mixed")
    if ts.notna().all():
        return ts.max().isoformat()
    return str(col.astype(str).max())


class Source(ABC):
    """A data source that yields pandas DataFrames in batches.

    Subclasses implement :meth:`_iter_batches`. The base class adds:

    * offset tracking (rows consumed) and ``seek`` to skip already-read rows,
    * watermark tracking on an optional ``cursor`` column for incremental reads.
    """

    kind = "source"
    #: Whether re-reading starts from the beginning (files, tables). Streams
    #: yield only new items on every read, so offsets are not skipped for them.
    replayable = True

    def __init__(self, name: str | None = None, cursor: str | None = None):
        self.name = name or self.kind
        self.cursor = cursor
        self._offset = 0
        self._watermark: Any = None
        self._count = 0

    # -- lifecycle (no-ops by default) ----------------------------------
    def connect(self) -> None:  # noqa: B027 - optional hook
        """Open connections (optional)."""

    def close(self) -> None:  # noqa: B027 - optional hook
        """Release resources (optional)."""

    def __enter__(self) -> Source:
        self.connect()
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # -- reading --------------------------------------------------------
    @abstractmethod
    def _iter_batches(self, batch_size: int) -> Iterator[pd.DataFrame]:
        """Yield raw batches from the beginning of the source."""

    def read_batches(self, batch_size: int = 10_000) -> Iterator[pd.DataFrame]:
        """Yield batches after the current offset/watermark, updating both."""
        to_skip = self._offset if self.replayable else 0
        start_wm = self._watermark
        for batch in self._iter_batches(batch_size):
            if batch is None or batch.empty:
                continue
            n = len(batch)
            if to_skip >= n:
                to_skip -= n
                continue
            if to_skip:
                batch = batch.iloc[to_skip:]
                to_skip = 0
            self._offset += len(batch)
            if self.cursor:
                batch = filter_after_watermark(batch, self.cursor, start_wm)
                new_wm = max_cursor(batch, self.cursor)
                if new_wm is not None:
                    self._watermark = (
                        new_wm
                        if self._watermark is None
                        else max_cursor(
                            pd.DataFrame({self.cursor: [self._watermark, new_wm]}), self.cursor
                        )
                    )
            if batch.empty:
                continue
            self._count += len(batch)
            yield batch.reset_index(drop=True)

    def read(self, limit: int | None = None, batch_size: int = 10_000) -> pd.DataFrame:
        """Read everything (or up to ``limit`` rows) into a single DataFrame."""
        frames: list[pd.DataFrame] = []
        total = 0
        for batch in self.read_batches(batch_size):
            frames.append(batch)
            total += len(batch)
            if limit is not None and total >= limit:
                break
        if not frames:
            return pd.DataFrame()
        df = pd.concat(frames, ignore_index=True)
        return df.iloc[:limit] if limit is not None else df

    # -- state ----------------------------------------------------------
    def checkpoint(self) -> Checkpoint:
        return Checkpoint(
            source=self.name,
            offset=self._offset,
            watermark=self._watermark,
            record_count=self._count,
        )

    def seek(self, checkpoint: Checkpoint | None) -> None:
        if checkpoint is None:
            return
        self._watermark = checkpoint.watermark
        # With a cursor the watermark is authoritative; offsets are only used for
        # append-only sources without one.
        self._offset = 0 if self.cursor else int(checkpoint.offset or 0)
        self._count = int(checkpoint.record_count or 0)

    def describe(self) -> dict[str, Any]:
        return {"kind": self.kind, "name": self.name, "cursor": self.cursor}
