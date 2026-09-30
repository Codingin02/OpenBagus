"""Compatibility shim for risk_portfolio_metrics."""

from openbagus.risk.metrics import (
    calculate_risk_metrics,
    calculate_sharpe_ratio,
    calculate_sortino_ratio,
    calculate_max_drawdown,
    calculate_var_cvar,
    monte_carlo_drawdown_simulation,
)

__all__ = [
    "calculate_risk_metrics",
    "calculate_sharpe_ratio",
    "calculate_sortino_ratio",
    "calculate_max_drawdown",
    "calculate_var_cvar",
    "monte_carlo_drawdown_simulation",
]
