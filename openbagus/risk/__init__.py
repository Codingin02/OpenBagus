"""OpenBagus Risk & Portfolio Analytics."""

from __future__ import annotations

from openbagus.risk.portfolio import calculate_risk_metrics
from openbagus.risk.multi_asset import (
    PositionSizeResult,
    PortfolioVaRResult,
    CorrelationMatrixResult,
    calculate_position_size,
    calculate_portfolio_var,
    calculate_correlation_matrix,
    format_position_size_summary,
    format_portfolio_var_summary,
    format_correlation_matrix_table,
)

__all__ = [
    "calculate_risk_metrics",
    "PositionSizeResult",
    "PortfolioVaRResult",
    "CorrelationMatrixResult",
    "calculate_position_size",
    "calculate_portfolio_var",
    "calculate_correlation_matrix",
    "format_position_size_summary",
    "format_portfolio_var_summary",
    "format_correlation_matrix_table",
]
