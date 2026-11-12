"""A small interval scheduler (no cron dependency)."""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable

from anomalyguard.pipeline.config import PipelineConfig
from anomalyguard.pipeline.executor import PipelineExecutor, PipelineResult

log = logging.getLogger("anomalyguard.scheduler")


class Scheduler:
    """Run each pipeline every ``interval`` seconds in a single thread.

    Runs never overlap: if a run takes longer than its interval, the next one
    starts immediately after. ``max_runs`` (per pipeline) and ``stop()`` end
    the loop; Ctrl+C stops it cleanly from the CLI.
    """

    def __init__(
        self,
        pipelines: list[tuple[PipelineConfig, float]],
        max_runs: int | None = None,
        on_result: Callable[[PipelineResult], None] | None = None,
        sleep: Callable[[float], None] | None = None,
        clock: Callable[[], float] = time.monotonic,
    ):
        if not pipelines:
            raise ValueError("Scheduler needs at least one pipeline")
        for _, interval in pipelines:
            if interval <= 0:
                raise ValueError("interval must be positive")
        self.pipelines = pipelines
        self.max_runs = max_runs
        self.on_result = on_result
        self._stop = threading.Event()
        self._sleep = sleep or (lambda s: self._stop.wait(s))
        self.clock = clock
        self.results: list[PipelineResult] = []

    def stop(self) -> None:
        self._stop.set()

    def run(self) -> list[PipelineResult]:
        now = self.clock()
        next_due = [now for _ in self.pipelines]
        counts = [0 for _ in self.pipelines]
        executors = [PipelineExecutor(cfg) for cfg, _ in self.pipelines]
        while not self._stop.is_set():
            active = [
                i
                for i in range(len(self.pipelines))
                if self.max_runs is None or counts[i] < self.max_runs
            ]
            if not active:
                break
            i = min(active, key=lambda k: next_due[k])
            wait = next_due[i] - self.clock()
            if wait > 0:
                self._sleep(wait)
                if self._stop.is_set():
                    break
            cfg, interval = self.pipelines[i]
            log.info("running pipeline %s (run %d)", cfg.name, counts[i] + 1)
            result = executors[i].run()
            self.results.append(result)
            counts[i] += 1
            if self.on_result:
                self.on_result(result)
            next_due[i] = max(next_due[i] + interval, self.clock())
        return self.results
