"""OpenBagus Experimental Lunar & Astronomical Cycle Research Engine.

Provides public USNO lunar phase data and deterministic synodic month calculation.
STRICT RULE: This module is purely experimental and has ZERO (0%) DECISION WEIGHT
in production QuantEngine trade and allocation decisions.
"""

from __future__ import annotations

import math
from datetime import datetime, timezone
from dataclasses import dataclass, field
from typing import Any, Sequence


SYNODIC_MONTH_DAYS = 29.53058867  # Mean length of synodic lunar cycle
KNOWN_NEW_MOON_EPOCH = datetime(2024, 1, 11, 11, 57, tzinfo=timezone.utc)  # Reference Jan 11, 2024 New Moon


@dataclass
class LunarPhaseInfo:
    phase_name: str  # New Moon | Waxing Crescent | First Quarter | Waxing Gibbous | Full Moon | Waning Gibbous | Last Quarter | Waning Crescent
    phase_ratio: float  # 0.0 to 1.0 (0.0 = New Moon, 0.5 = Full Moon)
    illumination_pct: float  # 0.0% to 100.0%
    days_since_new_moon: float
    next_full_moon_days: float
    next_new_moon_days: float
    status: str = "EXPERIMENTAL"
    decision_weight: str = "0%"
    disclaimer: str = (
        "FAKTOR EKSPERIMENTAL: Data siklus bulan ini murni untuk riset statistik "
        "dan memiliki bobot 0% (tidak mempengaruhi keputusan order atau rekomendasi)."
    )


@dataclass
class LunarHypothesisTestResult:
    asset_symbol: str
    sample_size_candles: int
    full_moon_samples: int
    new_moon_samples: int
    full_moon_mean_return_pct: float
    new_moon_mean_return_pct: float
    return_diff_pct: float
    t_statistic: float
    p_value: float
    is_statistically_significant: bool  # True if p < 0.05
    conclusion: str


class LunarCycleResearch:
    """Hypothesis testing engine for astronomical cycles in financial time series."""

    @staticmethod
    def get_lunar_phase(dt: datetime | None = None) -> LunarPhaseInfo:
        """Calculates deterministic lunar phase and illumination percentage."""
        if dt is None:
            dt = datetime.now(timezone.utc)
        elif dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        else:
            dt = dt.astimezone(timezone.utc)

        delta_days = (dt - KNOWN_NEW_MOON_EPOCH).total_seconds() / 86400.0
        phase_ratio = (delta_days % SYNODIC_MONTH_DAYS) / SYNODIC_MONTH_DAYS
        days_in_cycle = phase_ratio * SYNODIC_MONTH_DAYS

        # Illumination follows sinusoidal curve between 0.0 and 1.0
        # phase_ratio 0.0 = New Moon (0%), 0.5 = Full Moon (100%)
        illumination = (1.0 - math.cos(2.0 * math.pi * phase_ratio)) / 2.0 * 100.0

        if phase_ratio < 0.06 or phase_ratio >= 0.94:
            phase_name = "New Moon"
        elif 0.06 <= phase_ratio < 0.22:
            phase_name = "Waxing Crescent"
        elif 0.22 <= phase_ratio < 0.28:
            phase_name = "First Quarter"
        elif 0.28 <= phase_ratio < 0.44:
            phase_name = "Waxing Gibbous"
        elif 0.44 <= phase_ratio < 0.56:
            phase_name = "Full Moon"
        elif 0.56 <= phase_ratio < 0.72:
            phase_name = "Waning Gibbous"
        elif 0.72 <= phase_ratio < 0.78:
            phase_name = "Last Quarter"
        else:
            phase_name = "Waning Crescent"

        days_to_full = (0.5 - phase_ratio) * SYNODIC_MONTH_DAYS if phase_ratio <= 0.5 else (1.5 - phase_ratio) * SYNODIC_MONTH_DAYS
        days_to_new = (1.0 - phase_ratio) * SYNODIC_MONTH_DAYS

        return LunarPhaseInfo(
            phase_name=phase_name,
            phase_ratio=round(phase_ratio, 4),
            illumination_pct=round(illumination, 1),
            days_since_new_moon=round(days_in_cycle, 2),
            next_full_moon_days=round(days_to_full, 2),
            next_new_moon_days=round(days_to_new, 2),
            status="EXPERIMENTAL",
            decision_weight="0%",
        )

    @classmethod
    def test_lunar_effect_on_returns(
        cls,
        symbol: str,
        candles: Sequence[dict[str, Any]],
        forward_bars: int = 3,
    ) -> LunarHypothesisTestResult:
        """Performs two-sample t-test comparing forward returns during Full Moon vs New Moon.

        Enforces rigorous statistical standard: if p >= 0.05, hypothesis is rejected.
        """
        sym = symbol.upper()
        if len(candles) < 30:
            return LunarHypothesisTestResult(
                asset_symbol=sym,
                sample_size_candles=len(candles),
                full_moon_samples=0,
                new_moon_samples=0,
                full_moon_mean_return_pct=0.0,
                new_moon_mean_return_pct=0.0,
                return_diff_pct=0.0,
                t_statistic=0.0,
                p_value=1.0,
                is_statistically_significant=False,
                conclusion="Data historis tidak mencukupi untuk uji hipotesis (minimal 30 bar).",
            )

        full_moon_returns: list[float] = []
        new_moon_returns: list[float] = []

        for i in range(len(candles) - forward_bars):
            c = candles[i]
            ts = c.get("time") or c.get("timestamp") or 0
            if ts > 1e11:  # milliseconds
                ts /= 1000.0
            dt = datetime.fromtimestamp(ts, tz=timezone.utc)
            phase = cls.get_lunar_phase(dt)

            c_close = float(c.get("close", 0))
            fwd_close = float(candles[i + forward_bars].get("close", 0))
            if c_close <= 0 or fwd_close <= 0:
                continue

            fwd_ret = ((fwd_close - c_close) / c_close) * 100.0

            if phase.phase_name == "Full Moon":
                full_moon_returns.append(fwd_ret)
            elif phase.phase_name == "New Moon":
                new_moon_returns.append(fwd_ret)

        n_full = len(full_moon_returns)
        n_new = len(new_moon_returns)

        if n_full < 3 or n_new < 3:
            return LunarHypothesisTestResult(
                asset_symbol=sym,
                sample_size_candles=len(candles),
                full_moon_samples=n_full,
                new_moon_samples=n_new,
                full_moon_mean_return_pct=0.0,
                new_moon_mean_return_pct=0.0,
                return_diff_pct=0.0,
                t_statistic=0.0,
                p_value=1.0,
                is_statistically_significant=False,
                conclusion="Sampel fase bulan spesifik dalam rentang data tidak mencukupi untuk uji inferensi.",
            )

        mean_full = sum(full_moon_returns) / n_full
        mean_new = sum(new_moon_returns) / n_new
        diff = mean_full - mean_new

        var_full = sum((x - mean_full) ** 2 for x in full_moon_returns) / (n_full - 1)
        var_new = sum((x - mean_new) ** 2 for x in new_moon_returns) / (n_new - 1)

        se_diff = math.sqrt((var_full / n_full) + (var_new / n_new))
        t_stat = (diff / se_diff) if se_diff > 1e-8 else 0.0

        # Approximate two-tailed p-value via normal distribution for large samples or simple Gaussian CDF
        # 1 - erf(|t| / sqrt(2))
        abs_t = abs(t_stat)
        p_val = math.erfc(abs_t / math.sqrt(2.0))

        is_sig = p_val < 0.05
        if is_sig:
            conclusion = (
                f"Terdapat perbedaan return yang signifikan secara statistik (t={t_stat:.2f}, p={p_val:.4f} < 0.05). "
                f"Namun demikian, sesuai kebijakan integritas OpenBagus, faktor ini tetap diberi bobot 0%."
            )
        else:
            conclusion = (
                f"Hipotesis ditolak: return Full Moon ({mean_full:+.2f}%) dan New Moon ({mean_new:+.2f}%) "
                f"tidak berbeda secara signifikan (t={t_stat:.2f}, p-value={p_val:.3f} >= 0.05). "
                f"Perbedaan berada dalam batas fluktuasi acak (noise). Bobot keputusan: 0%."
            )

        return LunarHypothesisTestResult(
            asset_symbol=sym,
            sample_size_candles=len(candles),
            full_moon_samples=n_full,
            new_moon_samples=n_new,
            full_moon_mean_return_pct=round(mean_full, 3),
            new_moon_mean_return_pct=round(mean_new, 3),
            return_diff_pct=round(diff, 3),
            t_statistic=round(t_stat, 3),
            p_value=round(p_val, 4),
            is_statistically_significant=is_sig,
            conclusion=conclusion,
        )
