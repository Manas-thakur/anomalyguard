"""Declarative pipeline configuration (YAML)."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from anomalyguard.monitor.store import DEFAULT_DB

_ENV = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)(?::-([^}]*))?\}")
TOP_LEVEL_KEYS = {
    "name",
    "description",
    "source",
    "schema",
    "detectors",
    "detection",
    "remediation",
    "review",
    "alerts",
    "sink",
    "monitor",
    "state",
    "schedule",
}


class ConfigError(ValueError):
    """Invalid pipeline configuration."""


def expand_env(text: str) -> str:
    """Replace ``${VAR}`` / ``${VAR:-default}`` with environment values."""

    def repl(m: re.Match) -> str:
        val = os.environ.get(m.group(1))
        if val is None:
            return m.group(2) if m.group(2) is not None else ""
        return val

    return _ENV.sub(repl, text)


@dataclass
class PipelineConfig:
    """A pipeline: source -> schema -> detectors -> remediation -> alerts -> sink.

    Data paths (``source.path``, ``schema.path``, ``sink.*path``) and any
    explicitly configured state paths are resolved relative to ``base_dir``
    (the YAML file's folder). Runtime state defaults live in
    ``.anomalyguard/`` under the current working directory so ``anomalyguard
    serve`` finds them without extra flags.
    """

    name: str
    source: dict[str, Any]
    description: str = ""
    schema: dict[str, Any] = field(default_factory=lambda: {"infer": True})
    detectors: list[Any] = field(default_factory=lambda: ["mad", "iforest"])
    detection: dict[str, Any] = field(default_factory=dict)
    remediation: dict[str, Any] | None = field(default_factory=dict)
    review: dict[str, Any] = field(default_factory=lambda: {"enabled": True})
    alerts: dict[str, Any] = field(default_factory=dict)
    sink: dict[str, Any] | None = None
    monitor: dict[str, Any] = field(default_factory=dict)
    state: dict[str, Any] = field(default_factory=dict)
    schedule: dict[str, Any] | None = None
    base_dir: Path = field(default_factory=Path.cwd)

    # -- paths ----------------------------------------------------------
    def resolve(self, path: str | Path | None) -> Path | None:
        if path is None:
            return None
        p = Path(str(path))
        return p if p.is_absolute() else Path(os.path.normpath(self.base_dir / p))

    @property
    def db_path(self) -> Path:
        explicit = self.monitor.get("db")
        return self.resolve(explicit) if explicit else Path(DEFAULT_DB)

    @property
    def review_db_path(self) -> Path:
        explicit = self.review.get("db")
        return self.resolve(explicit) if explicit else self.db_path

    @property
    def state_dir(self) -> Path:
        explicit = self.state.get("dir")
        return self.resolve(explicit) if explicit else Path(".anomalyguard") / "state"

    @property
    def interval_seconds(self) -> float | None:
        if not self.schedule:
            return None
        if "interval_seconds" in self.schedule:
            return _positive_seconds(self.schedule["interval_seconds"], "schedule.interval_seconds")
        if "every" in self.schedule:
            return _positive_seconds(self.schedule["every"], "schedule.every")
        return None

    # -- loading --------------------------------------------------------
    @classmethod
    def from_dict(cls, data: dict[str, Any], base_dir: str | Path | None = None) -> PipelineConfig:
        if not isinstance(data, dict):
            raise ConfigError("Pipeline config must be a mapping")
        unknown = set(data) - TOP_LEVEL_KEYS
        if unknown:
            raise ConfigError(
                f"Unknown top-level keys: {sorted(unknown)}. Allowed: {sorted(TOP_LEVEL_KEYS)}"
            )
        if not data.get("name"):
            raise ConfigError("Pipeline config needs a 'name'")
        if not isinstance(data.get("source"), dict):
            raise ConfigError(
                "Pipeline config needs a 'source' mapping (e.g. {type: csv, path: data.csv})"
            )
        kwargs = {k: v for k, v in data.items() if k in TOP_LEVEL_KEYS}
        if kwargs.get("schema") is None:
            kwargs["schema"] = {"infer": True}
        if isinstance(kwargs.get("schema"), str):
            kwargs["schema"] = {"path": kwargs["schema"]}
        if kwargs.get("remediation") is False:
            kwargs["remediation"] = None
        elif kwargs.get("remediation") is True:
            kwargs["remediation"] = {}
        if isinstance(kwargs.get("detectors"), str):
            kwargs["detectors"] = [d.strip() for d in kwargs["detectors"].split(",")]
        for key in ("detection", "review", "alerts", "monitor", "state"):
            if kwargs.get(key) is None:
                kwargs.pop(key, None)
        cfg = cls(**kwargs, base_dir=Path(base_dir) if base_dir else Path.cwd())
        cfg.validate()
        return cfg

    @classmethod
    def from_yaml(cls, text: str, base_dir: str | Path | None = None) -> PipelineConfig:
        try:
            data = yaml.safe_load(expand_env(text))
        except yaml.YAMLError as exc:
            raise ConfigError(f"Invalid YAML: {_yaml_error(exc)}") from exc
        return cls.from_dict(data, base_dir)

    @classmethod
    def load(cls, path: str | Path) -> PipelineConfig:
        """Load and validate a pipeline file; errors name the file."""
        path = Path(path)
        if not path.exists():
            raise ConfigError(f"Pipeline file not found: {path}")
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            raise ConfigError(f"{path}: cannot read file: {exc}") from exc
        try:
            return cls.from_yaml(text, base_dir=path.resolve().parent)
        except ConfigError as exc:
            raise ConfigError(f"{path}: {exc}") from exc

    def validate(self) -> None:
        from anomalyguard.alert.rules import AlertRule
        from anomalyguard.detect.registry import build_detector
        from anomalyguard.remediate.pipeline import RemediationPolicy

        if not self.detectors:
            raise ConfigError("At least one detector is required")
        for spec in self.detectors:
            try:
                build_detector(spec)
            except (KeyError, ValueError, TypeError) as exc:
                msg = exc.args[0] if isinstance(exc, KeyError) and exc.args else exc
                raise ConfigError(f"Bad detector {spec!r}: {msg}") from exc
        if self.schedule is not None:
            if not isinstance(self.schedule, dict):
                raise ConfigError(
                    "schedule must be a mapping, e.g. {every: 5m} or {interval_seconds: 300}"
                )
            self.interval_seconds  # noqa: B018 - parses (and so validates) the duration
        if self.remediation is not None:
            rem = {k: v for k, v in self.remediation.items() if k not in ("enabled", "llm")}
            try:
                RemediationPolicy.from_dict(rem)
            except (ValueError, TypeError) as exc:
                raise ConfigError(f"Bad remediation config: {exc}") from exc
        for rule in self.alerts.get("rules", []) or []:
            try:
                AlertRule.from_dict(rule)
            except (ValueError, TypeError) as exc:
                raise ConfigError(f"Bad alert rule {rule!r}: {exc}") from exc
        combine = self.detection.get("combine", "any")
        if combine not in ("any", "vote", "all"):
            raise ConfigError("detection.combine must be any, vote or all")
        ref = self.detection.get("reference_rows", 0)
        if isinstance(ref, bool) or not isinstance(ref, int) or ref < 0:
            raise ConfigError(f"detection.reference_rows must be a whole number >= 0 (got {ref!r})")


def _yaml_error(exc: yaml.YAMLError) -> str:
    """One-line description of a YAML error with its line and column."""
    mark = getattr(exc, "problem_mark", None)
    problem = getattr(exc, "problem", None) or str(exc).splitlines()[0]
    if mark is not None:
        return f"{problem} (line {mark.line + 1}, column {mark.column + 1})"
    return str(problem)


def _positive_seconds(value: Any, field_name: str) -> float:
    try:
        if isinstance(value, bool):
            raise ConfigError("not a duration")
        seconds = float(value) if isinstance(value, (int, float)) else parse_duration(str(value))
    except (ConfigError, ValueError) as exc:
        raise ConfigError(
            f"{field_name}: invalid duration {value!r} (use e.g. 30s, 5m, 2h, 1d)"
        ) from exc
    if not seconds > 0:
        raise ConfigError(f"{field_name}: duration must be positive, got {value!r}")
    return seconds


def parse_duration(text: str) -> float:
    """``"30s"``, ``"5m"``, ``"2h"``, ``"1d"`` or plain seconds."""
    m = re.fullmatch(r"\s*(\d+(?:\.\d+)?)\s*([smhd]?)\s*", text)
    if not m:
        raise ConfigError(f"Invalid duration '{text}' (use e.g. 30s, 5m, 2h, 1d)")
    value, unit = float(m.group(1)), m.group(2) or "s"
    return value * {"s": 1, "m": 60, "h": 3600, "d": 86400}[unit]
