"""Compatibility shim for market_structure_engine."""

from openbagus.core.market_structure import (
    analyze_market_structure,
    calculate_vwap,
    calculate_volume_profile,
    detect_support_resistance,
)

__all__ = [
    "analyze_market_structure",
    "calculate_vwap",
    "calculate_volume_profile",
    "detect_support_resistance",
]
