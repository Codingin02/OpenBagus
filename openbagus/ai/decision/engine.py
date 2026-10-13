"""Structured Decision Intelligence and Analytical Synthesis Engine."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class DecisionSynthesis:
    subject: str
    horizon: str
    strategy_name: str
    observations: list[str] = field(default_factory=list)
    interpretations: list[str] = field(default_factory=list)
    uncertainties: list[str] = field(default_factory=list)
    risks_and_invalidations: list[str] = field(default_factory=list)
    decision_alternatives: list[str] = field(default_factory=list)
    confidence_level: str = "MODERATE"  # "HIGH" | "MODERATE" | "LOW" (evidence-grounded)

    def to_markdown(self) -> str:
        lines = [
            f"### Sintesis Riset & Pengambilan Keputusan: {self.subject}",
            f"- **Horizon Riset:** {self.horizon}  |  **Kerangka Strategi:** {self.strategy_name}  |  **Tingkat Keyakinan Bukti:** `{self.confidence_level}`",
            "",
            "#### 1. Fakta Terverifikasi (Observations)",
        ]
        for obs in self.observations:
            lines.append(f"- {obs}")

        lines.extend(["", "#### 2. Interpretasi & Analisis (Interpretation)"])
        for interp in self.interpretations:
            lines.append(f"- {interp}")

        if self.uncertainties:
            lines.extend(["", "#### 3. Kesenjangan Data & Ketidakpastian (Data Gaps / Uncertainties)"])
            for unc in self.uncertainties:
                lines.append(f"- {unc}")

        lines.extend(["", "#### 4. Risiko & Batas Invalidasi (Risks & Invalidation Conditions)"])
        for rsk in self.risks_and_invalidations:
            lines.append(f"- {rsk}")

        lines.extend(["", "#### 5. Opsi Tindakan Rasional (Actionable Alternatives)"])
        for act in self.decision_alternatives:
            lines.append(f"- {act}")

        return "\n".join(lines)


class DecisionIntelligenceEngine:
    """Transforms raw tool outputs and market evidence into balanced, skeptical decision support."""

    @classmethod
    def synthesize_swing_decision(
        cls,
        ticker: str,
        price_data: dict[str, Any],
        micro_data: dict[str, Any],
        events_data: dict[str, Any],
        indicators_data: dict[str, Any],
        horizon: str = "1_WEEK - 2_WEEKS",
    ) -> DecisionSynthesis:
        obs: list[str] = []
        interp: list[str] = []
        unc: list[str] = []
        risks: list[str] = []
        alts: list[str] = []

        px = price_data.get("close")
        if px:
            obs.append(f"Harga EOD terakhir terverifikasi di level Rp {px:,.0f} ({price_data.get('change_pct', 0.0):+.1f}%).")
        else:
            unc.append("Data harga EOD lokal belum tersedia; analisis menggunakan estimasi referensi.")

        # Microstructure evaluation
        board = micro_data.get("board", "REGULAR")
        adtv = micro_data.get("adtv_20d", 0.0)
        elig = micro_data.get("execution_eligible", True)
        if adtv > 0:
            obs.append(f"ADTV 20-hari tercatat Rp {adtv:,.0f} di Papan {board}.")
        if not elig:
            reasons = ", ".join(micro_data.get("rejection_reasons", ["Likuiditas terbatas"]))
            risks.append(f"[RISK GATE] Aset ditolak untuk eksekusi langsung: {reasons}.")

        # Events evaluation
        ev_list = events_data.get("events", [])
        if ev_list:
            top_ev = ev_list[0]
            obs.append(f"Keterbukaan informasi: '{top_ev.get('title')}' (Skor sentimen: {top_ev.get('impact_score', 0):+.0f}).")
            rel_pct = top_ev.get("relative_materiality_pct")
            if rel_pct:
                interp.append(f"Materialitas relatif kontrak/peristiwa tercatat {rel_pct:.1f}% terhadap baseline keuangan emiten.")
        else:
            interp.append("Tidak terdapat keterbukaan informasi material baru dalam radar terkini.")

        # Technical indicators
        rsi = indicators_data.get("rsi_14")
        if rsi is not None:
            obs.append(f"RSI 14-hari berada di level {rsi:.1f}.")
            if rsi > 70:
                risks.append("RSI memasuki area jenuh beli (overbought); risiko pullback sementara.")
            elif rsi < 30:
                interp.append("RSI berada di area jenuh jual (oversold); potensi technical rebound.")

        # Invalidation & Alternatives
        ara = micro_data.get("ara_limit")
        arb = micro_data.get("arb_limit")
        if arb:
            risks.append(f"Batas auto-rejection bawah (ARB) berada di Rp {arb:,.0f}; invalidasi terjadi jika harga menembus support terdekat.")

        if elig:
            alts.append("Opsi 1: Tunggu konfirmasi breakout volume pada pembukaan sesi perdagangan sebelum entri bertahap.")
            alts.append("Opsi 2: Batasi risiko maksimal 2.0% modal portofolio dengan pembulatan lot standar 100 lembar.")
        else:
            alts.append("Opsi Alternatif: Alihkan riset ke emiten yang lebih likuid di sektor yang sama untuk menghindari slippage tinggi.")
            alts.append("Opsi Pantau: Masukkan ke dalam watchlist radar dan hindari eksekusi riil saat likuiditas masih beku.")

        return DecisionSynthesis(
            subject=ticker.upper(),
            horizon=horizon,
            strategy_name="Event-Driven Post-Announcement Momentum",
            observations=obs,
            interpretations=interp,
            uncertainties=unc,
            risks_and_invalidations=risks,
            decision_alternatives=alts,
            confidence_level="HIGH" if elig and px and ev_list else "MODERATE",
        )

    @classmethod
    def synthesize_fundamental_decision(
        cls,
        ticker: str,
        statement_data: dict[str, Any],
        ratios_data: dict[str, Any],
        valuation_data: dict[str, Any],
        horizon: str = "LONG_TERM",
    ) -> DecisionSynthesis:
        obs: list[str] = []
        interp: list[str] = []
        unc: list[str] = []
        risks: list[str] = []
        alts: list[str] = []

        period = statement_data.get("period", "LATEST")
        obs.append(f"Data keuangan mengacu pada laporan resmi periode {period}.")

        der = ratios_data.get("der")
        roe = ratios_data.get("roe_pct")
        if der is not None:
            obs.append(f"Debt-to-Equity Ratio (DER): {der:.2f}x.")
            if der > 1.5:
                risks.append("Leverage relatif tinggi (DER > 1.5x); beban bunga dapat membebani margin laba di siklus suku bunga tinggi.")
            else:
                interp.append("Struktur modal sehat dan solvabilitas terjaga dengan baik.")

        if roe is not None:
            obs.append(f"Return on Equity (ROE): {roe:.1f}%.")

        iv = valuation_data.get("dcf_intrinsic_value")
        px = valuation_data.get("market_price")
        mos = valuation_data.get("margin_of_safety_pct")
        if iv and px:
            obs.append(f"Harga pasar Rp {px:,.0f} vs Nilai Intrinsik DCF Rp {iv:,.0f} (Margin of Safety: {mos:+.1f}%).")
            if mos and mos >= 20.0:
                interp.append(f"Emiten berada di zona undervalued dengan margin of safety memadai ({mos:+.1f}%).")
            elif mos and mos < 0:
                risks.append(f"Harga pasar diperdagangkan di atas estimasi nilai wajar intrinsik (overvalued {-mos:.1f}%).")
        else:
            unc.append("Valuasi DCF membutuhkan kelengkapan riwayat arus kas operasi dan belanja modal.")

        alts.append("Opsi 1: Evaluasi akumulasi bertahap pada batas bawah margin of safety.")
        alts.append("Opsi 2: Lakukan perbandingan fundamental dengan kompetitor seindustri sebelum alokasi penuh.")

        return DecisionSynthesis(
            subject=ticker.upper(),
            horizon=horizon,
            strategy_name="Damodaran DCF & Fundamental Quality Investing",
            observations=obs,
            interpretations=interp,
            uncertainties=unc,
            risks_and_invalidations=risks,
            decision_alternatives=alts,
            confidence_level="HIGH" if iv and der is not None else "MODERATE",
        )
