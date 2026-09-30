"""Compatibility shim for real_analysis_engine."""

from openbagus.analysis.engine import (
    DataQualityAgent,
    MacroAgent,
    OpenBagusAnalysisEngine,
    QuantCoreAgent,
    run_real_analysis,
)

__all__ = [
    "OpenBagusAnalysisEngine",
    "run_real_analysis",
    "DataQualityAgent",
    "MacroAgent",
    "QuantCoreAgent",
]
