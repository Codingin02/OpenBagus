"""Multi-Asset Portfolio & Risk Management Engine for OpenBagus.

Features:
1. Dynamic Position Sizing (Fixed Fractional Risk, Kelly Criterion, ATR Volatility, Indonesian Equity Lots vs Crypto Units).
2. Multi-Asset Portfolio Value at Risk (VaR) & CVaR / Expected Shortfall (Parametric, Historical Simulation, Component VaR, Diversification Benefit).
3. Cross-Asset Correlation Analysis (IDX Equities vs Cryptocurrency Cross-Asset Matrix, Rolling Correlation, Diversification Score).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence


TRADING_DAYS_PER_YEAR = 252
Z_SCORES = {
    0.90: 1.28155,
    0.95: 1.64485,
    0.99: 2.32635,
}


@dataclass
class PositionSizeResult:
    capital: float
    risk_pct: float
    risk_amount: float
    entry_price: float
    stop_loss: float
    risk_per_unit: float
    units: float
    lots: int | None
    position_value: float
    allocation_pct: float
    max_loss: float
    asset_type: str
    method: str
    currency: str = "IDR"
    details: dict[str, Any] = field(default_factory=dict)


@dataclass
class PortfolioVaRResult:
    portfolio_value: float
    confidence: float
    horizon_days: int
    portfolio_daily_volatility: float
    portfolio_annual_volatility: float
    parametric_var: float
    parametric_var_pct: float
    historical_var: float
    historical_var_pct: float
    cvar_expected_shortfall: float
    cvar_pct: float
    diversified_risk: float
    undiversified_risk: float
    diversification_benefit_pct: float
    weights: dict[str, float]
    component_var: dict[str, float]
    currency: str = "IDR"
    observations_used: int = 0


@dataclass
class CorrelationMatrixResult:
    assets: list[str]
    matrix: dict[str, dict[str, float]]
    cross_asset_correlations: list[dict[str, Any]]
    average_correlation: float
    diversification_score: float
    highest_pair: tuple[str, str, float]
    lowest_pair: tuple[str, str, float]
    observations_used: int


def _mean(values: Sequence[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def _sample_std(values: Sequence[float]) -> float:
    if len(values) < 2:
        return 0.0
    avg = _mean(values)
    variance = sum((v - avg) ** 2 for v in values) / (len(values) - 1)
    return math.sqrt(max(variance, 0.0))


def _covariance(x: Sequence[float], y: Sequence[float]) -> float:
    n = min(len(x), len(y))
    if n < 2:
        return 0.0
    mx = _mean(x[:n])
    my = _mean(y[:n])
    return sum((x[i] - mx) * (y[i] - my) for i in range(n)) / (n - 1)


def _pearson_corr(x: Sequence[float], y: Sequence[float]) -> float:
    n = min(len(x), len(y))
    if n < 2:
        return 0.0
    std_x = _sample_std(x[:n])
    std_y = _sample_std(y[:n])
    if std_x == 0.0 or std_y == 0.0:
        return 0.0
    cov = _covariance(x[:n], y[:n])
    r = cov / (std_x * std_y)
    return max(-1.0, min(1.0, r))


def _percentile(values: Sequence[float], p: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    idx = (len(ordered) - 1) * p
    lower = math.floor(idx)
    upper = math.ceil(idx)
    if lower == upper:
        return ordered[int(idx)]
    weight = idx - lower
    return ordered[lower] * (1.0 - weight) + ordered[upper] * weight


# =========================================================================
# 1. POSITION SIZING
# =========================================================================

def calculate_position_size(
    capital: float,
    entry_price: float,
    stop_loss: float,
    risk_pct: float = 2.0,
    *,
    asset_type: str = "EQUITY_ID",
    currency: str = "IDR",
    lot_size: int = 100,
    atr: float | None = None,
    atr_multiplier: float = 2.0,
    win_rate: float | None = None,
    reward_risk: float | None = None,
    use_half_kelly: bool = True,
) -> PositionSizeResult:
    """Calculates risk-managed position sizing for Indonesian equities or Crypto.

    Supports:
    - Fixed Fractional Risk (default)
    - ATR-adjusted risk spacing
    - Kelly Criterion sizing recommendations
    - IDX lot constraints (1 lot = 100 shares)
    """
    if capital <= 0 or entry_price <= 0:
        raise ValueError("Capital and entry price must be positive numbers.")

    details: dict[str, Any] = {}
    method = "FIXED_RISK"

    # 1. Kelly adjustment if provided
    effective_risk_pct = risk_pct
    if win_rate is not None and reward_risk is not None and reward_risk > 0:
        p = max(0.01, min(0.99, win_rate))
        q = 1.0 - p
        b = reward_risk
        full_kelly = max(0.0, (p * b - q) / b)
        target_kelly = (full_kelly * 0.5) if use_half_kelly else full_kelly
        kelly_pct = round(target_kelly * 100.0, 2)
        details["full_kelly_pct"] = round(full_kelly * 100.0, 2)
        details["half_kelly_pct"] = kelly_pct
        if kelly_pct > 0:
            effective_risk_pct = min(risk_pct, kelly_pct)
            method = "KELLY_BOUNDED"

    # 2. Risk amount in currency
    risk_amount = capital * (effective_risk_pct / 100.0)

    # 3. Risk per unit (distance to stop loss or ATR)
    if atr and atr > 0:
        risk_per_unit = atr * atr_multiplier
        method = "ATR_VOLATILITY"
        details["atr"] = atr
        details["atr_multiplier"] = atr_multiplier
    else:
        risk_per_unit = abs(entry_price - stop_loss)

    if risk_per_unit <= 0:
        risk_per_unit = entry_price * 0.01  # Minimum 1% safety cushion

    raw_units = risk_amount / risk_per_unit

    # 4. Handle lot-size constraints for IDX equities
    is_equity = asset_type.upper() in ("EQUITY_ID", "EQUITY", "STOCK", "IDX") or currency.upper() == "IDR"
    lots: int | None = None
    if is_equity and lot_size > 0:
        calculated_lots = int(raw_units // lot_size)
        if calculated_lots < 1 and (capital >= entry_price * lot_size):
            calculated_lots = 1  # Minimum 1 lot if affordable
        lots = max(0, calculated_lots)
        units = float(lots * lot_size)
    else:
        units = round(raw_units, 6 if currency.upper() == "USD" else 2)

    position_value = units * entry_price
    # Cap position value at available capital (cash-only, no leverage assumption)
    if position_value > capital:
        if is_equity and lot_size > 0:
            lots = int(capital // (entry_price * lot_size))
            units = float(lots * lot_size)
        else:
            units = round(capital / entry_price, 6 if currency.upper() == "USD" else 2)
        position_value = units * entry_price
        details["capped_by_capital"] = True

    allocation_pct = round((position_value / capital) * 100.0, 2) if capital > 0 else 0.0
    max_loss = round(units * risk_per_unit, 2)

    return PositionSizeResult(
        capital=capital,
        risk_pct=effective_risk_pct,
        risk_amount=round(risk_amount, 2),
        entry_price=entry_price,
        stop_loss=stop_loss,
        risk_per_unit=round(risk_per_unit, 4),
        units=units,
        lots=lots,
        position_value=round(position_value, 2),
        allocation_pct=allocation_pct,
        max_loss=max_loss,
        asset_type=asset_type,
        method=method,
        currency=currency,
        details=details,
    )


# =========================================================================
# 2. MULTI-ASSET PORTFOLIO VALUE AT RISK (VaR)
# =========================================================================

def calculate_portfolio_var(
    weights: Mapping[str, float],
    returns_by_asset: Mapping[str, Sequence[float]],
    portfolio_value: float,
    confidence: float = 0.95,
    horizon_days: int = 1,
    currency: str = "IDR",
) -> PortfolioVaRResult:
    """Calculates Parametric & Historical VaR and CVaR for a multi-asset portfolio.

    Supports mixed portfolios of IDX stocks, Cryptos, and cash.
    """
    if portfolio_value <= 0:
        raise ValueError("Portfolio value must be positive.")
    if not weights:
        raise ValueError("Portfolio weights must not be empty.")

    # Normalize weights
    raw_sum = sum(weights.values())
    if raw_sum <= 0:
        raise ValueError("Sum of weights must be positive.")
    norm_weights = {k: v / raw_sum for k, v in weights.items()}

    assets = [a for a in norm_weights.keys() if a in returns_by_asset and len(returns_by_asset[a]) >= 2]
    if not assets:
        raise ValueError("At least one asset must have two or more return observations.")

    # Align return series length
    min_obs = min(len(returns_by_asset[a]) for a in assets)
    aligned_returns = {a: list(returns_by_asset[a][-min_obs:]) for a in assets}

    # 1. Individual volatilities
    std_by_asset = {a: _sample_std(aligned_returns[a]) for a in assets}

    # 2. Covariance Matrix & Parametric Portfolio Volatility
    cov_matrix: dict[str, dict[str, float]] = {a: {} for a in assets}
    for a1 in assets:
        for a2 in assets:
            cov_matrix[a1][a2] = _covariance(aligned_returns[a1], aligned_returns[a2])

    # Portfolio daily variance: w^T * Sigma * w
    port_var_daily = 0.0
    for a1 in assets:
        w1 = norm_weights[a1]
        for a2 in assets:
            w2 = norm_weights[a2]
            port_var_daily += w1 * w2 * cov_matrix[a1][a2]

    port_daily_std = math.sqrt(max(0.0, port_var_daily))
    port_annual_std = port_daily_std * math.sqrt(TRADING_DAYS_PER_YEAR)

    # Parametric VaR
    z_score = Z_SCORES.get(confidence, 1.64485)
    horizon_multiplier = math.sqrt(max(1, horizon_days))
    parametric_var_pct = z_score * port_daily_std * horizon_multiplier
    parametric_var_amount = portfolio_value * parametric_var_pct

    # 3. Historical Simulation Portfolio Return Series
    hist_port_returns: list[float] = []
    for i in range(min_obs):
        r_day = sum(norm_weights[a] * aligned_returns[a][i] for a in assets)
        hist_port_returns.append(r_day)

    # Historical VaR & CVaR (Expected Shortfall)
    p_tail = 1.0 - confidence
    hist_var_single_day = abs(_percentile(hist_port_returns, p_tail))
    historical_var_pct = hist_var_single_day * horizon_multiplier
    historical_var_amount = portfolio_value * historical_var_pct

    tail_losses = [abs(r) for r in hist_port_returns if r <= -hist_var_single_day]
    cvar_single_day = _mean(tail_losses) if tail_losses else hist_var_single_day
    cvar_pct = cvar_single_day * horizon_multiplier
    cvar_amount = portfolio_value * cvar_pct

    # 4. Diversification Benefit
    undiversified_daily_std = sum(norm_weights[a] * std_by_asset[a] for a in assets)
    undiversified_risk = portfolio_value * (z_score * undiversified_daily_std * horizon_multiplier)
    diversified_risk = parametric_var_amount

    if undiversified_risk > 0:
        div_benefit_pct = max(0.0, ((undiversified_risk - diversified_risk) / undiversified_risk) * 100.0)
    else:
        div_benefit_pct = 0.0

    # 5. Component VaR (Marginal Contribution to Total Risk)
    component_var: dict[str, float] = {}
    if port_daily_std > 0:
        for a in assets:
            # Marginal covariance: (Sigma * w)_a
            cov_w = sum(cov_matrix[a][other] * norm_weights[other] for other in assets)
            marginal_beta = cov_w / (port_daily_std ** 2)
            # Component VaR = weight * marginal_beta * total VaR
            c_var = norm_weights[a] * marginal_beta * parametric_var_amount
            component_var[a] = round(c_var, 2)
    else:
        for a in assets:
            component_var[a] = 0.0

    return PortfolioVaRResult(
        portfolio_value=portfolio_value,
        confidence=confidence,
        horizon_days=horizon_days,
        portfolio_daily_volatility=round(port_daily_std, 6),
        portfolio_annual_volatility=round(port_annual_std, 4),
        parametric_var=round(parametric_var_amount, 2),
        parametric_var_pct=round(parametric_var_pct * 100.0, 2),
        historical_var=round(historical_var_amount, 2),
        historical_var_pct=round(historical_var_pct * 100.0, 2),
        cvar_expected_shortfall=round(cvar_amount, 2),
        cvar_pct=round(cvar_pct * 100.0, 2),
        diversified_risk=round(diversified_risk, 2),
        undiversified_risk=round(undiversified_risk, 2),
        diversification_benefit_pct=round(div_benefit_pct, 2),
        weights={a: round(norm_weights[a], 4) for a in assets},
        component_var=component_var,
        currency=currency,
        observations_used=min_obs,
    )


# =========================================================================
# 3. CROSS-ASSET CORRELATION MATRIX (IDX EQUITIES VS CRYPTO)
# =========================================================================

def calculate_correlation_matrix(
    returns_by_asset: Mapping[str, Sequence[float]],
    idx_symbols: Sequence[str] | None = None,
    crypto_symbols: Sequence[str] | None = None,
) -> CorrelationMatrixResult:
    """Calculates correlation matrix across assets and isolates IDX-Crypto cross-correlation."""
    assets = [a for a, rets in returns_by_asset.items() if len(rets) >= 2]
    if len(assets) < 2:
        raise ValueError("At least two assets with returns are required for correlation matrix.")

    min_obs = min(len(returns_by_asset[a]) for a in assets)
    aligned = {a: list(returns_by_asset[a][-min_obs:]) for a in assets}

    matrix: dict[str, dict[str, float]] = {a: {} for a in assets}
    pair_values: list[tuple[str, str, float]] = []

    for i, a1 in enumerate(assets):
        for j, a2 in enumerate(assets):
            if a1 == a2:
                matrix[a1][a2] = 1.0
            else:
                corr = _pearson_corr(aligned[a1], aligned[a2])
                matrix[a1][a2] = round(corr, 4)
                if i < j:
                    pair_values.append((a1, a2, corr))

    # Cross-asset correlations (e.g. IDX vs Crypto)
    idx_set = set(idx_symbols or [])
    crypto_set = set(crypto_symbols or [])

    cross_list: list[dict[str, Any]] = []
    for a1, a2, corr in pair_values:
        is_cross = (a1 in idx_set and a2 in crypto_set) or (a2 in idx_set and a1 in crypto_set)
        if is_cross or not (idx_set and crypto_set):
            cross_list.append({
                "pair": f"{a1} - {a2}",
                "asset_1": a1,
                "asset_2": a2,
                "correlation": round(corr, 4),
                "is_cross_asset": is_cross,
                "relationship": "POS_STRONG" if corr > 0.6 else ("NEG_STRONG" if corr < -0.6 else "DECOUPLED" if abs(corr) <= 0.25 else "MODERATE"),
            })

    # Summary metrics
    avg_corr = _mean([p[2] for p in pair_values]) if pair_values else 0.0
    sorted_pairs = sorted(pair_values, key=lambda item: item[2])
    lowest_pair = sorted_pairs[0] if sorted_pairs else ("", "", 0.0)
    highest_pair = sorted_pairs[-1] if sorted_pairs else ("", "", 0.0)

    # Diversification Score (1.0 = perfect zero/negative correlation, 0.0 = completely correlated)
    div_score = max(0.0, min(1.0, (1.0 - max(0.0, avg_corr))))

    return CorrelationMatrixResult(
        assets=assets,
        matrix=matrix,
        cross_asset_correlations=cross_list,
        average_correlation=round(avg_corr, 4),
        diversification_score=round(div_score, 4),
        highest_pair=(highest_pair[0], highest_pair[1], round(highest_pair[2], 4)),
        lowest_pair=(lowest_pair[0], lowest_pair[1], round(lowest_pair[2], 4)),
        observations_used=min_obs,
    )


# =========================================================================
# 4. TEXTUAL / TERMINAL FORMATTERS
# =========================================================================

def format_position_size_summary(result: PositionSizeResult) -> str:
    """Renders a clean terminal summary of risk position sizing."""
    curr = result.currency.upper()
    lines = [
        "----------------------------------------------------------------",
        f"  OpenBagus Risk Engine - Position Sizing ({result.asset_type})",
        "----------------------------------------------------------------",
        f"  Modal / Capital      : {curr} {result.capital:,.2f}",
        f"  Toleransi Risiko     : {result.risk_pct:.2f}% ({curr} {result.risk_amount:,.2f})",
        f"  Harga Masuk (Entry)  : {curr} {result.entry_price:,.2f}",
        f"  Stop Loss            : {curr} {result.stop_loss:,.2f}",
        f"  Jarak Risiko / Unit  : {curr} {result.risk_per_unit:,.2f}",
        "----------------------------------------------------------------",
    ]
    if result.lots is not None:
        lines.append(f"  Rekomendasi Alokasi  : {result.lots} Lot ({int(result.units):,} lembar saham)")
    else:
        lines.append(f"  Rekomendasi Alokasi  : {result.units} Unit")

    lines.extend([
        f"  Nilai Posisi         : {curr} {result.position_value:,.2f}",
        f"  Porsi Portofolio     : {result.allocation_pct:.2f}% dari total modal",
        f"  Maksimum Kerugian    : {curr} {result.max_loss:,.2f} jika hit stop loss",
        f"  Metode Perhitungan   : {result.method}",
    ])
    if result.details.get("half_kelly_pct"):
        lines.append(f"  Saran Half-Kelly     : {result.details['half_kelly_pct']}% modal")
    lines.append("----------------------------------------------------------------")
    return "\n".join(lines)


def format_portfolio_var_summary(result: PortfolioVaRResult) -> str:
    """Renders a clean terminal summary of multi-asset Value at Risk."""
    curr = result.currency.upper()
    conf_pct = int(result.confidence * 100)
    lines = [
        "----------------------------------------------------------------",
        f"  OpenBagus Portfolio Risk - Value at Risk ({conf_pct}% / {result.horizon_days} Hari)",
        "----------------------------------------------------------------",
        f"  Nilai Portofolio     : {curr} {result.portfolio_value:,.2f}",
        f"  Volatilitas Harian   : {result.portfolio_daily_volatility * 100:.2f}%",
        f"  Volatilitas Tahunan  : {result.portfolio_annual_volatility * 100:.2f}%",
        "----------------------------------------------------------------",
        f"  Parametric VaR ({conf_pct}%) : {curr} {result.parametric_var:,.2f} ({result.parametric_var_pct:.2f}%)",
        f"  Historical VaR ({conf_pct}%): {curr} {result.historical_var:,.2f} ({result.historical_var_pct:.2f}%)",
        f"  Expected Shortfall   : {curr} {result.cvar_expected_shortfall:,.2f} ({result.cvar_pct:.2f}% CVaR)",
        "----------------------------------------------------------------",
        f"  Efek Diversifikasi   : {result.diversification_benefit_pct:.2f}% penurunan risiko",
        f"  Risiko Undiversified : {curr} {result.undiversified_risk:,.2f}",
        "  Kontribusi Risiko per Aset (Component VaR):",
    ]
    for asset, c_var in result.component_var.items():
        w = result.weights.get(asset, 0.0) * 100.0
        lines.append(f"    - {asset:<6} (Bobot {w:>5.1f}%): {curr} {c_var:>12,.2f}")
    lines.append("----------------------------------------------------------------")
    return "\n".join(lines)


def format_correlation_matrix_table(result: CorrelationMatrixResult) -> str:
    """Renders a formatted cross-asset correlation matrix table."""
    assets = result.assets
    header = f"  {'Aset':<8} " + " ".join(f"{a:>7}" for a in assets)
    sep = "  " + "-" * (8 + len(assets) * 8)
    lines = [
        "----------------------------------------------------------------",
        "  OpenBagus Multi-Asset - Matriks Korelasi IHSG & Kripto",
        "----------------------------------------------------------------",
        header,
        sep,
    ]
    for a1 in assets:
        row = f"  {a1:<8} " + " ".join(f"{result.matrix[a1][a2]:>7.2f}" for a2 in assets)
        lines.append(row)
    lines.append(sep)
    lines.append(f"  Rata-rata Korelasi   : {result.average_correlation:.4f}")
    lines.append(f"  Skor Diversifikasi   : {result.diversification_score * 100:.1f} / 100 (Makin tinggi makin terdispersi)")
    if result.lowest_pair[0]:
        lines.append(f"  Korelasi Terendah    : {result.lowest_pair[0]} & {result.lowest_pair[1]} ({result.lowest_pair[2]:.2f})")
    if result.highest_pair[0]:
        lines.append(f"  Korelasi Tertinggi   : {result.highest_pair[0]} & {result.highest_pair[1]} ({result.highest_pair[2]:.2f})")
    lines.append("----------------------------------------------------------------")
    return "\n".join(lines)
