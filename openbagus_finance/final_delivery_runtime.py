"""Compatibility shim for final_delivery_runtime."""

from openbagus.delivery.runner import (
    CONFIRMATION_PHRASE,
    FinalDeliveryRuntime,
    ManualQueryParser,
    run_final_delivery,
)

__all__ = [
    "FinalDeliveryRuntime",
    "run_final_delivery",
    "ManualQueryParser",
    "CONFIRMATION_PHRASE",
]
