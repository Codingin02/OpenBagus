"""Unified local environment resolver for OpenBagus runtime.

Reads private values only from process environment or ignored local files.
Never writes secrets to Git-tracked files and exposes masked metadata for status reports.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any, Mapping


ENGINE_VERSION = "openbagus.core.runtime_env.v1"

ENV_FILES: tuple[Path, ...] = (
    Path("config/openbagus_runtime_local.env"),
    Path(".env"),
    Path(".env.local"),
)

LOCAL_JSON_FILES: tuple[Path, ...] = (
    Path("config/openbagus_runtime_local.json"),
    Path("config/openbagus_delivery_local.json"),
    Path("config/openbagus_local_flags.json"),
)

SECRET_HINT = re.compile(r"(?i)(key|token|secret|password|jid|phone|credential|topic)")


def _strip_quotes(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1]
    return value


def parse_env_text(text: str) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].strip()
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key):
            continue
        values[key] = _strip_quotes(value)
    return values


def _flatten_json(data: Mapping[str, Any]) -> dict[str, str]:
    values: dict[str, str] = {}

    def walk(item: Any) -> None:
        if isinstance(item, Mapping):
            for key, value in item.items():
                if isinstance(value, str) and re.fullmatch(r"[A-Z][A-Z0-9_]+", key):
                    values[key] = value
                elif isinstance(value, Mapping):
                    walk(value)

    walk(data)
    env_section = data.get("env") if isinstance(data, Mapping) else None
    if isinstance(env_section, Mapping):
        for key, value in env_section.items():
            if isinstance(key, str) and isinstance(value, str):
                values[key] = value
    return values


def _read_json(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _mask(value: str | None) -> str | None:
    if not value:
        return value
    if len(value) <= 8:
        return "***"
    return value[:3] + "***" + value[-3:]


def _source_record(name: str, path: Path | None = None, loaded: bool = False, keys: list[str] | None = None) -> dict[str, Any]:
    return {
        "source": name,
        "path": str(path) if path else None,
        "loaded": loaded,
        "key_count": len(keys or []),
        "keys": sorted(keys or []),
    }


class RuntimeEnv:
    """Resolve runtime env from process, local env files, local JSON, and caches."""

    def __init__(self, repo_root: Path) -> None:
        self.repo_root = repo_root
        self.layers: list[tuple[str, dict[str, str]]] = []
        self.source_status: list[dict[str, Any]] = []
        self._load()

    def _load(self) -> None:
        process = dict(os.environ)
        self.layers.append(("process_env", process))
        self.source_status.append(_source_record("process_env", loaded=True, keys=list(process.keys())))

        for rel_path in ENV_FILES:
            path = self.repo_root / rel_path
            if path.exists():
                values = parse_env_text(path.read_text(encoding="utf-8", errors="replace"))
                self.layers.append((str(rel_path), values))
                self.source_status.append(_source_record("env_file", rel_path, True, list(values.keys())))
            else:
                self.source_status.append(_source_record("env_file", rel_path, False, []))

        for rel_path in LOCAL_JSON_FILES:
            path = self.repo_root / rel_path
            if path.exists():
                values = _flatten_json(_read_json(path))
                self.layers.append((str(rel_path), values))
                self.source_status.append(_source_record("local_json", rel_path, True, list(values.keys())))
            else:
                self.source_status.append(_source_record("local_json", rel_path, False, []))

    def get(self, key: str, default: str | None = None) -> str | None:
        for source, layer in self.layers:
            value = layer.get(key)
            if value:
                return value
        return default

    def get_with_source(self, key: str, default: str | None = None) -> tuple[str | None, str]:
        for source, layer in self.layers:
            value = layer.get(key)
            if value:
                return value, source
        return default, "default" if default is not None else "missing"

    def subprocess_env(self) -> dict[str, str]:
        env = dict(os.environ)
        for _source, layer in reversed(self.layers[1:]):
            for key, value in layer.items():
                env.setdefault(key, value)
        for key, value in self.layers[0][1].items():
            env[key] = value
        return env

    def redacted_summary(self, keys: list[str]) -> dict[str, Any]:
        resolved = {}
        for key in keys:
            value, source = self.get_with_source(key)
            resolved[key] = {
                "present": bool(value),
                "source": source,
                "value": _mask(value) if SECRET_HINT.search(key) else value,
            }
        return {"engine_version": ENGINE_VERSION, "sources": self.source_status, "resolved": resolved}

def load_runtime_env(repo_root: Path) -> RuntimeEnv:
    return RuntimeEnv(repo_root)


def get_repo_root() -> Path:
    """Return the absolute path to the repository root directory."""
    return Path(__file__).resolve().parents[2]
