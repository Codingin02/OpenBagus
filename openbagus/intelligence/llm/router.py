"""Optional OpenRouter LLM jury / critic router for OpenBagus.

Never owns quant facts. Used only for prose criticism, summarization, and contradiction checks.
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Mapping

from openbagus.core.guards import scan_text
from openbagus.core.env import load_runtime_env
from openbagus.intelligence.llm.prompts import ROLE_PROMPTS, SYSTEM_PROMPT, build_user_prompt


ENGINE_VERSION = "openbagus.intelligence.llm.router.v1"
CONFIG_PATHS = (
    Path("config/openbagus_llm_jury_free.local.json"),
    Path("config/openbagus_llm_jury_free.example.json"),
)


def _load_config(repo_root: Path) -> dict[str, Any]:
    for rel_path in CONFIG_PATHS:
        path = repo_root / rel_path
        if path.exists():
            data = json.loads(path.read_text(encoding="utf-8"))
            data["_config_path"] = str(rel_path)
            return data
    return {"roles": {}, "_config_path": str(CONFIG_PATHS[1])}


def _short_error(exc: BaseException) -> str:
    if isinstance(exc, urllib.error.HTTPError):
        return f"HTTP {exc.code}: {exc.reason}"
    if isinstance(exc, urllib.error.URLError):
        return f"URL error: {exc.reason}"
    return str(exc)[:180]


def _is_free_model(model_id: str, role_cfg: Mapping[str, Any]) -> bool:
    return ":free" in model_id or bool(role_cfg.get("free", False))


class LLMJuryRouter:
    """Runs only optional model critique. It never owns quant facts."""

    def __init__(self, repo_root: Path) -> None:
        self.repo_root = repo_root
        self.config = _load_config(repo_root)
        self.runtime_env = load_runtime_env(repo_root)

    def run(self, facts: Mapping[str, Any]) -> dict[str, Any]:
        enabled_flag = (
            self.runtime_env.get("OPENBAGUS_LLM_JURY_ENABLED")
            or self.runtime_env.get("OBF_LLM_JURY_ENABLED", "false")
            or "false"
        ).lower()
        api_key = self.runtime_env.get("OPENROUTER_API_KEY")
        if not api_key:
            return {
                "engine_version": ENGINE_VERSION,
                "status": "LLM_JURY_DISABLED_NO_KEY",
                "enabled": False,
                "reason": "OPENROUTER_API_KEY is not set; deterministic renderer used.",
                "model_config_file": self.config.get("_config_path"),
            }
        if enabled_flag not in {"1", "true", "yes", "on"}:
            return {
                "engine_version": ENGINE_VERSION,
                "status": "LLM_JURY_DISABLED_OPTIONAL",
                "enabled": False,
                "reason": "OPENBAGUS_LLM_JURY_ENABLED is not enabled; deterministic renderer used.",
                "model_config_file": self.config.get("_config_path"),
                "api_key_logged": False,
            }
        roles = self.config.get("roles", {})
        selected = list(roles.items())[:5]
        free_roles = [(role, cfg) for role, cfg in selected if _is_free_model(str(cfg.get("model", "")), cfg)]
        if len(free_roles) < 3:
            return {
                "engine_version": ENGINE_VERSION,
                "status": "LLM_JURY_DISABLED_NO_MIN_FREE_MODELS",
                "enabled": False,
                "reason": "At least 3 free OpenRouter models are required.",
                "model_config_file": self.config.get("_config_path"),
            }

        facts_json = json.dumps(facts, ensure_ascii=True, sort_keys=True)[:12000]
        results = []
        for role, cfg in free_roles:
            result = self._call_role(api_key, role, cfg, facts_json)
            results.append(result)
            time.sleep(0.15)
        return {
            "engine_version": ENGINE_VERSION,
            "status": "LLM_JURY_COMPLETED_WITH_PARTIALS",
            "enabled": True,
            "model_config_file": self.config.get("_config_path"),
            "results": results,
            "final_policy": "Conservative deterministic output is kept if jury is unavailable or disagrees.",
            "api_key_logged": False,
        }

    def _call_role(self, api_key: str, role: str, cfg: Mapping[str, Any], facts_json: str) -> dict[str, Any]:
        model = str(cfg.get("model", "openai/gpt-oss-120b:free"))
        body = {
            "model": model,
            "messages": [
                {"role": "system", "content": f"{SYSTEM_PROMPT}\n{ROLE_PROMPTS.get(role, '')}"},
                {"role": "user", "content": build_user_prompt(role, facts_json)},
            ],
            "temperature": 0.2,
        }
        data = json.dumps(body).encode("utf-8")
        request = urllib.request.Request(
            "https://openrouter.ai/api/v1/chat/completions",
            data=data,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
                "User-Agent": "OpenBagusJuryRouter/1.0",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=12) as response:
                payload = json.loads(response.read().decode("utf-8"))
            content = payload["choices"][0]["message"]["content"]
            scan = scan_text(content)
            return {
                "role": role,
                "model": model,
                "status": "OK" if scan["passed"] else "BLOCKED_BY_GUARD",
                "findings": scan["findings"],
                "content_preview": content[:240],
            }
        except Exception as exc:
            return {
                "role": role,
                "model": model,
                "status": "FAILED",
                "error": _short_error(exc),
            }
