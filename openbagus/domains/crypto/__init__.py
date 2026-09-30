"""Crypto Domain package for OpenBagus.

Provides cryptocurrency microstructure, order flow analysis, and liquidity metrics.
"""

from __future__ import annotations

from openbagus.domains.crypto.microstructure import analyze_crypto_microstructure

__all__ = ["analyze_crypto_microstructure"]
