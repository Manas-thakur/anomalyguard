"""Persisted per-pipeline state (run counters, last status, checkpoints)."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any

from anomalyguard.ingest.incremental import CheckpointStore


class PipelineState:
    """Stores ``pipelines.json`` (run history summary) and ``checkpoints.json``
    (source positions for incremental reads) in ``state_dir``."""

    def __init__(self, state_dir: str | Path):
        self.dir = Path(state_dir)
        self.path = self.dir / "pipelines.json"
        self.checkpoints = CheckpointStore(self.dir / "checkpoints.json")

    def _load(self) -> dict[str, Any]:
        if not self.path.exists():
            return {}
        try:
            return json.loads(self.path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {}

    def get(self, pipeline: str) -> dict[str, Any]:
        return self._load().get(pipeline, {})

    def update(self, pipeline: str, **values: Any) -> dict[str, Any]:
        data = self._load()
        entry = data.get(pipeline, {})
        entry.update(values)
        data[pipeline] = entry
        self.dir.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=self.dir, suffix=".tmp")
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2, default=str)
        os.replace(tmp, self.path)
        return entry

    def reset(self, pipeline: str) -> None:
        data = self._load()
        data.pop(pipeline, None)
        if self.path.exists():
            self.path.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")
        self.checkpoints.reset(pipeline)
        # reference rows kept for incremental detection
        (self.dir / f"{pipeline}.reference.jsonl").unlink(missing_ok=True)
