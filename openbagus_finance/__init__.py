"""OpenBagus Finance Compatibility Shim Package.

Provides seamless backward compatibility for openbagus_finance imports,
aliasing cleanly to the modular openbagus architecture.
"""

from openbagus.data.ingestion import RuntimeDataIngestion, run_runtime_ingestion
from openbagus.analysis.engine import OpenBagusAnalysisEngine, run_real_analysis
from openbagus.delivery.runner import FinalDeliveryRuntime, run_final_delivery
from openbagus.reporting.dashboard import PwaDashboardRenderer

__all__ = [
    "RuntimeDataIngestion",
    "run_runtime_ingestion",
    "OpenBagusAnalysisEngine",
    "run_real_analysis",
    "FinalDeliveryRuntime",
    "run_final_delivery",
    "PwaDashboardRenderer",
]
