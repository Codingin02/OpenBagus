"""Compatibility shim for delivery_safety_guard."""

from openbagus.delivery.safety import scan_payload, scan_text

__all__ = ["scan_payload", "scan_text"]
