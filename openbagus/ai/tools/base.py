"""Base schemas and abstractions for the dynamic financial tool registry."""

from __future__ import annotations

import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

from openbagus.ai.providers.base import ToolDefinition


@dataclass
class ToolResult:
    success: bool
    data: Any
    error: str | None = None
    provenance: dict[str, Any] = field(default_factory=dict)
    latency_ms: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "success": self.success,
            "data": self.data,
            "error": self.error,
            "provenance": self.provenance,
            "latency_ms": round(self.latency_ms, 2),
        }


class BaseFinancialTool(ABC):
    """Abstract class for all financial tools registered with the agent harness."""

    name: str
    description: str
    parameters_schema: dict[str, Any]
    permission_tier: str = "READ_ONLY"  # "READ_ONLY" | "SIMULATION" | "SENSITIVE"
    freshness_policy: str = "CACHED_ALLOWED"

    def to_definition(self) -> ToolDefinition:
        return ToolDefinition(
            name=self.name,
            description=self.description,
            parameters=self.parameters_schema,
        )

    def execute_with_telemetry(self, arguments: dict[str, Any]) -> ToolResult:
        t_start = time.perf_counter()
        try:
            res_data, prov = self.run(**arguments)
            elapsed = (time.perf_counter() - t_start) * 1000
            return ToolResult(
                success=True,
                data=res_data,
                provenance=prov or {},
                latency_ms=elapsed,
            )
        except Exception as e:
            elapsed = (time.perf_counter() - t_start) * 1000
            return ToolResult(
                success=False,
                data=None,
                error=str(e),
                provenance={"error_type": type(e).__name__},
                latency_ms=elapsed,
            )

    @abstractmethod
    def run(self, **kwargs: Any) -> tuple[Any, dict[str, Any]]:
        """Executes the tool and returns (result_data, provenance_metadata)."""
        ...
