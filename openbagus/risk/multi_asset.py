"""Multi-Asset Portfolio & Risk Management Engine for OpenBagus.

Features:
1. Dynamic Position Sizing:
   - Hard risk invariant: estimated worst-case loss at stop <= capital * risk_pct / 100.
   - Strict downward lot rounding (never force 1 lot if it violates risk budget).
   - Zero-lot rejection with explicit risk excess when minimum lot exceeds budget.
   - Stop geometry validation (stop < entry for longs; no fake 1% cushion).
   - Optional transaction fees and slippage modeling.
   - Kelly criterion validation (zero or negative edge cancels risk allocation).
2. Multi-Asset Portfolio Value at Risk (VaR) & CVaR / Expected Shortfall:
   - Parametric VaR with explicit horizon scaling assumptions.
   - Empirical left-tail Historical VaR and Expected Shortfall.
   - True Component VaR decomposition (supporting negative/hedging contributions).
   - Diversification Benefit calculation.
3. Cross-Asset Correlation Analysis:
   - Date-aligned time series (mismatched calendars, e.g. 7-day crypto vs weekday IDX, aligned strictly on matching observation dates).
   - Pairwise alignment metadata reporting start date, end date, and common interval count.
   - FX normalization support.
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
    trade_eligible: bool = True
    rejection_reason: str = ""
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
    alignment_metadata: dict[str, Any] = field(default_factory=dict)


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
    alignment_metadata: dict[str, Any] = field(default_factory=dict)


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
    include_costs: bool = False,
    buy_fee_pct: float | None = None,
    sell_fee_pct: float | None = None,
    slippage_pct: float = 0.0,
) -> PositionSizeResult:
    """Calculates risk-managed position sizing for Indonesian equities or Crypto.

    Hard Invariant:
    estimated_worst_case_loss_at_stop <= capital * risk_pct / 100.

    Strictly rounds down to lot boundaries for Indonesian equities.
    If 1 lot exceeds the risk budget, returns 0 lots and marks trade ineligible.
    """
    if capital <= 0 or entry_price <= 0:
        raise ValueError("Capital and entry price must be positive numbers.")

    is_equity = asset_type.upper() in ("EQUITY_ID", "EQUITY", "STOCK", "IDX") or currency.upper() == "IDR"
    details: dict[str, Any] = {}
    method = "FIXED_RISK"

    # 1. Stop loss geometry validation (for long position)
    has_atr_stop = bool(atr and atr > 0)
    if not has_atr_stop and stop_loss >= entry_price:
        return PositionSizeResult(
            capital=capital,
            risk_pct=risk_pct,
            risk_amount=round(capital * (risk_pct / 100.0), 2),
            entry_price=entry_price,
            stop_loss=stop_loss,
            risk_per_unit=0.0,
            units=0.0,
            lots=0 if is_equity else None,
            position_value=0.0,
            allocation_pct=0.0,
            max_loss=0.0,
            asset_type=asset_type,
            method="INVALID_STOP",
            currency=currency,
            trade_eligible=False,
            rejection_reason="Stop loss harus berada di bawah harga entry untuk posisi long.",
            details={"error": "INVALID_STOP_GEOMETRY"},
        )

    # 2. Kelly adjustment if win rate and reward/risk provided
    effective_risk_pct = risk_pct
    if win_rate is not None and reward_risk is not None:
        if win_rate <= 0 or reward_risk <= 0:
            full_kelly = 0.0
        else:
            p = max(0.0, min(1.0, win_rate))
            q = 1.0 - p
            b = reward_risk
            full_kelly = (p * b - q) / b

        if full_kelly <= 0:
            return PositionSizeResult(
                capital=capital,
                risk_pct=0.0,
                risk_amount=0.0,
                entry_price=entry_price,
                stop_loss=stop_loss,
                risk_per_unit=0.0,
                units=0.0,
                lots=0 if is_equity else None,
                position_value=0.0,
                allocation_pct=0.0,
                max_loss=0.0,
                asset_type=asset_type,
                method="KELLY_ZERO_EDGE",
                currency=currency,
                trade_eligible=False,
                rejection_reason="Strategi tidak memiliki edge statistik positif (Kelly <= 0). Alokasi risiko dibatalkan.",
                details={"full_kelly_pct": round(full_kelly * 100.0, 2), "half_kelly_pct": 0.0},
            )

        target_kelly = (full_kelly * 0.5) if use_half_kelly else full_kelly
        kelly_pct = round(target_kelly * 100.0, 2)
        details["full_kelly_pct"] = round(full_kelly * 100.0, 2)
        details["half_kelly_pct"] = kelly_pct
        effective_risk_pct = min(risk_pct, kelly_pct)
        method = "KELLY_BOUNDED"

    # 3. Risk budget calculation
    risk_amount = capital * (effective_risk_pct / 100.0)

    # 4. Risk per unit calculation (price distance + optional transaction costs)
    if has_atr_stop:
        price_risk_per_unit = atr * atr_multiplier  # type: ignore
        method = "ATR_VOLATILITY"
        details["atr"] = atr
        details["atr_multiplier"] = atr_multiplier
    else:
        price_risk_per_unit = entry_price - stop_loss

    if include_costs:
        b_fee = 0.15 if buy_fee_pct is None and is_equity else (0.05 if buy_fee_pct is None else buy_fee_pct)
        s_fee = 0.25 if sell_fee_pct is None and is_equity else (0.05 if sell_fee_pct is None else sell_fee_pct)
        fee_cost = (entry_price * (b_fee + slippage_pct) / 100.0) + (stop_loss * (s_fee + slippage_pct) / 100.0)
        risk_per_unit = price_risk_per_unit + fee_cost
        details["fees_modeled"] = True
        details["fee_per_unit"] = round(fee_cost, 4)
    else:
        risk_per_unit = price_risk_per_unit

    if risk_per_unit <= 0:
        return PositionSizeResult(
            capital=capital,
            risk_pct=effective_risk_pct,
            risk_amount=round(risk_amount, 2),
            entry_price=entry_price,
            stop_loss=stop_loss,
            risk_per_unit=0.0,
            units=0.0,
            lots=0 if is_equity else None,
            position_value=0.0,
            allocation_pct=0.0,
            max_loss=0.0,
            asset_type=asset_type,
            method="ZERO_RISK_PER_UNIT",
            currency=currency,
            trade_eligible=False,
            rejection_reason="Jarak risiko per unit tidak valid (<= 0).",
        )

    raw_units = risk_amount / risk_per_unit

    # 5. Handle lot constraints (Strict round-down; never exceed risk budget)
    lots: int | None = None
    if is_equity and lot_size > 0:
        calculated_lots = int(raw_units // lot_size)  # Always round DOWN
        if calculated_lots < 1:
            min_lot_loss = float(lot_size * risk_per_unit)
            excess_risk = min_lot_loss - risk_amount
            return PositionSizeResult(
                capital=capital,
                risk_pct=effective_risk_pct,
                risk_amount=round(risk_amount, 2),
                entry_price=entry_price,
                stop_loss=stop_loss,
                risk_per_unit=round(risk_per_unit, 4),
                units=0.0,
                lots=0,
                position_value=0.0,
                allocation_pct=0.0,
                max_loss=0.0,
                asset_type=asset_type,
                method=method,
                currency=currency,
                trade_eligible=False,
                rejection_reason=(
                    f"Ukuran minimum 1 lot ({lot_size} lembar) menghasilkan potensi rugi "
                    f"{currency} {min_lot_loss:,.0f}, melebihi batas anggaran risiko {currency} {risk_amount:,.0f} "
                    f"(kelebihan risiko {currency} {excess_risk:,.0f}). Order ditolak demi menjaga batas modal."
                ),
                details={
                    "min_lot_loss": round(min_lot_loss, 2),
                    "excess_risk": round(excess_risk, 2),
                    "trade_eligible": False,
                },
            )
        lots = calculated_lots
        units = float(lots * lot_size)
    else:
        units = round(raw_units, 6 if currency.upper() == "USD" else 2)

    position_value = units * entry_price

    # 6. Check cash affordability limit
    if position_value > capital:
        if is_equity and lot_size > 0:
            lots = int(capital // (entry_price * lot_size))
            if lots < 1:
                return PositionSizeResult(
                    capital=capital,
                    risk_pct=effective_risk_pct,
                    risk_amount=round(risk_amount, 2),
                    entry_price=entry_price,
                    stop_loss=stop_loss,
                    risk_per_unit=round(risk_per_unit, 4),
                    units=0.0,
                    lots=0,
                    position_value=0.0,
                    allocation_pct=0.0,
                    max_loss=0.0,
                    asset_type=asset_type,
                    method=method,
                    currency=currency,
                    trade_eligible=False,
                    rejection_reason=f"Modal tunai {currency} {capital:,.0f} tidak mencukupi untuk membeli 1 lot ({lot_size} lembar) seharga {currency} {entry_price * lot_size:,.0f}.",
                    details={"capped_by_capital": True, "trade_eligible": False},
                )
            units = float(lots * lot_size)
        else:
            units = round(capital / entry_price, 6 if currency.upper() == "USD" else 2)
        position_value = units * entry_price
        details["capped_by_capital"] = True

    allocation_pct = round((position_value / capital) * 100.0, 2) if capital > 0 else 0.0
    max_loss = round(units * risk_per_unit, 2)

    # Invariant assertion
    if max_loss > risk_amount + 0.05:
        # Edge safety guard
        units = 0.0
        lots = 0 if is_equity else None
        max_loss = 0.0

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
        trade_eligible=True,
        rejection_reason="",
        details=details,
    )


# =========================================================================
# 2. DATE ALIGNMENT HELPER FOR MULTI-ASSET RETURNS
# =========================================================================

def align_asset_returns(
    returns_by_asset: Mapping[str, Any],
    dates_by_asset: Mapping[str, Sequence[str]] | None = None,
    min_observations: int = 2,
) -> tuple[list[str], dict[str, list[float]], dict[str, Any]]:
    """Aligns multi-asset return series by observation dates.

    Ensures that mismatched calendars (e.g. 7-day crypto vs weekday IDX)
    are correlated strictly on matching observation dates rather than by positional index.
    """
    assets = [a for a, rets in returns_by_asset.items() if len(rets) >= min_observations]
    if len(assets) < 1:
        raise ValueError("At least one asset with sufficient returns is required.")

    parsed: dict[str, dict[str, float]] = {}
    has_explicit_dates = False

    for a in assets:
        series = returns_by_asset[a]
        if isinstance(series, dict):
            has_explicit_dates = True
            parsed[a] = {str(k): float(v) for k, v in series.items()}
        elif dates_by_asset and a in dates_by_asset:
            has_explicit_dates = True
            d_list = list(dates_by_asset[a])
            r_list = list(series)
            n = min(len(d_list), len(r_list))
            parsed[a] = {str(d_list[i]): float(r_list[i]) for i in range(n)}
        elif series and isinstance(series[0], (tuple, list)) and len(series[0]) == 2:
            has_explicit_dates = True
            parsed[a] = {str(item[0]): float(item[1]) for item in series}
        else:
            r_list = [float(v) for v in series]
            parsed[a] = {f"obs_{i:06d}": r_list[i] for i in range(len(r_list))}

    if has_explicit_dates and len(assets) > 1:
        common_set = set(parsed[assets[0]].keys())
        for a in assets[1:]:
            common_set.intersection_update(parsed[a].keys())
        common_dates = sorted(common_set)
    elif has_explicit_dates and len(assets) == 1:
        common_dates = sorted(parsed[assets[0]].keys())
    else:
        min_n = min(len(parsed[a]) for a in assets)
        common_dates = [f"obs_{i:06d}" for i in range(min_n)]

    if len(common_dates) < min_observations:
        raise ValueError(
            f"Insufficient date-aligned observations: {len(common_dates)} common dates found, "
            f"minimum required is {min_observations}."
        )

    aligned: dict[str, list[float]] = {}
    for a in assets:
        aligned[a] = [parsed[a][d] for d in common_dates]

    metadata: dict[str, Any] = {
        "start_date": common_dates[0] if has_explicit_dates and common_dates else None,
        "end_date": common_dates[-1] if has_explicit_dates and common_dates else None,
        "common_intervals": len(common_dates),
        "date_aligned": has_explicit_dates,
        "total_assets": len(assets),
    }
    return common_dates, aligned, metadata


# =========================================================================
# 3. MULTI-ASSET PORTFOLIO VALUE AT RISK (VaR)
# =========================================================================

def calculate_portfolio_var(
    weights: Mapping[str, float],
    returns_by_asset: Mapping[str, Any],
    portfolio_value: float,
    confidence: float = 0.95,
    horizon_days: int = 1,
    currency: str = "IDR",
    dates_by_asset: Mapping[str, Sequence[str]] | None = None,
) -> PortfolioVaRResult:
    """Calculates Parametric & Historical VaR and CVaR for a multi-asset portfolio.

    Aligns assets on genuine matching observation dates and decomposes Component VaR.
    """
    if portfolio_value <= 0:
        raise ValueError("Portfolio value must be positive.")
    if not weights:
        raise ValueError("Portfolio weights must not be empty.")

    raw_sum = sum(weights.values())
    if raw_sum <= 0:
        raise ValueError("Sum of weights must be positive.")
    norm_weights = {k: v / raw_sum for k, v in weights.items()}

    valid_assets = [a for a in norm_weights.keys() if a in returns_by_asset and len(returns_by_asset[a]) >= 2]
    if not valid_assets:
        raise ValueError("At least one asset must have two or more return observations.")

    # Align dates across assets
    sub_returns = {a: returns_by_asset[a] for a in valid_assets}
    sub_dates = {a: dates_by_asset[a] for a in valid_assets if dates_by_asset and a in dates_by_asset} if dates_by_asset else None
    common_dates, aligned_returns, align_meta = align_asset_returns(sub_returns, sub_dates, min_observations=2)
    obs_count = len(common_dates)

    # 1. Individual volatilities
    std_by_asset = {a: _sample_std(aligned_returns[a]) for a in valid_assets}

    # 2. Covariance Matrix & Parametric Volatility
    cov_matrix: dict[str, dict[str, float]] = {a: {} for a in valid_assets}
    for a1 in valid_assets:
        for a2 in valid_assets:
            cov_matrix[a1][a2] = _covariance(aligned_returns[a1], aligned_returns[a2])

    port_var_daily = 0.0
    for a1 in valid_assets:
        w1 = norm_weights[a1]
        for a2 in valid_assets:
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
    for i in range(obs_count):
        r_day = sum(norm_weights[a] * aligned_returns[a][i] for a in valid_assets)
        hist_port_returns.append(r_day)

    # Historical VaR & CVaR (Expected Shortfall)
    p_tail = 1.0 - confidence
    left_tail_pctile = _percentile(hist_port_returns, p_tail)
    hist_var_single_day = abs(left_tail_pctile) if left_tail_pctile < 0 else 0.0
    historical_var_pct = hist_var_single_day * horizon_multiplier
    historical_var_amount = portfolio_value * historical_var_pct

    tail_losses = [abs(r) for r in hist_port_returns if r <= -hist_var_single_day] if hist_var_single_day > 0 else []
    cvar_single_day = _mean(tail_losses) if tail_losses else hist_var_single_day
    cvar_pct = cvar_single_day * horizon_multiplier
    cvar_amount = portfolio_value * cvar_pct

    # 4. Diversification Benefit
    undiversified_daily_std = sum(norm_weights[a] * std_by_asset[a] for a in valid_assets)
    undiversified_risk = portfolio_value * (z_score * undiversified_daily_std * horizon_multiplier)
    diversified_risk = parametric_var_amount
    div_benefit_pct = max(0.0, ((undiversified_risk - diversified_risk) / undiversified_risk) * 100.0) if undiversified_risk > 0 else 0.0

    # 5. Component VaR (Marginal Contribution to Total Risk)
    component_var: dict[str, float] = {}
    if port_daily_std > 0:
        for a in valid_assets:
            cov_w = sum(cov_matrix[a][other] * norm_weights[other] for other in valid_assets)
            marginal_beta = cov_w / (port_daily_std ** 2)
            c_var = norm_weights[a] * marginal_beta * parametric_var_amount
            component_var[a] = round(c_var, 2)
    else:
        for a in valid_assets:
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
        weights={a: round(norm_weights[a], 4) for a in valid_assets},
        component_var=component_var,
        currency=currency,
        observations_used=obs_count,
        alignment_metadata=align_meta,
    )


# =========================================================================
# 4. CROSS-ASSET CORRELATION MATRIX (IDX EQUITIES VS CRYPTO)
# =========================================================================

def calculate_correlation_matrix(
    returns_by_asset: Mapping[str, Any],
    idx_symbols: Sequence[str] | None = None,
    crypto_symbols: Sequence[str] | None = None,
    dates_by_asset: Mapping[str, Sequence[str]] | None = None,
) -> CorrelationMatrixResult:
    """Calculates correlation matrix across assets with strict calendar date alignment."""
    assets = [a for a, rets in returns_by_asset.items() if len(rets) >= 2]
    if len(assets) < 2:
        raise ValueError("At least two assets with returns are required for correlation matrix.")

    # Align each pair on their common dates
    matrix: dict[str, dict[str, float]] = {a: {} for a in assets}
    pair_values: list[tuple[str, str, float]] = []
    total_obs_used = 0

    for i, a1 in enumerate(assets):
        for j, a2 in enumerate(assets):
            if a1 == a2:
                matrix[a1][a2] = 1.0
            elif j > i:
                pair_dict = {a1: returns_by_asset[a1], a2: returns_by_asset[a2]}
                pair_dates = {a: dates_by_asset[a] for a in (a1, a2) if dates_by_asset and a in dates_by_asset} if dates_by_asset else None
                try:
                    common_d, aligned_p, _ = align_asset_returns(pair_dict, pair_dates, min_observations=2)
                    corr = _pearson_corr(aligned_p[a1], aligned_p[a2])
                    total_obs_used = max(total_obs_used, len(common_d))
                except ValueError:
                    corr = 0.0
                c_val = round(corr, 4)
                matrix[a1][a2] = c_val
                matrix[a2][a1] = c_val
                pair_values.append((a1, a2, c_val))

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

    avg_corr = _mean([p[2] for p in pair_values]) if pair_values else 0.0
    sorted_pairs = sorted(pair_values, key=lambda item: item[2])
    lowest_pair = sorted_pairs[0] if sorted_pairs else ("", "", 0.0)
    highest_pair = sorted_pairs[-1] if sorted_pairs else ("", "", 0.0)
    div_score = max(0.0, min(1.0, (1.0 - max(0.0, avg_corr))))

    return CorrelationMatrixResult(
        assets=assets,
        matrix=matrix,
        cross_asset_correlations=cross_list,
        average_correlation=round(avg_corr, 4),
        diversification_score=round(div_score, 4),
        highest_pair=(highest_pair[0], highest_pair[1], round(highest_pair[2], 4)),
        lowest_pair=(lowest_pair[0], lowest_pair[1], round(lowest_pair[2], 4)),
        observations_used=total_obs_used,
        alignment_metadata={"date_aligned": bool(dates_by_asset or any(isinstance(returns_by_asset[a], dict) for a in assets))},
    )


# =========================================================================
# 5. TEXTUAL / TERMINAL FORMATTERS
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
    if not result.trade_eligible:
        lines.append("  STATUS ORDER         : DITOLAK (Trade Ineligible)")
        lines.append(f"  Alasan Penolakan     : {result.rejection_reason}")
    else:
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
    if result.alignment_metadata.get("start_date"):
        lines.append(f"  Periode Sampel       : {result.alignment_metadata['start_date']} s/d {result.alignment_metadata['end_date']} ({result.observations_used} interval)")
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
