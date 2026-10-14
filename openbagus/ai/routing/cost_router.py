"""Cost-Aware Model Router with Token Budgeting and Spend Guardrails.

Enforces zero-cloud-spend default ($0.00 budget), local-first execution,
role-based dynamic model assignment, and spend tracking with persistent ledger.
"""

from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import asdict, dataclass
from enum import Enum
from pathlib import Path
from typing import Any

from openbagus.ai.credentials import CredentialManager
from openbagus.ai.providers.base import BaseModelProvider
from openbagus.ai.providers.gemini_provider import GeminiProvider
from openbagus.ai.providers.manager import ProviderManager
from openbagus.ai.providers.openai_provider import OpenAIProvider

logger = logging.getLogger(__name__)


class ModelRole(str, Enum):
    """Dynamic operational roles for queries."""
    FAST_RESPONDER = "FAST_RESPONDER"
    DEEP_REASONER = "DEEP_REASONER"
    RESEARCH_SYNTHESIZER = "RESEARCH_SYNTHESIZER"


@dataclass
class ModelPricing:
    """Pricing in USD per 1,000,000 tokens."""
    input_per_m: float
    output_per_m: float


MODEL_PRICING_TABLE: dict[str, ModelPricing] = {
    # Local models: strictly zero marginal cost
    "qwen3.5:2b": ModelPricing(0.0, 0.0),
    "qwen3.5:4b": ModelPricing(0.0, 0.0),
    "qwen3.5:2b-q4_K_M": ModelPricing(0.0, 0.0),
    "llama_local": ModelPricing(0.0, 0.0),
    "deterministic_fallback": ModelPricing(0.0, 0.0),
    # Cloud models
    "gpt-4o-mini": ModelPricing(0.15, 0.60),
    "gpt-4o": ModelPricing(2.50, 10.00),
    "gemini-2.5-flash": ModelPricing(0.075, 0.30),
    "gemini-2.5-pro": ModelPricing(1.25, 5.00),
}


@dataclass
class UsageRecord:
    timestamp: float
    provider: str
    model: str
    role: str
    input_tokens: int
    output_tokens: int
    cost_usd: float


class CostAwareModelRouter:
    """Routes requests across local and optional cloud providers while enforcing cost limits."""

    _instance: CostAwareModelRouter | None = None

    def __init__(self, ledger_path: Path | None = None) -> None:
        if ledger_path is None:
            home = Path.home()
            openbagus_dir = home / ".openbagus"
            openbagus_dir.mkdir(parents=True, exist_ok=True)
            self.ledger_path = openbagus_dir / "spend_ledger.json"
        else:
            self.ledger_path = ledger_path

        self.creds = CredentialManager.get_instance()
        self.provider_mgr = ProviderManager.get_instance()

        # Cloud spend limit default: $0.00 (Cloud strictly off unless explicitly granted)
        self.monthly_budget_usd: float = float(os.environ.get("OPENBAGUS_CLOUD_BUDGET_USD", "0.00"))
        self.cloud_enabled: bool = os.environ.get("OPENBAGUS_ALLOW_CLOUD_MODELS", "0").lower() in ("1", "true", "yes")

        self._load_ledger()

    @classmethod
    def get_instance(cls) -> CostAwareModelRouter:
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def _load_ledger(self) -> None:
        self.records: list[dict[str, Any]] = []
        if self.ledger_path.exists():
            try:
                data = json.loads(self.ledger_path.read_text(encoding="utf-8"))
                self.records = data.get("records", [])
                if "monthly_budget_usd" in data and self.monthly_budget_usd == 0.0:
                    self.monthly_budget_usd = float(data["monthly_budget_usd"])
                if "cloud_enabled" in data and not self.cloud_enabled:
                    self.cloud_enabled = bool(data["cloud_enabled"])
            except Exception as e:
                logger.warning("Could not read spend ledger: %s", e)
                self.records = []

    def _save_ledger(self) -> None:
        try:
            payload = {
                "monthly_budget_usd": self.monthly_budget_usd,
                "cloud_enabled": self.cloud_enabled,
                "total_spend_usd": self.get_total_spend_usd(),
                "monthly_spend_usd": self.get_monthly_spend_usd(),
                "records_count": len(self.records),
                "records": self.records[-200:],  # keep last 200 records
            }
            self.ledger_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        except Exception as e:
            logger.warning("Could not write spend ledger: %s", e)

    def set_budget(self, budget_usd: float, enable_cloud: bool = True) -> None:
        """Sets monthly cloud budget and enables or disables cloud routing."""
        self.monthly_budget_usd = max(0.0, float(budget_usd))
        self.cloud_enabled = enable_cloud and self.monthly_budget_usd > 0.0
        self._save_ledger()
        logger.info(
            "Cloud budget set to $%.2f (cloud_enabled=%s)",
            self.monthly_budget_usd,
            self.cloud_enabled,
        )

    def get_monthly_spend_usd(self) -> float:
        """Calculates total spend for the current 30-day window."""
        now = time.time()
        thirty_days_ago = now - (30 * 86400)
        total = 0.0
        for r in self.records:
            if r.get("timestamp", 0) >= thirty_days_ago:
                total += float(r.get("cost_usd", 0.0))
        return total

    def get_total_spend_usd(self) -> float:
        return sum(float(r.get("cost_usd", 0.0)) for r in self.records)

    def get_remaining_budget_usd(self) -> float:
        return max(0.0, self.monthly_budget_usd - self.get_monthly_spend_usd())

    def can_use_cloud(self, estimated_cost_usd: float = 0.001) -> bool:
        """Verifies if cloud inference is permitted by budget and flag."""
        if not self.cloud_enabled or self.monthly_budget_usd <= 0.0:
            return False
        return self.get_remaining_budget_usd() >= estimated_cost_usd

    def record_usage(
        self,
        provider: str,
        model: str,
        role: ModelRole | str,
        input_tokens: int,
        output_tokens: int,
    ) -> float:
        """Calculates and logs token usage and cost in USD."""
        role_str = role.value if isinstance(role, ModelRole) else str(role)
        pricing = MODEL_PRICING_TABLE.get(model, ModelPricing(0.0, 0.0))
        cost = (input_tokens / 1_000_000.0 * pricing.input_per_m) + (
            output_tokens / 1_000_000.0 * pricing.output_per_m
        )

        rec = UsageRecord(
            timestamp=time.time(),
            provider=provider,
            model=model,
            role=role_str,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_usd=cost,
        )
        self.records.append(asdict(rec))
        self._save_ledger()
        return cost

    # -------------------------------------------------------------------------
    # Role-Based Routing
    # -------------------------------------------------------------------------

    def route(
        self,
        role: ModelRole | str = ModelRole.FAST_RESPONDER,
        allow_cloud_override: bool = False,
    ) -> tuple[BaseModelProvider, str]:
        """Routes to the optimal provider according to role, hardware, and budget.

        Returns (provider_instance, role_name).
        """
        if isinstance(role, str):
            try:
                role = ModelRole(role.upper())
            except ValueError:
                role = ModelRole.FAST_RESPONDER

        # Rule 1: FAST_RESPONDER always uses local GPU FAST model (qwen3.5:2b) or fallback
        if role == ModelRole.FAST_RESPONDER:
            return self.provider_mgr.switch_to_fast(), role.value

        # Rule 2: DEEP_REASONER or RESEARCH_SYNTHESIZER
        # Check if cloud is explicitly permitted and has budget
        has_budget = self.can_use_cloud()
        if (self.cloud_enabled or allow_cloud_override) and has_budget:
            # Check OpenAI
            openai_key = self.creds.get_credential("openai")
            if openai_key and len(openai_key) > 10:
                p_openai = OpenAIProvider(api_key=openai_key)
                if p_openai.is_available():
                    return p_openai, role.value

            # Check Gemini
            gemini_key = self.creds.get_credential("gemini")
            if gemini_key and len(gemini_key) > 10:
                p_gemini = GeminiProvider(api_key=gemini_key)
                if p_gemini.is_available():
                    return p_gemini, role.value

        # Rule 3: Default to local DEEP model (qwen3.5:4b) with thinking trace
        return self.provider_mgr.switch_to_deep(), role.value

    def get_status(self) -> dict[str, Any]:
        """Returns diagnostic and accounting status."""
        return {
            "cloud_enabled": self.cloud_enabled,
            "monthly_budget_usd": self.monthly_budget_usd,
            "monthly_spend_usd": round(self.get_monthly_spend_usd(), 4),
            "remaining_budget_usd": round(self.get_remaining_budget_usd(), 4),
            "total_spend_usd": round(self.get_total_spend_usd(), 4),
            "total_transactions": len(self.records),
            "cloud_providers_configured": {
                "openai": bool(self.creds.get_credential("openai")),
                "gemini": bool(self.creds.get_credential("gemini")),
            },
        }
