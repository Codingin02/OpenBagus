"""Reasoning mode controller managing FAST and DEEP_REASONING modes with spoken mode selection."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any

from openbagus.ai.runtime.profiles import RuntimeProfile, get_profile

logger = logging.getLogger(__name__)

MODE_SELECTION_PROMPT = (
    "Ini perlu analisis yang lebih dalam. "
    "Mau saya jawab cepat dulu atau gunakan penalaran mendalam? "
    "Yang mendalam biasanya lebih lama."
)


@dataclass
class PendingModeQuery:
    original_query: str
    ticker: str | None
    detected_strategy: str | None


class VoiceModeController:
    """Manages conversational reasoning modes, expensive analysis detection, and spoken mode resolution."""

    def __init__(self, default_mode: str = "FAST") -> None:
        self.current_mode = default_mode.upper()
        self.session_preference = "ASK_IF_EXPENSIVE"  # "ALWAYS_FAST" | "ALWAYS_DEEP" | "ASK_IF_EXPENSIVE"
        self._pending_query: PendingModeQuery | None = None

    def get_profile(self) -> RuntimeProfile:
        """Returns the corresponding RuntimeProfile for the active mode."""
        if self.current_mode == "DEEP_REASONING":
            return get_profile("DEEP_RESEARCH")
        return get_profile("FAST")

    def set_mode(self, mode: str) -> None:
        clean = mode.strip().upper()
        if clean in ("DEEP", "DEEP_REASONING", "REASONING"):
            self.current_mode = "DEEP_REASONING"
        else:
            self.current_mode = "FAST"
        logger.info("Voice reasoning mode switched to: %s", self.current_mode)

    def is_expensive_query(self, query: str) -> bool:
        """Determines if a query materially benefits from high-effort DEEP_REASONING."""
        lower = query.lower()
        # Heuristics for complex, multi-year, multi-statement, or scenario valuation
        expensive_patterns = [
            r"\b(?:bedah|analisis mendalam|komprehensif)\b",
            r"\b(?:dcf|valuasi intrinsik|skenario|margin of safety)\b",
            r"\b(?:lima tahun|5 tahun|multi tahun|historis)\b",
            r"\b(?:bandingkan|peer comparison)\s+.*?\s+(?:dengan|versus)\b",
            r"\b(?:backtest|uji strategi|simulasi monte carlo|var cvar)\b",
            r"\b(?:dupont|roic versus wacc|kualitas laba)\b",
        ]
        return any(bool(re.search(p, lower)) for p in expensive_patterns)

    def should_ask_for_mode(self, query: str) -> bool:
        """Checks whether we should prompt the user for mode selection before execution."""
        if self.session_preference == "ALWAYS_FAST":
            return False
        if self.session_preference == "ALWAYS_DEEP":
            self.current_mode = "DEEP_REASONING"
            return False

        # If user explicitly specified mode in the query, honor immediately
        lower = query.lower()
        if any(w in lower for w in ["pakai reasoning", "mode mendalam", "analisis lengkap", "deep reasoning"]):
            self.current_mode = "DEEP_REASONING"
            return False
        if any(w in lower for w in ["jawab cepat", "singkat saja", "mode cepat", "ringkas"]):
            self.current_mode = "FAST"
            return False

        return self.is_expensive_query(query)

    def set_pending_query(self, query: str, ticker: str | None = None, strategy: str | None = None) -> str:
        """Registers a pending query awaiting user's spoken mode response."""
        self._pending_query = PendingModeQuery(
            original_query=query,
            ticker=ticker,
            detected_strategy=strategy,
        )
        if ticker:
            return (
                f"Analisis {ticker} ini perlu komputasi mendalam. "
                "Mau saya jawab dengan Mode Cepat atau gunakan Deep Reasoning? "
                "Deep Reasoning biasanya lebih komprehensif namun butuh waktu lebih lama."
            )
        return (
            "Analisis ini perlu komputasi mendalam. "
            "Mau saya jawab dengan Mode Cepat atau gunakan Deep Reasoning? "
            "Deep Reasoning biasanya lebih lama."
        )

    def has_pending_query(self) -> bool:
        return self._pending_query is not None

    def get_pending_query(self) -> PendingModeQuery | None:
        return self._pending_query

    def clear_pending_query(self) -> None:
        self._pending_query = None

    def resolve_spoken_mode_answer(self, spoken_answer: str) -> tuple[str, PendingModeQuery | None]:
        """Resolves spoken response (e.g. 'Cepat', 'Yang mendalam') and returns (mode, original_query)."""
        lower = spoken_answer.lower().strip()
        pending = self._pending_query
        self._pending_query = None

        if any(w in lower for w in ["mendalam", "deep", "reasoning", "lengkap", "tinggi"]):
            self.current_mode = "DEEP_REASONING"
        else:
            self.current_mode = "FAST"

        return self.current_mode, pending

    def handle_mode_commands(self, user_query: str) -> str | None:
        """Handles spoken voice commands switching persistent preferences."""
        lower = user_query.lower()
        if re.search(r"\b(?:mulai sekarang|seterusnya)?\s*pakai\s+mode\s+cepat\b", lower):
            self.current_mode = "FAST"
            self.session_preference = "ALWAYS_FAST"
            return "Mode cepat diaktifkan untuk seluruh percakapan sesi ini."
        if re.search(r"\b(?:mulai sekarang|seterusnya)?\s*pakai\s+(?:mode\s+)?(?:reasoning|mendalam)\b", lower):
            self.current_mode = "DEEP_REASONING"
            self.session_preference = "ALWAYS_DEEP"
            return "Mode penalaran mendalam diaktifkan untuk seluruh percakapan sesi ini."
        if re.search(r"\b(?:tanyakan|tanya dulu|konfirmasi)\s+kalau\s+perlu\s+reasoning\b", lower):
            self.session_preference = "ASK_IF_EXPENSIVE"
            return "Konfirmasi mode akan ditanyakan sebelum menjalankan analisis berat."
        return None
