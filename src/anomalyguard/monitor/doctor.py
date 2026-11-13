"""Environment diagnostics shared by ``anomalyguard doctor`` and the Settings page."""

from __future__ import annotations

import importlib.util
import os
import platform
import sqlite3
import sys
from contextlib import closing
from pathlib import Path
from typing import Any

from anomalyguard import __version__

EXTRAS = {
    "server": ["fastapi", "uvicorn", "multipart"],
    "parquet": ["pyarrow"],
    "sql": ["sqlalchemy"],
}

# environment variables the notifiers, LLM suggester and server read by default
ENV_VARS = {
    "ANOMALYGUARD_API_KEY": "API key required by the dashboard/API",
    "ANOMALYGUARD_CORS_ORIGINS": "browser origins allowed to call the API",
    "ANOMALYGUARD_MAX_UPLOAD_MB": "upload size limit in MB",
    "ANOMALYGUARD_PIPELINE_DIRS": "folders scanned for pipeline YAML",
    "ANOMALYGUARD_WORKERS": "background job threads",
    "SLACK_WEBHOOK_URL": "Slack notifier (examples use ${SLACK_WEBHOOK_URL})",
    "ANOMALYGUARD_SMTP_PASSWORD": "email notifier password",
    "OPENAI_API_KEY": "LLM suggestions with provider: openai",
}
SECRET_VARS = {
    "ANOMALYGUARD_API_KEY",
    "SLACK_WEBHOOK_URL",
    "ANOMALYGUARD_SMTP_PASSWORD",
    "OPENAI_API_KEY",
}


REPO_URL = "https://github.com/Manas-thakur/anomalyguard"


def install_command(extra: str | None = None, ref: str | None = None) -> str:
    """pip command that installs this release from GitHub (the package is not on PyPI).

    ``ref`` defaults to this version's tag; pass ``"main"`` for the latest code.
    """
    name = f"anomalyguard[{extra}]" if extra else "anomalyguard"
    return f'pip install "{name} @ git+{REPO_URL}@{ref or "v" + __version__}"'


def _installed(module: str) -> bool:
    return importlib.util.find_spec(module) is not None


def extras_status() -> dict[str, dict[str, Any]]:
    out = {}
    for extra, modules in EXTRAS.items():
        missing = [m for m in modules if not _installed(m)]
        out[extra] = {
            "installed": not missing,
            "missing": missing,
            "install": install_command(extra),
        }
    return out


def env_status(env: dict[str, str] | None = None) -> list[dict[str, Any]]:
    env = dict(os.environ if env is None else env)
    rows = []
    for name, purpose in ENV_VARS.items():
        value = env.get(name)
        shown = None
        if value and name not in SECRET_VARS:
            shown = value
        rows.append({"name": name, "set": bool(value), "value": shown, "purpose": purpose})
    return rows


def state_status(db_path: str | Path) -> dict[str, Any]:
    db = Path(db_path)
    state = db.parent
    info: dict[str, Any] = {
        "state_dir": str(state.resolve()),
        "db": str(db.resolve()),
        "exists": state.exists(),
        "writable": False,
        "db_exists": db.exists(),
        "runs": None,
        "review_pending": None,
        "uploads": 0,
    }
    try:
        state.mkdir(parents=True, exist_ok=True)
        probe = state / ".doctor-probe"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
        info["writable"] = True
    except OSError as exc:
        info["error"] = str(exc)
    if db.exists():
        try:
            with closing(sqlite3.connect(db)) as conn:
                tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master").fetchall()}
                if "runs" in tables:
                    info["runs"] = conn.execute("SELECT COUNT(*) FROM runs").fetchone()[0]
                if "review_items" in tables:
                    info["review_pending"] = conn.execute(
                        "SELECT COUNT(*) FROM review_items WHERE status = 'pending'"
                    ).fetchone()[0]
        except sqlite3.Error as exc:
            info["error"] = f"database: {exc}"
    uploads = state / "uploads"
    if uploads.is_dir():
        info["uploads"] = sum(1 for p in uploads.iterdir() if p.is_dir())
    return info


def notifier_status(pipeline_files: list[Path]) -> list[dict[str, Any]]:
    """Notifiers configured in each pipeline and whether their secrets resolve."""
    from anomalyguard.pipeline.config import PipelineConfig

    out = []
    for path in pipeline_files:
        try:
            cfg = PipelineConfig.load(path)
        except Exception as exc:
            out.append({"pipeline": path.name, "error": str(exc), "notifiers": []})
            continue
        notifiers = []
        for n in (cfg.alerts or {}).get("notifiers", []) or []:
            if not isinstance(n, dict):
                n = {"type": str(n)}
            kind = str(n.get("type", "console"))
            ok, detail = True, ""
            if kind in ("slack", "webhook"):
                url = n.get("url") or (os.environ.get(n["url_env"], "") if n.get("url_env") else "")
                ok = bool(url)
                detail = (
                    "webhook URL set"
                    if ok
                    else "webhook URL is empty (environment variable not set?)"
                )
            elif kind == "email":
                env_name = n.get("password_env", "ANOMALYGUARD_SMTP_PASSWORD")
                ok = bool(os.environ.get(env_name)) or not n.get("username")
                detail = f"{env_name} {'set' if os.environ.get(env_name) else 'not set'}"
            elif kind in ("file", "jsonl"):
                detail = str(n.get("path", ""))
            notifiers.append(
                {
                    "type": kind,
                    "min_severity": n.get("min_severity", n.get("severity", "info")),
                    "ok": ok,
                    "detail": detail,
                }
            )
        out.append({"pipeline": cfg.name, "file": str(path), "notifiers": notifiers})
    return out


def collect(db_path: str | Path, pipeline_dirs: list[Path] | None = None) -> dict[str, Any]:
    from anomalyguard.monitor.catalog import PipelineCatalog
    from anomalyguard.monitor.store import MetricsStore

    dirs = [Path(d) for d in (pipeline_dirs or [Path("pipelines"), Path("examples")])]
    files: list[Path] = []
    pipelines: list[dict[str, Any]] = []
    try:
        store = MetricsStore(db_path) if Path(db_path).exists() else None
    except Exception:  # pragma: no cover - an unreadable database is reported by state_status
        store = None
    catalog = PipelineCatalog(dirs, store, Path(db_path).parent)
    try:
        files = catalog.files()
    except Exception as exc:  # pragma: no cover - diagnostics must not crash
        pipelines.append({"name": None, "file": "", "valid": False, "error": str(exc)})
    for p in files:
        # one bad file must not hide the others (describe() reports, never raises)
        try:
            d = catalog.describe(p)
        except Exception as exc:  # pragma: no cover - defensive
            d = {"name": None, "valid": False, "error": f"{type(exc).__name__}: {exc}"}
        pipelines.append(
            {
                "name": d.get("name"),
                "file": str(p),
                "valid": d["valid"],
                "error": d["error"],
                "warnings": d.get("warnings") or [],
            }
        )
    return {
        "version": __version__,
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "executable": sys.executable,
        "state": state_status(db_path),
        "extras": extras_status(),
        "env": env_status(),
        "pipeline_dirs": [{"path": str(d), "exists": d.is_dir()} for d in dirs],
        "pipelines": pipelines,
        "notifiers": notifier_status(files),
    }
