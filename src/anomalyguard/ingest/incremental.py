"""Persisted checkpoints and incremental (read-only-new-data) reading."""

from __future__ import annotations

import json
import os
import tempfile
from collections.abc import Iterator
from pathlib import Path

import pandas as pd

from anomalyguard.ingest.base import Checkpoint, Source


class CheckpointStore:
    """JSON file mapping ``source name -> checkpoint``. Writes are atomic."""

    def __init__(self, path: str | Path):
        self.path = Path(path)

    def _load_all(self) -> dict[str, dict]:
        if not self.path.exists():
            return {}
        try:
            return json.loads(self.path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {}

    def get(self, name: str) -> Checkpoint | None:
        data = self._load_all().get(name)
        return Checkpoint.from_dict(data) if data else None

    def save(self, checkpoint: Checkpoint) -> None:
        data = self._load_all()
        data[checkpoint.source] = checkpoint.to_dict()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=self.path.parent, suffix=".tmp")
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2, default=str)
        os.replace(tmp, self.path)

    def reset(self, name: str) -> None:
        data = self._load_all()
        if data.pop(name, None) is not None:
            self.path.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")


class IncrementalReader:
    """Resume a source from its last checkpoint and persist progress after
    every batch, so each call only returns data not seen before."""

    def __init__(self, source: Source, store: CheckpointStore):
        self.source = source
        self.store = store

    def read_new_batches(self, batch_size: int = 10_000) -> Iterator[pd.DataFrame]:
        self.source.seek(self.store.get(self.source.name))
        for batch in self.source.read_batches(batch_size):
            yield batch
            self.store.save(self.source.checkpoint())
        # Persist even when nothing new arrived (updates the timestamp).
        self.store.save(self.source.checkpoint())

    def read_new(self, batch_size: int = 10_000) -> pd.DataFrame:
        frames = list(self.read_new_batches(batch_size))
        return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
