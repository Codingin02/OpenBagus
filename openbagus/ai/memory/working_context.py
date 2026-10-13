"""Working context, entity resolution, and conversational state tracking."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


@dataclass
class WorkingContext:
    """Maintains active entities, candidate shortlists, and constraints across turns."""

    session_id: str = "default"
    active_ticker: str | None = None
    active_ticker_name: str | None = None
    comparison_tickers: list[str] = field(default_factory=list)
    market: str = "IDX"  # "IDX" | "CRYPTO" | "MACRO"
    strategy: str = "GENERAL"  # "SWING" | "INVESTMENT" | "VALUATION" | "LIQUIDITY" | "EVENT_DRIVEN"
    time_horizon: str = "MEDIUM_TERM"  # "INTRADAY" | "1_WEEK" | "2_WEEKS" | "1_MONTH" | "LONG_TERM"
    financial_period: str = "LATEST"
    active_candidates: list[dict[str, Any]] = field(default_factory=list)
    explicit_constraints: dict[str, Any] = field(default_factory=dict)
    prior_observations: dict[str, Any] = field(default_factory=dict)
    turns: list[dict[str, str]] = field(default_factory=list)
    user_style: str = "PROFESSIONAL_DIRECT"
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def record_turn(self, role: str, content: str) -> None:
        self.turns.append({
            "role": role,
            "content": content,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })
        self.updated_at = datetime.now(timezone.utc).isoformat()
        # Keep turns bounded to recent 30 turns
        if len(self.turns) > 30:
            self.turns = self.turns[-30:]

    def handle_corrections(self, user_query: str) -> dict[str, Any]:
        """Detects and applies explicit user corrections (entity, strategy, horizon)."""
        lower = user_query.lower()
        applied: dict[str, Any] = {}

        # 1. Entity Correction: "Bukan BBRI, maksudku BMRI" / "Ganti ke BBCA"
        corr_match = re.search(r"\b(?:bukan\s+([a-zA-Z]{4})[,\s]+maksud(?:ku|nya)?\s+([a-zA-Z]{4})|maksudku\s+([a-zA-Z]{4}))\b", lower)
        if corr_match:
            new_ticker = (corr_match.group(2) or corr_match.group(3) or "").upper()
            if new_ticker:
                self.active_ticker = new_ticker
                # Invalidate prior entity calculations
                self.prior_observations.pop("last_valuation", None)
                self.prior_observations.pop("last_ratios", None)
                applied["entity_corrected"] = new_ticker

        # 2. Strategy Detection & Change: "Bukan investasi, aku mau swing" / "investasi panjang"
        if re.search(r"\b(?:bukan.*(?:mau|ingin)?\s*swing|aku\s*maunya\s*swing|mau\s+swing|ganti\s+ke\s+swing)\b", lower):
            self.strategy = "SWING"
            applied["strategy_changed"] = "SWING"
        elif re.search(r"\b(?:investasi\s+panjang|jangka\s+panjang|bukan.*(?:mau|ingin)?\s*investasi|mau\s+investasi)\b", lower):
            self.strategy = "INVESTMENT"
            applied["strategy_changed"] = "INVESTMENT"

        # 3. Horizon Change: "Kalau hold tiga minggu?" / "Untuk dua minggu" / "Horizon dua minggu"
        h_match = re.search(r"\b(?:(?:hold|tahan|horizon|untuk)\s+(\d+|satu|dua|tiga|empat)\s*(?:hari|minggu|bulan))\b", lower)
        if h_match:
            phrase = h_match.group(0)
            if "minggu" in phrase:
                self.time_horizon = "2_WEEKS" if "dua" in phrase else ("3_WEEKS" if "tiga" in phrase else "1_WEEK")
            elif "bulan" in phrase:
                self.time_horizon = "LONG_TERM"
            applied["horizon_changed"] = self.time_horizon

        # 4. Liquidity constraint refinement: "Yang volumenya lebih bagus dan likuid."
        if re.search(r"\b(?:cari\s+yang\s+lebih\s+likuid|lebih\s+bagus\s+dan\s+likuid|lebih\s+likuid|tambah(?:kan)?\s+filter\s+likuiditas|likuiditas(?:nya)?\s+kurang)\b", lower):
            self.explicit_constraints["min_adtv"] = 500_000_000.0  # Rp 500 Juta
            self.explicit_constraints["only_liquid"] = True
            applied["constraint_added"] = "only_liquid"

        return applied

    def resolve_candidate_reference(self, user_query: str) -> dict[str, Any] | None:
        """Resolves references like 'yang pertama', 'pilihan kedua', 'alternatif ketiga'."""
        lower = user_query.lower()
        if not self.active_candidates:
            return None

        matches: list[tuple[int, int]] = []
        for m in re.finditer(r"\b(?:yang\s+pertama|pilihan\s+pertama|kandidat\s+pertama|opsi\s+pertama|no(?:mor)?\s*1)\b", lower):
            matches.append((m.start(), 0))
        for m in re.finditer(r"\b(?:yang\s+kedua|pilihan\s+kedua|kandidat\s+kedua|alternatif\s+kedua|opsi\s+kedua|no(?:mor)?\s*2)\b", lower):
            matches.append((m.start(), 1))
        for m in re.finditer(r"\b(?:yang\s+ketiga|pilihan\s+ketiga|kandidat\s+ketiga|alternatif\s+ketiga|opsi\s+ketiga|no(?:mor)?\s*3)\b", lower):
            matches.append((m.start(), 2))

        if not matches:
            return None

        matches.sort(key=lambda x: x[0])
        idx = matches[-1][1]  # Take focal reference at the end of the clause

        if 0 <= idx < len(self.active_candidates):
            chosen = self.active_candidates[idx]
            ticker = chosen.get("ticker") or chosen.get("symbol")
            if ticker:
                self.active_ticker = str(ticker).upper()
            return chosen
        return None

    def to_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "active_ticker": self.active_ticker,
            "comparison_tickers": self.comparison_tickers,
            "market": self.market,
            "strategy": self.strategy,
            "time_horizon": self.time_horizon,
            "financial_period": self.financial_period,
            "active_candidates": self.active_candidates,
            "explicit_constraints": self.explicit_constraints,
            "turns_count": len(self.turns),
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> WorkingContext:
        ctx = cls(session_id=data.get("session_id", "default"))
        ctx.active_ticker = data.get("active_ticker")
        ctx.comparison_tickers = data.get("comparison_tickers", [])
        ctx.market = data.get("market", "IDX")
        ctx.strategy = data.get("strategy", "GENERAL")
        ctx.time_horizon = data.get("time_horizon", "MEDIUM_TERM")
        ctx.financial_period = data.get("financial_period", "LATEST")
        ctx.active_candidates = data.get("active_candidates", [])
        ctx.explicit_constraints = data.get("explicit_constraints", {})
        ctx.turns = data.get("turns", [])
        ctx.updated_at = data.get("updated_at", ctx.updated_at)
        return ctx
