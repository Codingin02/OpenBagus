"""Compatibility shim for runtime_real_data_ingestion."""

from openbagus.data.ingestion import RuntimeDataIngestion, run_runtime_ingestion

__all__ = ["RuntimeDataIngestion", "run_runtime_ingestion"]
