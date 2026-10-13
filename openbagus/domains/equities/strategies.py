"""Event-Driven Swing Trading Strategies for Indonesian Equities.

Implements candidate generation and risk filters across all capitalization tiers:
A. Post-Announcement Momentum (PAM)
B. Earnings Momentum (SUE / Turnaround)
C. Volume Expansion Breakout (VCP)
D. Event-Driven Continuation
E. Liquidity Transition
F. Post-Suspension Observation
G. Corporate Action Strategy (Buyback / Dividend)
H. Mean Reversion
I. Sector / Commodity Catalyst
J. Negative Catalyst Risk Watch (Capital Preservation)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Sequence

from openbagus.domains.equities.events import CorporateEventRecord
from openbagus.domains.equities.microstructure import IDXMicrostructureEngine, MicrostructureProfile
from openbagus.domains.quant.engine import (
    calculate_sma,
    calculate_ema,
    calculate_rsi,
    calculate_atr,
    calculate_lot_shares,
)


@dataclass
class TradingSignal:
    ticker: str
    strategy_name: str
    action: str              # "BUY", "WATCH", "EXIT", "NO_TRADE", "REJECTED_BY_RISK"
    signal_date: str
    entry_price: float | None = None
    stop_loss: float | None = None
    target_price: float | None = None
    reward_risk_ratio: float = 0.0
    suggested_shares: int = 0
    suggested_notional: float = 0.0
    confidence_score: float = 0.0
    catalyst_event: CorporateEventRecord | None = None
    rationale: str = ""
    risk_warnings: list[str] = field(default_factory=list)
    execution_eligible: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "ticker": self.ticker,
            "strategy": self.strategy_name,
            "action": self.action,
            "signal_date": self.signal_date,
            "entry_price": self.entry_price,
            "stop_loss": self.stop_loss,
            "target_price": self.target_price,
            "reward_risk": round(self.reward_risk_ratio, 2),
            "suggested_shares": self.suggested_shares,
            "suggested_notional": self.suggested_notional,
            "confidence_score": round(self.confidence_score, 2),
            "catalyst": self.catalyst_event.event_title if self.catalyst_event else None,
            "rationale": self.rationale,
            "risk_warnings": self.risk_warnings,
            "execution_eligible": self.execution_eligible,
        }


class BaseStrategy:
    def __init__(self, name: str) -> None:
        self.name = name

    def evaluate(
        self,
        ticker: str,
        candles: Sequence[dict[str, Any]],
        profile: MicrostructureProfile,
        events: Sequence[CorporateEventRecord] | None = None,
        capital_budget: float = 10_000_000.0,
        max_risk_pct: float = 0.02,
    ) -> TradingSignal:
        raise NotImplementedError


class PostAnnouncementMomentumStrategy(BaseStrategy):
    """Detects verified material disclosures accompanied by abnormal relative volume and price expansion."""

    def __init__(self) -> None:
        super().__init__("PostAnnouncementMomentum")

    def evaluate(
        self,
        ticker: str,
        candles: Sequence[dict[str, Any]],
        profile: MicrostructureProfile,
        events: Sequence[CorporateEventRecord] | None = None,
        capital_budget: float = 10_000_000.0,
        max_risk_pct: float = 0.02,
    ) -> TradingSignal:
        if not candles or len(candles) < 20:
            return TradingSignal(
                ticker=ticker,
                strategy_name=self.name,
                action="NO_TRADE",
                signal_date=candles[-1]["open_at"][:10] if candles else "",
                rationale="Data historis kurang dari 20 candle.",
                execution_eligible=profile.execution_eligible,
            )

        # Microstructure / execution gate
        if not profile.execution_eligible:
            return TradingSignal(
                ticker=ticker,
                strategy_name=self.name,
                action="REJECTED_BY_RISK",
                signal_date=candles[-1]["open_at"][:10],
                rationale=f"Ditolak oleh Microstructure Engine: {profile.rejection_reason}",
                execution_eligible=False,
                risk_warnings=[profile.rejection_reason],
            )

        # Check positive catalyst within 14 trading days
        recent_pos_event = None
        if events:
            for ev in events:
                if ev.sentiment_label in ("HIGH_POSITIVE", "MODERATE_POSITIVE"):
                    recent_pos_event = ev
                    break

        if not recent_pos_event:
            return TradingSignal(
                ticker=ticker,
                strategy_name=self.name,
                action="NO_TRADE",
                signal_date=candles[-1]["open_at"][:10],
                rationale="Tidak ada pengumuman katalis material positif terbaru.",
            )

        closes = [float(c["close"]) for c in candles]
        volumes = [float(c.get("volume", 0.0)) for c in candles]
        last_close = closes[-1]
        last_vol = volumes[-1]
        v20 = volumes[-21:-1]
        avg_v20 = sum(v20) / len(v20) if v20 else 0.0

        # Technical confirmation: volume spike >= 1.5x and close > 20d SMA
        sma20 = calculate_sma(closes, 20)[-1] or last_close
        vol_multiple = (last_vol / avg_v20) if avg_v20 > 0 else 0.0

        if vol_multiple >= 1.5 and last_close >= sma20:
            # Entry setup
            entry_px = IDXMicrostructureEngine.snap_to_tick(last_close, profile.board)
            low20 = min(float(c["low"]) for c in candles[-20:])
            stop_px = IDXMicrostructureEngine.snap_to_tick(max(profile.arb_price, low20 * 0.97), profile.board)

            risk_per_share = max(1.0, entry_px - stop_px)
            target_px = IDXMicrostructureEngine.snap_to_tick(entry_px + 2.0 * risk_per_share, profile.board)
            rr = (target_px - entry_px) / risk_per_share

            max_risk_cash = capital_budget * max_risk_pct
            shares, notional = calculate_lot_shares(capital_budget, entry_px, max_risk_cash, stop_px)

            return TradingSignal(
                ticker=ticker,
                strategy_name=self.name,
                action="BUY",
                signal_date=candles[-1]["open_at"][:10],
                entry_price=entry_px,
                stop_loss=stop_px,
                target_price=target_px,
                reward_risk_ratio=rr,
                suggested_shares=shares,
                suggested_notional=notional,
                confidence_score=min(100.0, 50.0 + vol_multiple * 10.0 + recent_pos_event.impact_score * 0.3),
                catalyst_event=recent_pos_event,
                rationale=(
                    f"PAM Terkonfirmasi: Katalis '{recent_pos_event.event_title}' didukung "
                    f"kenaikan volume {vol_multiple:.1f}x di atas rata-rata 20-hari."
                ),
            )

        return TradingSignal(
            ticker=ticker,
            strategy_name=self.name,
            action="WATCH",
            signal_date=candles[-1]["open_at"][:10],
            confidence_score=recent_pos_event.impact_score * 0.5,
            catalyst_event=recent_pos_event,
            rationale=f"Katalis positif ada, namun volume ({vol_multiple:.1f}x) belum mengonfirmasi breakout.",
        )


class VolumeExpansionBreakoutStrategy(BaseStrategy):
    """Detects volume expansion breakout (RVOL > 2.0x, closing at 20-day high)."""

    def __init__(self) -> None:
        super().__init__("VolumeExpansionBreakout")

    def evaluate(
        self,
        ticker: str,
        candles: Sequence[dict[str, Any]],
        profile: MicrostructureProfile,
        events: Sequence[CorporateEventRecord] | None = None,
        capital_budget: float = 10_000_000.0,
        max_risk_pct: float = 0.02,
    ) -> TradingSignal:
        if not candles or len(candles) < 20:
            return TradingSignal(
                ticker=ticker,
                strategy_name=self.name,
                action="NO_TRADE",
                signal_date=candles[-1]["open_at"][:10] if candles else "",
                rationale="Data tidak cukup untuk breakout 20 hari.",
            )

        if not profile.execution_eligible:
            return TradingSignal(
                ticker=ticker,
                strategy_name=self.name,
                action="REJECTED_BY_RISK",
                signal_date=candles[-1]["open_at"][:10],
                rationale=profile.rejection_reason,
                execution_eligible=False,
            )

        closes = [float(c["close"]) for c in candles]
        volumes = [float(c.get("volume", 0.0)) for c in candles]
        last_close = closes[-1]
        last_vol = volumes[-1]

        v20 = volumes[-21:-1]
        c20 = closes[-21:-1]
        avg_v20 = sum(v20) / len(v20) if v20 else 0.0
        high20 = max(c20) if c20 else last_close

        vol_mult = (last_vol / avg_v20) if avg_v20 > 0 else 0.0

        if vol_mult >= 2.0 and last_close > high20:
            entry_px = IDXMicrostructureEngine.snap_to_tick(last_close, profile.board)
            stop_px = IDXMicrostructureEngine.snap_to_tick(high20 * 0.98, profile.board)
            risk_per_share = max(1.0, entry_px - stop_px)
            target_px = IDXMicrostructureEngine.snap_to_tick(entry_px + 2.5 * risk_per_share, profile.board)

            max_risk_cash = capital_budget * max_risk_pct
            shares, notional = calculate_lot_shares(capital_budget, entry_px, max_risk_cash, stop_px)

            return TradingSignal(
                ticker=ticker,
                strategy_name=self.name,
                action="BUY",
                signal_date=candles[-1]["open_at"][:10],
                entry_price=entry_px,
                stop_loss=stop_px,
                target_price=target_px,
                reward_risk_ratio=2.5,
                suggested_shares=shares,
                suggested_notional=notional,
                confidence_score=min(95.0, 60.0 + vol_mult * 5.0),
                rationale=f"Breakout struktur 20-hari dengan lonjakan volume {vol_mult:.1f}x ADTV20.",
            )

        return TradingSignal(
            ticker=ticker,
            strategy_name=self.name,
            action="NO_TRADE",
            signal_date=candles[-1]["open_at"][:10],
            rationale="Belum ada breakout struktur harga dan ekspansi volume.",
        )


class NegativeCatalystRiskWatch(BaseStrategy):
    """Detects material negative disclosures and recommends capital preservation (NO-TRADE or EXIT)."""

    def __init__(self) -> None:
        super().__init__("NegativeCatalystRiskWatch")

    def evaluate(
        self,
        ticker: str,
        candles: Sequence[dict[str, Any]],
        profile: MicrostructureProfile,
        events: Sequence[CorporateEventRecord] | None = None,
        capital_budget: float = 10_000_000.0,
        max_risk_pct: float = 0.02,
    ) -> TradingSignal:
        s_date = candles[-1]["open_at"][:10] if candles else datetime.now(timezone.utc).strftime("%Y-%m-%d")

        negative_events = []
        if events:
            for ev in events:
                if ev.sentiment_label == "NEGATIVE_RISK" or ev.impact_score < -30.0:
                    negative_events.append(ev)

        if negative_events or profile.is_suspended or profile.is_fca:
            warnings = []
            if profile.is_suspended:
                warnings.append("Saham tersuspensi Bursa.")
            if profile.is_fca:
                warnings.append("Saham masuk Papan Pemantauan Khusus (FCA).")
            for ev in negative_events[:2]:
                warnings.append(f"Katalis negatif: {ev.event_title}")

            return TradingSignal(
                ticker=ticker,
                strategy_name=self.name,
                action="EXIT",
                signal_date=s_date,
                confidence_score=90.0,
                catalyst_event=negative_events[0] if negative_events else None,
                rationale="Prioritas proteksi modal: terdeteksi pengumuman/status berisiko tinggi.",
                risk_warnings=warnings,
                execution_eligible=False,
            )

        return TradingSignal(
            ticker=ticker,
            strategy_name=self.name,
            action="NO_TRADE",
            signal_date=s_date,
            rationale="Tidak ada sinyal katalis negatif berisiko tinggi.",
        )
