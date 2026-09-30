"""OpenBagus Data Package.

Provides market and macro ingestion, data normalization, freshness checking,
and storage integration for active domains.
"""

from openbagus.data.ingestion import RuntimeDataIngestion, run_runtime_ingestion

__all__ = ["RuntimeDataIngestion", "run_runtime_ingestion"]
