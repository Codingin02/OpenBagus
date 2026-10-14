"""Dynamic Tool Registry with schema validation, telemetry and audit logging."""

from __future__ import annotations

import logging
from typing import Any

from openbagus.ai.providers.base import ToolDefinition
from openbagus.ai.tools.base import BaseFinancialTool, ToolResult

logger = logging.getLogger(__name__)


class ToolRegistry:
    """Manages discoverable financial tools for the conversational agent."""

    def __init__(self) -> None:
        self._tools: dict[str, BaseFinancialTool] = {}
        self._audit_logs: list[dict[str, Any]] = []

    def register(self, tool: BaseFinancialTool) -> None:
        self._tools[tool.name] = tool
        logger.debug("Registered financial tool: %s", tool.name)

    def get(self, name: str) -> BaseFinancialTool | None:
        return self._tools.get(name)

    def list_definitions(self) -> list[ToolDefinition]:
        return [tool.to_definition() for tool in self._tools.values()]

    def list_tool_names(self) -> list[str]:
        return list(self._tools.keys())

    def execute(self, name: str, arguments: dict[str, Any]) -> ToolResult:
        tool = self.get(name)
        if not tool:
            res = ToolResult(
                success=False,
                data=None,
                error=f"Alat analitis '{name}' tidak terdaftar dalam registry.",
            )
            self._record_audit(name, arguments, res)
            return res

        res = tool.execute_with_telemetry(arguments)
        self._record_audit(name, arguments, res)
        return res

    def _record_audit(self, tool_name: str, arguments: dict[str, Any], result: ToolResult) -> None:
        log_entry = {
            "tool_name": tool_name,
            "arguments": arguments,
            "success": result.success,
            "error": result.error,
            "latency_ms": result.latency_ms,
            "provenance": result.provenance,
        }
        self._audit_logs.append(log_entry)
        if len(self._audit_logs) > 500:
            self._audit_logs = self._audit_logs[-500:]

    def get_audit_logs(self, limit: int = 50) -> list[dict[str, Any]]:
        return self._audit_logs[-limit:]


_GLOBAL_REGISTRY: ToolRegistry | None = None


def get_global_tool_registry() -> ToolRegistry:
    global _GLOBAL_REGISTRY
    if _GLOBAL_REGISTRY is None:
        from openbagus.ai.tools.finance_tools import register_all_financial_tools
        reg = ToolRegistry()
        register_all_financial_tools(reg)
        try:
            from openbagus.companion.companion_tool import ControlBagusmaxTool
            reg.register(ControlBagusmaxTool())
        except Exception as _e:
            logger.debug("ControlBagusmaxTool registration skipped: %s", _e)
        _GLOBAL_REGISTRY = reg
    return _GLOBAL_REGISTRY

