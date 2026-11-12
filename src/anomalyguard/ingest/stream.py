"""In-memory and generator based sources (useful for streams and tests)."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Iterator
from typing import Any

import pandas as pd

from anomalyguard.ingest.base import Source


class StreamSource(Source):
    """Wrap a DataFrame, an iterable of records/DataFrames, or a callable that
    returns such an iterable (re-invoked on every read, e.g. a function that
    drains a queue). Every read consumes what the stream yields now; offsets
    are tracked for monitoring but never skipped. Use ``cursor`` to drop
    records at or below the last watermark."""

    kind = "stream"
    replayable = False

    def __init__(
        self,
        data: pd.DataFrame | Iterable[Any] | Callable[[], Iterable[Any]],
        name: str | None = None,
        cursor: str | None = None,
    ):
        super().__init__(name or "stream", cursor)
        self.data = data

    def _iter_batches(self, batch_size: int) -> Iterator[pd.DataFrame]:
        data = (
            self.data()
            if callable(self.data) and not isinstance(self.data, pd.DataFrame)
            else self.data
        )
        if isinstance(data, pd.DataFrame):
            for i in range(0, len(data), batch_size):
                yield data.iloc[i : i + batch_size]
            return
        buf: list[dict[str, Any]] = []
        for item in data:
            if isinstance(item, pd.DataFrame):
                if buf:
                    yield pd.DataFrame.from_records(buf)
                    buf = []
                yield item
                continue
            if isinstance(item, list):
                buf.extend(item)
            else:
                buf.append(dict(item))
            while len(buf) >= batch_size:
                yield pd.DataFrame.from_records(buf[:batch_size])
                buf = buf[batch_size:]
        if buf:
            yield pd.DataFrame.from_records(buf)
