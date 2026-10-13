"""Valuation, Fundamental Multiples, DuPont Analysis & DCF Scenario Engine.

Provides mathematically rigorous, source-grounded valuation analysis:
- Price multiples (PER, PBV, EV/EBITDA, FCF Yield) with negative earnings guards.
- 3-stage and 5-stage DuPont ROE decomposition.
- Earnings quality & cash conversion assessment.
- Multi-scenario DCF (Base / Bull / Bear) with 2D sensitivity matrix.
- Banking-specific Excess Return / Dividend Discount Model for financial institutions.
"""

from __future__ import annotations

import logging
import math
from typing import Any

logger = logging.getLogger(__name__)


def calculate_valuation_multiples(
    statement: dict[str, Any],
    price: float | None,
    shares_outstanding: float | None = None,
    sector: str = "",
) -> dict[str, Any]:
    """Calculates valuation multiples with rigorous guards for negative figures and sector differences."""
    values = statement.get("values", {})
    unit = statement.get("unit", "million_IDR")
    mult = {"IDR": 1.0, "thousand_IDR": 1e3, "million_IDR": 1e6, "billion_IDR": 1e9}.get(unit, 1e6)

    shares = shares_outstanding or values.get("shares_outstanding") or values.get("weighted_average_shares")
    if not shares or shares <= 0:
        return {"status": "INSUFFICIENT_SHARES_DATA", "multiples": {}}

    market_cap = (price * shares) if (price and price > 0) else None

    # Normalization
    net_income_attributable = values.get("net_income_attributable")
    if net_income_attributable is not None:
        net_income_attributable = net_income_attributable * mult

    equity_attributable = values.get("equity_attributable") or values.get("equity")
    if equity_attributable is not None:
        equity_attributable = equity_attributable * mult

    revenue = values.get("revenue")
    if revenue is not None:
        revenue = revenue * mult

    ebit = values.get("operating_income")
    if ebit is not None:
        ebit = ebit * mult

    total_debt = values.get("interest_bearing_debt") or values.get("total_liabilities")
    if total_debt is not None:
        total_debt = total_debt * mult

    cash = values.get("cash_and_equivalents")
    if cash is not None:
        cash = cash * mult

    ocf = values.get("operating_cash_flow")
    if ocf is not None:
        ocf = ocf * mult

    capex = values.get("capital_expenditure")
    if capex is not None:
        capex = abs(capex * mult)

    is_bank = (
        sector.upper() in {"FINANCIALS", "KEUANGAN", "BANK"}
        or "NIM" in statement.get("reported_ratios_pct", {})
        or "CAR" in statement.get("reported_ratios_pct", {})
    )

    multiples: dict[str, Any] = {}
    notes: list[str] = []

    # 1. EPS & PER
    eps = None
    if net_income_attributable is not None:
        eps = net_income_attributable / shares
        multiples["EPS_IDR"] = round(eps, 2)
        if price and price > 0:
            if net_income_attributable > 0:
                multiples["PER"] = round(price / eps, 2)
            else:
                multiples["PER"] = None
                multiples["PER_note"] = "N/A (Laba Bersih Negatif)"
                notes.append("Emiten membukukan rugi bersih; PER tidak dapat dihitung.")

    # 2. BVPS & PBV
    bvps = None
    if equity_attributable is not None:
        bvps = equity_attributable / shares
        multiples["BVPS_IDR"] = round(bvps, 2)
        if price and price > 0:
            if equity_attributable > 0:
                multiples["PBV"] = round(price / bvps, 2)
            else:
                multiples["PBV"] = None
                multiples["PBV_note"] = "N/A (Ekuitas Negatif / Defisiensi Modal)"
                notes.append("Emiten mengalami defisiensi modal; PBV tidak dapat dihitung.")

    # 3. Enterprise Value & EV/EBITDA
    if market_cap and total_debt is not None and cash is not None:
        ev = market_cap + total_debt - cash
        multiples["EV_IDR"] = round(ev, 0)
        multiples["Market_Cap_IDR"] = round(market_cap, 0)
        if ebit is not None and ebit > 0 and not is_bank:
            multiples["EV_to_EBIT"] = round(ev / ebit, 2)

    # 4. Free Cash Flow & FCF Yield
    if is_bank:
        multiples["FCF_IDR"] = None
        multiples["FCF_status"] = "NOT_APPLICABLE"
        multiples["FCF_note"] = "Sektor Perbankan: Arus kas operasional bank dipengaruhi dana pihak ketiga dan penyaluran kredit, sehingga FCF korporasi industri tidak relevan."
    elif ocf is not None and capex is not None:
        fcf = ocf - capex
        multiples["FCF_IDR"] = round(fcf, 0)
        if market_cap and market_cap > 0:
            multiples["FCF_Yield_pct"] = round((fcf / market_cap) * 100.0, 2)

    # 5. Price to Sales (P/S)
    if market_cap and revenue is not None and revenue > 0:
        multiples["Price_to_Sales"] = round(market_cap / revenue, 2)

    return {
        "status": "CALCULATED",
        "symbol": statement.get("symbol", ""),
        "period": statement.get("period", ""),
        "price": price,
        "shares_outstanding": shares,
        "is_bank": is_bank,
        "multiples": multiples,
        "notes": notes,
    }


def dupont_analysis(
    statement: dict[str, Any],
    previous_statement: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Decomposes Return on Equity (ROE) into operational and financial drivers using 3-stage and 5-stage DuPont models."""
    values = statement.get("values", {})
    unit = statement.get("unit", "million_IDR")
    mult = {"IDR": 1.0, "thousand_IDR": 1e3, "million_IDR": 1e6, "billion_IDR": 1e9}.get(unit, 1e6)

    revenue = (values.get("revenue") or 0.0) * mult
    ebit = (values.get("operating_income") or 0.0) * mult
    pbt = (values.get("profit_before_tax") or 0.0) * mult
    net_income = (values.get("net_income_attributable") or values.get("net_income") or 0.0) * mult
    ending_assets = (values.get("total_assets") or 0.0) * mult
    ending_equity = (values.get("equity_attributable") or values.get("equity") or 0.0) * mult

    # Average balances if previous period exists
    if previous_statement:
        p_vals = previous_statement.get("values", {})
        p_mult = {"IDR": 1.0, "thousand_IDR": 1e3, "million_IDR": 1e6, "billion_IDR": 1e9}.get(previous_statement.get("unit", "million_IDR"), 1e6)
        beg_assets = (p_vals.get("total_assets") or ending_assets / mult) * p_mult
        beg_equity = (p_vals.get("equity_attributable") or p_vals.get("equity") or ending_equity / mult) * p_mult
        avg_assets = (ending_assets + beg_assets) / 2.0
        avg_equity = (ending_equity + beg_equity) / 2.0
        is_avg = True
    else:
        avg_assets = ending_assets
        avg_equity = ending_equity
        is_avg = False

    if revenue <= 0 or avg_assets <= 0 or avg_equity <= 0:
        return {"status": "INSUFFICIENT_DATA", "analysis": {}}

    # 3-Stage DuPont
    net_profit_margin = (net_income / revenue) * 100.0
    asset_turnover = revenue / avg_assets
    equity_multiplier = avg_assets / avg_equity
    calc_roe = (net_profit_margin / 100.0) * asset_turnover * equity_multiplier * 100.0

    three_stage = {
        "net_profit_margin_pct": round(net_profit_margin, 2),
        "asset_turnover_x": round(asset_turnover, 3),
        "equity_multiplier_x": round(equity_multiplier, 2),
        "roe_pct": round(calc_roe, 2),
        "is_average_balances": is_avg,
    }

    # 5-Stage DuPont (if EBIT and PBT available)
    five_stage = None
    if ebit > 0 and pbt > 0:
        tax_burden = (net_income / pbt)  # Net Income / EBT
        interest_burden = (pbt / ebit)   # EBT / EBIT
        operating_margin = (ebit / revenue) * 100.0  # EBIT / Revenue
        five_stage = {
            "tax_burden": round(tax_burden, 3),
            "interest_burden": round(interest_burden, 3),
            "operating_margin_pct": round(operating_margin, 2),
            "asset_turnover_x": round(asset_turnover, 3),
            "financial_leverage_x": round(equity_multiplier, 2),
            "roe_pct": round(calc_roe, 2),
        }

    return {
        "status": "COMPLETED",
        "symbol": statement.get("symbol", ""),
        "period": statement.get("period", ""),
        "three_stage": three_stage,
        "five_stage": five_stage,
    }


def evaluate_earnings_quality(statement: dict[str, Any]) -> dict[str, Any]:
    """Evaluates earnings quality, cash flow backing, and accrual anomaly flags."""
    values = statement.get("values", {})
    unit = statement.get("unit", "million_IDR")
    mult = {"IDR": 1.0, "thousand_IDR": 1e3, "million_IDR": 1e6, "billion_IDR": 1e9}.get(unit, 1e6)

    net_income = (values.get("net_income_attributable") or values.get("net_income") or 0.0) * mult
    ocf = (values.get("operating_cash_flow") or 0.0) * mult
    total_assets = (values.get("total_assets") or 0.0) * mult

    if net_income == 0 or total_assets <= 0:
        return {"status": "INSUFFICIENT_DATA"}

    cash_conversion = ocf / net_income if net_income > 0 else None
    accruals = (net_income - ocf) / total_assets

    if cash_conversion is not None:
        if cash_conversion >= 1.0:
            assessment = "PRIMA (Arus kas operasi lebih tinggi dari laba bersih, kualitas laba sangat solid)"
        elif cash_conversion >= 0.8:
            assessment = "BAIK (Arus kas operasi memadai mengonversi laba akuntansi)"
        else:
            assessment = "PERLU WASPADA (Konversi kas rendah < 80%, potensi peningkatan piutang atau penumpukan persediaan)"
    else:
        assessment = "TIDAK DAPAT DIHITUNG (Laba bersih negatif)"

    return {
        "status": "EVALUATED",
        "cash_conversion_ratio": round(cash_conversion, 2) if cash_conversion is not None else None,
        "accruals_to_assets": round(accruals, 4),
        "assessment": assessment,
        "net_income_IDR": round(net_income, 0),
        "operating_cash_flow_IDR": round(ocf, 0),
    }


def dcf_scenario_model(
    statement: dict[str, Any],
    price: float,
    shares_outstanding: float | None = None,
    sector: str = "",
) -> dict[str, Any]:
    """Generates 3-scenario intrinsic valuation (Base, Bull, Bear) and a 2D sensitivity table.

    For banks, applies the Excess Return / Dividend Discount Model.
    """
    values = statement.get("values", {})
    unit = statement.get("unit", "million_IDR")
    mult = {"IDR": 1.0, "thousand_IDR": 1e3, "million_IDR": 1e6, "billion_IDR": 1e9}.get(unit, 1e6)

    shares = shares_outstanding or values.get("shares_outstanding") or values.get("weighted_average_shares")
    if not shares or shares <= 0 or price <= 0:
        return {"status": "INVALID_INPUTS", "message": "Harga saham dan lembar saham diperlukan."}

    is_bank = (
        sector.upper() in {"FINANCIALS", "KEUANGAN", "BANK"}
        or "NIM" in statement.get("reported_ratios_pct", {})
        or "CAR" in statement.get("reported_ratios_pct", {})
    )

    if is_bank:
        # Excess Return Model for Banks: Intrinsic Value = BVPS + PV of Excess ROE
        equity = (values.get("equity_attributable") or values.get("equity") or 0.0) * mult
        net_income = (values.get("net_income_attributable") or values.get("net_income") or 0.0) * mult
        if equity <= 0:
            return {"status": "NEGATIVE_EQUITY", "message": "Ekuitas bank negatif."}

        bvps = equity / shares
        roe = net_income / equity if equity > 0 else 0.0

        # Scenarios for Bank
        # Cost of equity: Ke = 10.5% (Risk Free ~6.5% + Beta 1.0 * ERP 4.0%)
        ke = 0.105
        scenarios = {
            "Bear": {"sustainable_roe": max(0.05, roe * 0.8), "g": 0.03, "ke": 0.115},
            "Base": {"sustainable_roe": roe, "g": 0.04, "ke": 0.105},
            "Bull": {"sustainable_roe": roe * 1.15, "g": 0.05, "ke": 0.095},
        }

        results = {}
        for sc_name, sc_params in scenarios.items():
            s_roe = sc_params["sustainable_roe"]
            s_g = sc_params["g"]
            s_ke = sc_params["ke"]
            # Excess return per share = BVPS * (ROE - Ke) / (Ke - g)
            excess = bvps * (s_roe - s_ke) / max(0.01, (s_ke - s_g))
            iv = max(0.0, bvps + excess)
            mos = ((iv - price) / iv * 100.0) if iv > 0 else -100.0
            results[sc_name] = {
                "intrinsic_value_per_share": round(iv, 0),
                "margin_of_safety_pct": round(mos, 1),
                "assumed_roe_pct": round(s_roe * 100.0, 1),
                "cost_of_equity_pct": round(s_ke * 100.0, 1),
            }

        return {
            "status": "COMPLETED",
            "model_type": "EXCESS_RETURN_BANK_MODEL",
            "current_price": price,
            "bvps": round(bvps, 2),
            "scenarios": results,
        }

    # Non-financial Corporate DCF Model
    ocf = (values.get("operating_cash_flow") or 0.0) * mult
    capex = abs((values.get("capital_expenditure") or 0.0) * mult)
    base_fcf = ocf - capex

    # Fallback to normalized net income if FCF is negative or zero
    net_income = (values.get("net_income_attributable") or values.get("net_income") or 0.0) * mult
    used_fcf = base_fcf if base_fcf > 0 else max(100_000.0, net_income * 0.7)

    debt = (values.get("interest_bearing_debt") or values.get("total_liabilities") or 0.0) * mult
    cash = (values.get("cash_and_equivalents") or 0.0) * mult

    scenarios_params = {
        "Bear": {"growth": 0.03, "wacc": 0.12, "terminal_g": 0.025},
        "Base": {"growth": 0.07, "wacc": 0.10, "terminal_g": 0.035},
        "Bull": {"growth": 0.12, "wacc": 0.09, "terminal_g": 0.040},
    }

    def _calc_dcf(g: float, wacc: float, tg: float) -> float:
        pv_fcfs = 0.0
        proj_fcf = used_fcf
        for year in range(1, 6):
            proj_fcf *= (1.0 + g)
            pv_fcfs += proj_fcf / ((1.0 + wacc) ** year)
        # Terminal value at year 5
        tv = (proj_fcf * (1.0 + tg)) / max(0.005, (wacc - tg))
        pv_tv = tv / ((1.0 + wacc) ** 5)
        ev = pv_fcfs + pv_tv
        equity_val = ev - debt + cash
        return max(0.0, equity_val / shares)

    scenario_outputs = {}
    for sc_name, p in scenarios_params.items():
        iv = _calc_dcf(p["growth"], p["wacc"], p["terminal_g"])
        mos = ((iv - price) / iv * 100.0) if iv > 0 else -100.0
        scenario_outputs[sc_name] = {
            "intrinsic_value_per_share": round(iv, 0),
            "margin_of_safety_pct": round(mos, 1),
            "growth_rate_pct": round(p["growth"] * 100.0, 1),
            "wacc_pct": round(p["wacc"] * 100.0, 1),
            "terminal_g_pct": round(p["terminal_g"] * 100.0, 1),
        }

    # 2D Sensitivity Matrix: WACC (8% - 12%) vs Terminal Growth (2.5% - 4.0%)
    wacc_rates = [0.08, 0.09, 0.10, 0.11, 0.12]
    tg_rates = [0.025, 0.030, 0.035, 0.040]
    sensitivity_matrix = []
    base_g = scenarios_params["Base"]["growth"]

    for w in wacc_rates:
        row = {"wacc_pct": round(w * 100.0, 1)}
        for tg in tg_rates:
            iv = _calc_dcf(base_g, w, tg)
            row[f"g_{round(tg*100, 1)}%"] = round(iv, 0)
        sensitivity_matrix.append(row)

    return {
        "status": "COMPLETED",
        "model_type": "FCF_DISCOUNTED_CASH_FLOW",
        "current_price": price,
        "base_fcf_IDR": round(used_fcf, 0),
        "scenarios": scenario_outputs,
        "sensitivity_matrix": sensitivity_matrix,
    }
