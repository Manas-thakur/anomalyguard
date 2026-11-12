"""Discover, validate, create and run pipeline YAML files for the web UI."""

from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Any

import yaml

from anomalyguard.monitor.store import MetricsStore
from anomalyguard.pipeline.config import ConfigError, PipelineConfig, expand_env
from anomalyguard.pipeline.templates import TEMPLATE_DEFAULTS, TEMPLATES, render_template

NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")
YAML_SUFFIXES = (".yaml", ".yml")


def pipeline_id(path: Path) -> str:
    return hashlib.sha1(str(path.resolve()).encode("utf-8")).hexdigest()[:12]


def looks_like_pipeline(path: Path) -> bool:
    """A YAML mapping with ``name`` and ``source`` (schema files have ``fields``)."""
    try:
        data = yaml.safe_load(expand_env(path.read_text(encoding="utf-8")))
    except (OSError, UnicodeDecodeError, yaml.YAMLError):
        return False
    return isinstance(data, dict) and "source" in data and "name" in data


class PipelineCatalog:
    def __init__(self, dirs: list[Path], store: MetricsStore | None, state_dir: Path):
        self.dirs = [Path(d) for d in dirs]
        self.store = store
        self.state_dir = Path(state_dir)

    @property
    def write_dir(self) -> Path:
        return self.dirs[0] if self.dirs else Path("pipelines")

    def files(self) -> list[Path]:
        out: list[Path] = []
        seen: set[Path] = set()
        for d in self.dirs:
            if not d.is_dir():
                continue
            for p in sorted(d.iterdir()):
                rp = p.resolve()
                if p.suffix.lower() in YAML_SUFFIXES and p.is_file() and rp not in seen:
                    seen.add(rp)
                    if looks_like_pipeline(p):
                        out.append(p)
        return out

    def find(self, pid: str) -> Path:
        for p in self.files():
            if pipeline_id(p) == pid:
                return p
        raise KeyError(f"Pipeline {pid} not found")

    def describe(self, path: Path, with_yaml: bool = False) -> dict[str, Any]:
        info: dict[str, Any] = {
            "id": pipeline_id(path),
            "file": path.name,
            "path": str(path),
            "dir": str(path.parent),
            "valid": True,
            "error": None,
        }
        text = path.read_text(encoding="utf-8")
        if with_yaml:
            info["yaml"] = text
        try:
            cfg = PipelineConfig.load(path)
        except (ConfigError, OSError) as exc:
            info.update(valid=False, error=str(exc))
            try:
                data = yaml.safe_load(text) or {}
                info["name"] = data.get("name") if isinstance(data, dict) else None
            except yaml.YAMLError:
                info["name"] = None
            return info
        info.update(
            name=cfg.name,
            description=cfg.description,
            source=_source_label(cfg),
            detectors=[_det_label(d) for d in cfg.detectors],
            remediation=cfg.remediation is not None,
            schedule=cfg.schedule,
            interval_seconds=cfg.interval_seconds,
            notifiers=[n.get("type", "console") for n in (cfg.alerts or {}).get("notifiers", [])],
        )
        if self.store is not None:
            last = self.store.runs(limit=1, pipeline=cfg.name)
            info["last_run"] = last[0] if last else None
            info["runs"] = self.store.count_runs(pipeline=cfg.name)
        return info

    def list(self) -> list[dict[str, Any]]:
        return [self.describe(p) for p in self.files()]

    def load_for_server(self, path: Path, db_path: Path) -> PipelineConfig:
        """Load a pipeline so a UI-triggered run records into the server's database."""
        cfg = PipelineConfig.load(path)
        if not cfg.monitor.get("db"):
            cfg.monitor = {**cfg.monitor, "db": str(Path(db_path).resolve())}
        if not cfg.state.get("dir"):
            cfg.state = {**cfg.state, "dir": str((self.state_dir / "state").resolve())}
        return cfg

    @staticmethod
    def validate_text(text: str, base_dir: Path | None = None) -> dict[str, Any]:
        try:
            cfg = PipelineConfig.from_yaml(text, base_dir=base_dir)
        except ConfigError as exc:
            return {"valid": False, "error": str(exc)}
        except Exception as exc:  # anything else yaml/config related
            return {"valid": False, "error": f"{type(exc).__name__}: {exc}"}
        warnings = []
        src = cfg.source.get("path")
        if src and "://" not in str(src):
            resolved = cfg.resolve(src)
            if resolved is not None and not resolved.exists():
                warnings.append(f"source file not found: {resolved}")
        return {"valid": True, "error": None, "name": cfg.name, "warnings": warnings}

    def create(
        self,
        name: str,
        template: str = "csv_quality",
        source: str | None = None,
        overwrite: bool = False,
        yaml_text: str | None = None,
        **values: str | None,
    ) -> Path:
        if not NAME_RE.match(name or ""):
            raise ValueError(
                "Name must start with a letter or digit and use only letters, digits, '.', '_' or '-'"
            )
        if template not in TEMPLATES and yaml_text is None:
            raise ValueError(f"Unknown template '{template}'. Available: {', '.join(TEMPLATES)}")
        out_dir = self.write_dir
        out_dir.mkdir(parents=True, exist_ok=True)
        path = out_dir / f"{name}.yaml"
        if path.exists() and not overwrite:
            raise FileExistsError(f"{path} already exists")
        if yaml_text is None:
            yaml_text = render_template(
                template,
                name=name,
                filename=path.name,
                source=source,
                **{k: v for k, v in values.items() if v},
            )
        check = self.validate_text(yaml_text, base_dir=out_dir.resolve())
        if not check["valid"]:
            raise ValueError(check["error"])
        path.write_text(yaml_text, encoding="utf-8")
        return path

    def update(self, pid: str, yaml_text: str) -> Path:
        path = self.find(pid)
        check = self.validate_text(yaml_text, base_dir=path.resolve().parent)
        if not check["valid"]:
            raise ValueError(check["error"])
        path.write_text(yaml_text, encoding="utf-8")
        return path


def templates() -> list[dict[str, Any]]:
    descriptions = {
        "csv_quality": "Scan a CSV file: robust outliers, Isolation Forest, safe fixes, alerts.",
        "timeseries_monitor": "Monitor one value column over time: seasonal, CUSUM, rolling z-score.",
        "database_quality": "Incremental checks on a SQL table, report only.",
    }
    fields = {
        "csv_quality": ["source", "group_by"],
        "timeseries_monitor": ["source", "value_column"],
        "database_quality": ["source", "table", "cursor"],
    }
    return [
        {
            "name": t,
            "description": descriptions.get(t, ""),
            "fields": fields.get(t, ["source"]),
            "defaults": TEMPLATE_DEFAULTS.get(t, {}),
        }
        for t in TEMPLATES
    ]


def _source_label(cfg: PipelineConfig) -> str:
    src = cfg.source
    return str(src.get("path") or src.get("url") or src.get("table") or src.get("type") or "")


def _det_label(spec: Any) -> str:
    if isinstance(spec, str):
        return spec
    if isinstance(spec, dict):
        m = str(spec.get("method") or spec.get("type") or "?")
        return f"{m} by {spec['group_by']}" if spec.get("group_by") else m
    return type(spec).__name__
