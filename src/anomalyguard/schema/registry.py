"""Schema model and a small file-based, versioned schema registry."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any

import yaml


class DataType(str, Enum):
    INTEGER = "integer"
    FLOAT = "float"
    STRING = "string"
    BOOLEAN = "boolean"
    DATETIME = "datetime"
    CATEGORICAL = "categorical"
    UNKNOWN = "unknown"

    @property
    def is_numeric(self) -> bool:
        return self in (DataType.INTEGER, DataType.FLOAT)


@dataclass
class Field:
    """A column definition with optional constraints."""

    name: str
    dtype: DataType = DataType.UNKNOWN
    nullable: bool = True
    unique: bool = False
    min: float | None = None
    max: float | None = None
    min_length: int | None = None
    max_length: int | None = None
    pattern: str | None = None
    allowed: list[Any] | None = None
    description: str | None = None

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {"type": self.dtype.value}
        if not self.nullable:
            out["nullable"] = False
        if self.unique:
            out["unique"] = True
        for key in ("min", "max", "min_length", "max_length", "pattern", "allowed", "description"):
            value = getattr(self, key)
            if value is not None:
                out[key] = value
        return out

    @classmethod
    def from_dict(cls, name: str, data: dict[str, Any] | str) -> Field:
        if isinstance(data, str):
            data = {"type": data}
        data = dict(data)
        dtype = DataType(str(data.pop("type", data.pop("dtype", "unknown"))).lower())
        allowed = data.pop("allowed", data.pop("enum", None))
        known = {
            "nullable",
            "unique",
            "min",
            "max",
            "min_length",
            "max_length",
            "pattern",
            "description",
        }
        unknown = set(data) - known
        if unknown:
            raise ValueError(f"Unknown keys for field '{name}': {sorted(unknown)}")
        return cls(name=name, dtype=dtype, allowed=allowed, **data)


@dataclass
class Schema:
    """A named, versioned collection of fields."""

    name: str
    fields: dict[str, Field] = field(default_factory=dict)
    version: int = 1
    primary_key: list[str] | None = None
    timestamp_column: str | None = None
    max_age_hours: float | None = None
    strict: bool = False
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def __getitem__(self, name: str) -> Field:
        return self.fields[name]

    def __contains__(self, name: object) -> bool:
        return name in self.fields

    @property
    def columns(self) -> list[str]:
        return list(self.fields)

    def numeric_columns(self) -> list[str]:
        return [n for n, f in self.fields.items() if f.dtype.is_numeric]

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {"name": self.name, "version": self.version}
        if self.primary_key:
            out["primary_key"] = list(self.primary_key)
        if self.timestamp_column:
            out["timestamp_column"] = self.timestamp_column
        if self.max_age_hours is not None:
            out["max_age_hours"] = self.max_age_hours
        if self.strict:
            out["strict"] = True
        out["fields"] = {n: f.to_dict() for n, f in self.fields.items()}
        return out

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Schema:
        fields_raw = data.get("fields") or {}
        if isinstance(fields_raw, list):  # allow a list of {name: ..., type: ...}
            fields_raw = {
                f["name"]: {k: v for k, v in f.items() if k != "name"} for f in fields_raw
            }
        pk = data.get("primary_key")
        if isinstance(pk, str):
            pk = [pk]
        return cls(
            name=data.get("name", "schema"),
            version=int(data.get("version", 1)),
            primary_key=pk,
            timestamp_column=data.get("timestamp_column"),
            max_age_hours=data.get("max_age_hours"),
            strict=bool(data.get("strict", False)),
            fields={n: Field.from_dict(n, spec) for n, spec in fields_raw.items()},
        )

    # --- serialisation -------------------------------------------------
    def to_yaml(self) -> str:
        return yaml.safe_dump(self.to_dict(), sort_keys=False, allow_unicode=False)

    def save(self, path: str | Path) -> Path:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.suffix.lower() == ".json":
            path.write_text(json.dumps(self.to_dict(), indent=2, default=str), encoding="utf-8")
        else:
            path.write_text(self.to_yaml(), encoding="utf-8")
        return path

    @classmethod
    def load(cls, path: str | Path) -> Schema:
        path = Path(path)
        text = path.read_text(encoding="utf-8")
        data = json.loads(text) if path.suffix.lower() == ".json" else yaml.safe_load(text)
        if not isinstance(data, dict):
            raise ValueError(f"Schema file {path} does not contain a mapping")
        return cls.from_dict(data)


class SchemaRegistry:
    """Stores schema versions as ``<root>/<name>/v<version>.yaml``."""

    def __init__(self, root: str | Path):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def _dir(self, name: str) -> Path:
        return self.root / name

    def versions(self, name: str) -> list[int]:
        d = self._dir(name)
        if not d.exists():
            return []
        out = []
        for p in d.glob("v*.yaml"):
            try:
                out.append(int(p.stem[1:]))
            except ValueError:
                continue
        return sorted(out)

    def names(self) -> list[str]:
        return sorted(p.name for p in self.root.iterdir() if p.is_dir())

    def register(self, schema: Schema) -> Schema:
        """Save ``schema`` as a new version (auto-incremented) and return it."""
        existing = self.versions(schema.name)
        schema.version = (existing[-1] + 1) if existing else max(schema.version, 1)
        schema.save(self._dir(schema.name) / f"v{schema.version}.yaml")
        return schema

    def get(self, name: str, version: int | None = None) -> Schema:
        versions = self.versions(name)
        if not versions:
            raise KeyError(f"No schema registered under '{name}'")
        v = versions[-1] if version is None else version
        path = self._dir(name) / f"v{v}.yaml"
        if not path.exists():
            raise KeyError(f"Schema '{name}' has no version {v}")
        return Schema.load(path)
