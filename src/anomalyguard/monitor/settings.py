"""Server settings, read from environment variables (see the README configuration table)."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

DEFAULT_PIPELINE_DIRS = ("pipelines", "examples")
DEFAULT_MAX_UPLOAD_MB = 100.0


def _split(value: str | None) -> list[str]:
    if not value:
        return []
    parts = value.replace(os.pathsep if os.pathsep != ":" else ",", ",").split(",")
    return [p.strip() for p in parts if p.strip()]


@dataclass
class ServerSettings:
    """Runtime options for ``anomalyguard serve`` and :func:`create_app`.

    ``api_key``: when set, every ``/api/*`` request must send it in the
    ``X-API-Key`` header (or ``Authorization: Bearer <key>``).
    ``cors_origins``: browser origins allowed to call the API cross-site.
    ``max_upload_mb``: largest accepted upload.
    ``pipeline_dirs``: folders scanned for pipeline YAML files; the first one is
    where pipelines created in the UI are written.
    ``workers``: background job threads (analyses and pipeline runs).
    """

    api_key: str | None = None
    cors_origins: list[str] = field(default_factory=list)
    max_upload_mb: float = DEFAULT_MAX_UPLOAD_MB
    pipeline_dirs: list[Path] = field(
        default_factory=lambda: [Path(d) for d in DEFAULT_PIPELINE_DIRS]
    )
    workers: int = 2

    @property
    def max_upload_bytes(self) -> int:
        return int(self.max_upload_mb * 1024 * 1024)

    @property
    def auth_enabled(self) -> bool:
        return bool(self.api_key)

    @classmethod
    def from_env(cls, env: dict[str, str] | None = None) -> ServerSettings:
        env = dict(os.environ if env is None else env)
        dirs = _split(env.get("ANOMALYGUARD_PIPELINE_DIRS")) or list(DEFAULT_PIPELINE_DIRS)
        try:
            max_mb = float(env.get("ANOMALYGUARD_MAX_UPLOAD_MB") or DEFAULT_MAX_UPLOAD_MB)
        except ValueError:
            max_mb = DEFAULT_MAX_UPLOAD_MB
        try:
            workers = max(1, int(env.get("ANOMALYGUARD_WORKERS") or 2))
        except ValueError:
            workers = 2
        return cls(
            api_key=(env.get("ANOMALYGUARD_API_KEY") or "").strip() or None,
            cors_origins=_split(env.get("ANOMALYGUARD_CORS_ORIGINS")),
            max_upload_mb=max_mb,
            pipeline_dirs=[Path(d) for d in dirs],
            workers=workers,
        )

    def describe(self) -> dict[str, object]:
        """Settings safe to show in the UI (never the key itself)."""
        return {
            "auth_enabled": self.auth_enabled,
            "cors_origins": self.cors_origins,
            "max_upload_mb": self.max_upload_mb,
            "pipeline_dirs": [str(d) for d in self.pipeline_dirs],
            "workers": self.workers,
        }
