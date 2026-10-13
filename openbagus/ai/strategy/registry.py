"""Discoverable multi-strategy financial research registry."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class StrategyMetadata:
    strategy_id: str
    name: str
    version: str
    family: str  # "EVENT_DRIVEN" | "MOMENTUM" | "VALUE" | "QUALITY" | "MICROSTRUCTURE" | "RISK"
    research_purpose: str
    applicable_markets: list[str]
    timeframe: str
    required_data: list[str]
    entry_conditions: str
    invalidation_conditions: str
    risk_model: str
    mechanism_assumptions: str
    validation_status: str = "VERIFIED"
    last_evaluated: str = "2026-10-14"

    def to_dict(self) -> dict[str, Any]:
        return {
            "strategy_id": self.strategy_id,
            "name": self.name,
            "version": self.version,
            "family": self.family,
            "research_purpose": self.research_purpose,
            "applicable_markets": self.applicable_markets,
            "timeframe": self.timeframe,
            "required_data": self.required_data,
            "entry_conditions": self.entry_conditions,
            "invalidation_conditions": self.invalidation_conditions,
            "risk_model": self.risk_model,
            "mechanism_assumptions": self.mechanism_assumptions,
            "validation_status": self.validation_status,
        }


CANONICAL_STRATEGIES: list[StrategyMetadata] = [
    StrategyMetadata(
        strategy_id="PAM_SWING",
        name="Post-Announcement Momentum (PAM)",
        version="1.0.0",
        family="EVENT_DRIVEN",
        research_purpose="Menangkap momentum harga jangka pendek pasca keterbukaan informasi material resmi.",
        applicable_markets=["IDX"],
        timeframe="1_WEEK - 3_WEEKS",
        required_data=["CorporateEvents", "EOD_Candles", "MicrostructureProfile"],
        entry_conditions="Event dampak positif (Skor >= +40, Materialitas >= 20%) + Relative Volume Spike (RVOL >= 1.5x).",
        invalidation_conditions="Close di bawah swing low atau breakout candle low; pengumuman sanggahan (clarification disclaimer).",
        risk_model="Max 2.0% equity risk per trade, stop-loss 1.5x ATR di bawah entry.",
        mechanism_assumptions="Continuous Regular; eksekusi T+1 Open jika rilis >= 16:00 WIB; tolakan harga jika >= ARA.",
    ),
    StrategyMetadata(
        strategy_id="VCP_BREAKOUT",
        name="Volume Expansion Breakout (VCP)",
        version="1.0.0",
        family="MOMENTUM",
        research_purpose="Mengidentifikasi breakout resistensi 20-hari yang didukung oleh ekspansi volume institusional.",
        applicable_markets=["IDX", "CRYPTO"],
        timeframe="1_WEEK - 4_WEEKS",
        required_data=["EOD_Candles", "MicrostructureProfile"],
        entry_conditions="Breakout harga di atas resistensi 20-hari + Volume >= 2.0x rata-rata 20-hari.",
        invalidation_conditions="False breakout (re-entry ke dalam range sideways); zero-volume streak >= 3 hari.",
        risk_model="Max 2.0% modal, stop loss pada level resistensi lama yang berubah jadi support.",
        mechanism_assumptions="Continuous trading reguler; penolakan jika ADTV20 < Rp 50 Juta.",
    ),
    StrategyMetadata(
        strategy_id="VALUE_FCFF",
        name="Damodaran Free Cash Flow to Firm (FCFF)",
        version="1.0.0",
        family="VALUE",
        research_purpose="Menghitung nilai intrinsik wajar berbasis proyeksi arus kas bebas perusahaan diskonto (DCF).",
        applicable_markets=["IDX", "US"],
        timeframe="LONG_TERM",
        required_data=["IncomeStatement", "BalanceSheet", "CashFlowStatement"],
        entry_conditions="Harga pasar saat ini berada di bawah nilai intrinsik DCF dengan Margin of Safety >= 25%.",
        invalidation_conditions="Kemunduran struktural marjin laba atau lonjakan hutang (DER > 2.0x).",
        risk_model="Margin of Safety fundamental; diversifikasi lintas 5+ sektor.",
        mechanism_assumptions="Buy and hold; tidak bergantung pada momentum harga intraday.",
    ),
    StrategyMetadata(
        strategy_id="QUALITY_GROWTH",
        name="High ROIC & Free Cash Flow Compounding",
        version="1.0.0",
        family="QUALITY",
        research_purpose="Menyaring perusahaan dengan return modal tinggi (ROIC > 15%), marjin laba kuat, dan neraca bersih.",
        applicable_markets=["IDX"],
        timeframe="LONG_TERM",
        required_data=["FinancialStatements", "HistoricalRatios"],
        entry_conditions="ROIC > 15%, DER < 0.8x, Pertumbuhan FCF positif 3 tahun berturut-turut.",
        invalidation_conditions="Penurunan ROIC di bawah WACC atau beban bunga melebihi laba operasi.",
        risk_model="Fundamental capital preservation.",
        mechanism_assumptions="Main & Development Board only.",
    ),
    StrategyMetadata(
        strategy_id="TURNAROUND_CATALYST",
        name="Earnings Turnaround & Debt Relief",
        version="1.0.0",
        family="EVENT_DRIVEN",
        research_purpose="Mendeteksi perbaikan radikal emiten dari rugi operasional menjadi laba bersih terkonfirmasi.",
        applicable_markets=["IDX"],
        timeframe="1_MONTH - 3_MONTHS",
        required_data=["IncomeStatement", "CorporateEvents", "LiquidityMetrics"],
        entry_conditions="Kuartal rugi berbalik laba positif + restrukturisasi hutang definitif disetujui kreditur.",
        invalidation_conditions="Kembali mencatatkan rugi operasional pada laporan keuangan berikutnya.",
        risk_model="High-volatility risk budgeting (max 1.0% modal per trade).",
        mechanism_assumptions="Hindari saham berstatus suspensi aktif.",
    ),
    StrategyMetadata(
        strategy_id="LIQUIDITY_ACTIVATION",
        name="Micro-Cap Liquidity Awakening",
        version="1.0.0",
        family="MICROSTRUCTURE",
        research_purpose="Mendeteksi saham berkapitalisasi mikro yang mulai aktif ditransaksikan secara konsisten.",
        applicable_markets=["IDX"],
        timeframe="1_WEEK - 2_WEEKS",
        required_data=["EOD_Candles", "MicrostructureProfile"],
        entry_conditions="ADTV 20-hari meningkat > 300% menembus ambang batas likuiditas minimum (Rp 50 Juta) tanpa jeda volume nol.",
        invalidation_conditions="Kembali ke volume nol (0 bar transaksi) atau masuk ke Papan Pemantauan Khusus (FCA).",
        risk_model="Posisi sangat kecil berbanding total pasar (< 5% dari ADTV).",
        mechanism_assumptions="Slippage model wajib diaplikasikan sebelum order.",
    ),
]


class StrategyRegistry:
    """Registry of discoverable and auditable research strategies."""

    def __init__(self) -> None:
        self._strategies = {s.strategy_id: s for s in CANONICAL_STRATEGIES}

    def list_strategies(self) -> list[StrategyMetadata]:
        return list(self._strategies.values())

    def get(self, strategy_id: str) -> StrategyMetadata | None:
        return self._strategies.get(strategy_id.upper())

    def match_strategy(self, horizon: str, goal: str) -> StrategyMetadata:
        """Finds the most appropriate strategy given user horizon and goal."""
        g = goal.upper()
        h = horizon.upper()
        if "INVEST" in g or "PANJANG" in g or "LONG" in h:
            return self._strategies["VALUE_FCFF"]
        if "TURNAROUND" in g:
            return self._strategies["TURNAROUND_CATALYST"]
        if "LIQUIDITY" in g or "MIKRO" in g:
            return self._strategies["LIQUIDITY_ACTIVATION"]
        if "KONTRAK" in g or "EVENT" in g or "PENGUMUMAN" in g or "KATALIS" in g:
            return self._strategies["PAM_SWING"]
        return self._strategies["VCP_BREAKOUT"]
