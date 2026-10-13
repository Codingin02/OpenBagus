"""Valuation, Fundamental Multiples, DuPont Analysis & DCF Scenario Engine.

Provides mathematically rigorous, source-grounded valuation analysis:
- Price multiples (PER, PBV, P/S, EV/EBITDA, EV/EBIT, P/FCF, FCF Yield) with negative earnings guards.
- Profitability margins (Gross, Operating, EBITDA, Net Profit, FCF Margin).
- Solvency & Liquidity ratios (Debt-to-Equity, Net Debt/EBITDA, Interest Coverage, Current, Quick, Cash Ratio).
- Return metrics (ROE, ROA, ROIC with NOPAT and invested capital).
- 3-stage and 5-stage DuPont ROE decomposition.
- Earnings quality & cash conversion assessment.
- Multi-scenario DCF (Base / Bull / Bear) with 2D sensitivity matrices (WACC vs g, Margin vs Rev Growth).
- Banking-specific Excess Return / Dividend Discount Model for financial institutions.
- Multi-currency support (IDR, USD).
"""

from __future__ import annotations

import logging
import math
from typing import Any

logger = logging.getLogger(__name__)


def _get_multiplier(unit: str, currency: str = "IDR") -> float:
    unit_map = {
        "IDR": 1.0,
        "thousand_IDR": 1e3,
        "million_IDR": 1e6,
        "billion_IDR": 1e9,
        "USD": 1.0,
        "thousand_USD": 1e3,
        "million_USD": 1e6,
        "billion_USD": 1e9,
        "exact": 1.0,
    }
    if unit in unit_map:
        return unit_map[unit]
    if currency == "USD":
        return 1.0
    return 1e6


def calculate_valuation_multiples(
    statement: dict[str, Any],
    price: float | None,
    shares_outstanding: float | None = None,
    sector: str = "",
) -> dict[str, Any]:
    """Calculates valuation multiples with rigorous guards for negative figures and sector differences."""
    values = statement.get("values", {})
    currency = statement.get("currency", "IDR")
    unit = statement.get("unit", "million_IDR" if currency == "IDR" else "USD")
    mult = _get_multiplier(unit, currency)

    shares = shares_outstanding or values.get("shares_outstanding") or values.get("weighted_average_shares")
    if not shares or shares <= 0:
        return {"status": "INSUFFICIENT_SHARES_DATA", "currency": currency, "multiples": {}}

    market_cap = (price * shares) if (price and price > 0) else None

    # Normalization
    net_income_attributable = values.get("net_income_attributable")
    if net_income_attributable is not None:
        net_income_attributable = net_income_attributable * mult

    net_income_total = values.get("net_income") or values.get("net_income_total")
    if net_income_total is not None:
        net_income_total = net_income_total * mult

    equity_attributable = values.get("equity_attributable") or values.get("equity")
    if equity_attributable is not None:
        equity_attributable = equity_attributable * mult

    revenue = values.get("revenue")
    if revenue is not None:
        revenue = revenue * mult

    cost_of_revenue = values.get("cost_of_revenue")
    if cost_of_revenue is not None:
        cost_of_revenue = abs(cost_of_revenue * mult)

    gross_profit = values.get("gross_profit")
    if gross_profit is not None:
        gross_profit = gross_profit * mult
    elif revenue is not None and cost_of_revenue is not None:
        gross_profit = revenue - cost_of_revenue

    ebit = values.get("operating_income")
    if ebit is not None:
        ebit = ebit * mult

    total_debt = values.get("interest_bearing_debt")
    if total_debt is not None:
        total_debt = total_debt * mult
    else:
        # Fallback to total liabilities
        t_liab = values.get("total_liabilities")
        if t_liab is not None:
            total_debt = t_liab * mult

    cash = values.get("cash_and_equivalents")
    if cash is not None:
        cash = cash * mult

    current_assets = values.get("current_assets")
    if current_assets is not None:
        current_assets = current_assets * mult

    current_liabilities = values.get("current_liabilities")
    if current_liabilities is not None:
        current_liabilities = current_liabilities * mult

    trade_receivables = values.get("trade_receivables")
    if trade_receivables is not None:
        trade_receivables = trade_receivables * mult

    short_term_investments = values.get("short_term_investments")
    if short_term_investments is not None:
        short_term_investments = short_term_investments * mult

    total_assets = values.get("total_assets")
    if total_assets is not None:
        total_assets = total_assets * mult

    interest_expense = values.get("interest_expense") or values.get("finance_costs")
    if interest_expense is not None:
        interest_expense = abs(interest_expense * mult)

    tax_expense = values.get("tax_expense")
    if tax_expense is not None:
        tax_expense = abs(tax_expense * mult)

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
    ratios: dict[str, Any] = {}
    notes: list[str] = []

    # 1. EPS & PER
    eps = None
    if net_income_attributable is not None:
        eps = net_income_attributable / shares
        multiples[f"EPS_{currency}"] = round(eps, 4 if currency == "USD" else 2)
        if price and price > 0:
            if eps > 0:
                multiples["PER"] = round(price / eps, 2)
            else:
                multiples["PER"] = None
                multiples["PER_note"] = "N/M (Laba Bersih Negatif)"
                notes.append("Emiten membukukan rugi bersih; PER diberi label N/M.")
        else:
            multiples["PER"] = None
            multiples["PER_note"] = "N/A (Harga pasar tidak tersedia)"

    # 2. BVPS & PBV
    bvps = None
    if equity_attributable is not None:
        bvps = equity_attributable / shares
        multiples[f"BVPS_{currency}"] = round(bvps, 4 if currency == "USD" else 2)
        if price and price > 0:
            if bvps > 0:
                multiples["PBV"] = round(price / bvps, 2)
            else:
                multiples["PBV"] = None
                multiples["PBV_note"] = "N/M (Defisiensi Modal / Ekuitas Negatif)"
                notes.append("Emiten mengalami defisiensi modal; PBV diberi label N/M.")
        else:
            multiples["PBV"] = None
            multiples["PBV_note"] = "N/A (Harga pasar tidak tersedia)"

    # 3. Enterprise Value & Multiples
    if market_cap:
        multiples[f"Market_Cap_{currency}"] = round(market_cap, 0)
        multiples["Market_Cap"] = round(market_cap, 0)
        if total_debt is not None and cash is not None:
            ev = market_cap + total_debt - cash
            multiples[f"EV_{currency}"] = round(ev, 0)
            multiples["EV"] = round(ev, 0)
            if ebit is not None and ebit > 0 and not is_bank:
                multiples["EV_to_EBIT"] = round(ev / ebit, 2)
    else:
        multiples[f"Market_Cap_{currency}"] = None
        multiples["Market_Cap"] = None
        multiples[f"EV_{currency}"] = None
        multiples["EV"] = None

    # 4. Free Cash Flow & FCF Yield
    if is_bank:
        multiples[f"FCF_{currency}"] = None
        multiples["FCF"] = None
        multiples["FCF_status"] = "NOT_APPLICABLE"
        multiples["FCF_note"] = "Sektor Perbankan: Arus kas operasional dipengaruhi DPK dan kredit, sehingga FCF korporasi industri tidak relevan."
        multiples["P_FCF_note"] = "NOT_APPLICABLE (Sektor Perbankan/Keuangan)"
        multiples["FCF_Yield_note"] = "NOT_APPLICABLE (Sektor Perbankan/Keuangan)"
    elif ocf is not None and capex is not None:
        fcf = ocf - capex
        multiples[f"FCF_{currency}"] = round(fcf, 0)
        multiples["FCF"] = round(fcf, 0)
        if market_cap and market_cap > 0:
            multiples["FCF_Yield_pct"] = round((fcf / market_cap) * 100.0, 2)
            if fcf > 0:
                multiples["P_to_FCF"] = round(market_cap / fcf, 2)
            else:
                multiples["P_to_FCF"] = None
                multiples["P_to_FCF_note"] = "N/M (FCF Negatif)"

    # 5. Price to Sales (P/S)
    if market_cap and revenue is not None and revenue > 0:
        multiples["Price_to_Sales"] = round(market_cap / revenue, 2)

    # 6. Profitability Margins
    if revenue and revenue > 0:
        if gross_profit is not None:
            ratios["Gross_Profit_Margin_pct"] = round((gross_profit / revenue) * 100.0, 2)
            ratios["Gross_Margin_pct"] = round((gross_profit / revenue) * 100.0, 2)
        if ebit is not None:
            ratios["Operating_Margin_pct"] = round((ebit / revenue) * 100.0, 2)
        if net_income_attributable is not None:
            ratios["Net_Profit_Margin_pct"] = round((net_income_attributable / revenue) * 100.0, 2)
        if not is_bank and ocf is not None and capex is not None:
            fcf = ocf - capex
            ratios["FCF_Margin_pct"] = round((fcf / revenue) * 100.0, 2)

    # 7. Solvency & Liquidity (Non-bank)
    if not is_bank:
        if equity_attributable and equity_attributable > 0 and total_debt is not None:
            ratios["Debt_to_Equity"] = round(total_debt / equity_attributable, 2)
        if current_liabilities and current_liabilities > 0:
            if current_assets is not None:
                ratios["Current_Ratio"] = round(current_assets / current_liabilities, 2)
            if cash is not None and trade_receivables is not None:
                st_inv = short_term_investments or 0.0
                ratios["Quick_Ratio"] = round((cash + st_inv + trade_receivables) / current_liabilities, 2)
            if cash is not None:
                ratios["Cash_Ratio"] = round(cash / current_liabilities, 2)
        if interest_expense and interest_expense > 0 and ebit is not None:
            ratios["Interest_Coverage"] = round(ebit / interest_expense, 2)

    # 8. Return Metrics (ROE, ROA, ROIC)
    if equity_attributable and equity_attributable > 0 and net_income_attributable is not None:
        ratios["ROE_pct"] = round((net_income_attributable / equity_attributable) * 100.0, 2)
    if total_assets and total_assets > 0 and net_income_total is not None:
        ratios["ROA_pct"] = round((net_income_total / total_assets) * 100.0, 2)
    if not is_bank and ebit is not None and total_debt is not None and equity_attributable and equity_attributable > 0:
        eff_tax_rate = (tax_expense / (ebit)) if (tax_expense and ebit > 0 and tax_expense < ebit) else 0.22
        nopat = ebit * (1.0 - eff_tax_rate)
        invested_capital = total_debt + equity_attributable - (cash or 0.0)
        if invested_capital > 0:
            ratios["ROIC_pct"] = round((nopat / invested_capital) * 100.0, 2)

    return {
        "status": "CALCULATED",
        "symbol": statement.get("symbol", ""),
        "period": statement.get("period", ""),
        "currency": currency,
        "price": price,
        "shares_outstanding": shares,
        "is_bank": is_bank,
        "multiples": multiples,
        "ratios": ratios,
        "notes": notes,
    }


def dupont_analysis(
    statement: dict[str, Any],
    previous_statement: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Decomposes Return on Equity (ROE) into operational and financial drivers using 3-stage and 5-stage DuPont models."""
    values = statement.get("values", {})
    currency = statement.get("currency", "IDR")
    unit = statement.get("unit", "million_IDR" if currency == "IDR" else "USD")
    mult = _get_multiplier(unit, currency)

    revenue = (values.get("revenue") or 0.0) * mult
    ebit = (values.get("operating_income") or 0.0) * mult
    pbt = (values.get("profit_before_tax") or 0.0) * mult
    net_income = (values.get("net_income_attributable") or values.get("net_income") or 0.0) * mult
    ending_assets = (values.get("total_assets") or 0.0) * mult
    ending_equity = (values.get("equity_attributable") or values.get("equity") or 0.0) * mult

    if previous_statement:
        p_vals = previous_statement.get("values", {})
        p_mult = _get_multiplier(previous_statement.get("unit", unit), previous_statement.get("currency", currency))
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

    five_stage = None
    if ebit > 0 and pbt > 0:
        tax_burden = net_income / pbt
        interest_burden = pbt / ebit
        operating_margin = (ebit / revenue) * 100.0
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
        "currency": currency,
        "three_stage": three_stage,
        "five_stage": five_stage,
    }


def evaluate_earnings_quality(statement: dict[str, Any]) -> dict[str, Any]:
    """Evaluates earnings quality, cash flow backing, and accrual anomaly flags."""
    values = statement.get("values", {})
    currency = statement.get("currency", "IDR")
    unit = statement.get("unit", "million_IDR" if currency == "IDR" else "USD")
    mult = _get_multiplier(unit, currency)

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
        "currency": currency,
        "cash_conversion_ratio": round(cash_conversion, 2) if cash_conversion is not None else None,
        "accruals_to_assets": round(accruals, 4),
        "assessment": assessment,
        f"net_income_{currency}": round(net_income, 0),
        f"operating_cash_flow_{currency}": round(ocf, 0),
    }


def dcf_scenario_model(
    statement: dict[str, Any],
    price: float | None,
    shares_outstanding: float | None = None,
    sector: str = "",
) -> dict[str, Any]:
    """Generates 3-scenario intrinsic valuation (Base, Bull, Bear) and two 2D sensitivity matrices.

    For banks, applies the Excess Return / Dividend Discount Model.
    """
    values = statement.get("values", {})
    currency = statement.get("currency", "IDR")
    unit = statement.get("unit", "million_IDR" if currency == "IDR" else "USD")
    mult = _get_multiplier(unit, currency)

    shares = shares_outstanding or values.get("shares_outstanding") or values.get("weighted_average_shares")
    if not shares or shares <= 0:
        return {"status": "INVALID_INPUTS", "message": "Lembar saham beredar diperlukan untuk valuasi per saham."}

    is_bank = (
        sector.upper() in {"FINANCIALS", "KEUANGAN", "BANK"}
        or "NIM" in statement.get("reported_ratios_pct", {})
        or "CAR" in statement.get("reported_ratios_pct", {})
    )

    if is_bank:
        equity = (values.get("equity_attributable") or values.get("equity") or 0.0) * mult
        net_income = (values.get("net_income_attributable") or values.get("net_income") or 0.0) * mult
        if equity <= 0:
            return {"status": "NEGATIVE_EQUITY", "message": "Ekuitas bank negatif."}

        bvps = equity / shares
        roe = net_income / equity if equity > 0 else 0.0

        # Cost of equity assumptions
        ke_base = 0.105 if currency == "IDR" else 0.090
        scenarios = {
            "Bear": {"sustainable_roe": max(0.05, roe * 0.8), "g": 0.03, "ke": ke_base + 0.01},
            "Base": {"sustainable_roe": roe, "g": 0.04, "ke": ke_base},
            "Bull": {"sustainable_roe": roe * 1.15, "g": 0.05, "ke": ke_base - 0.01},
        }

        results = {}
        for sc_name, sc_params in scenarios.items():
            s_roe = sc_params["sustainable_roe"]
            s_g = sc_params["g"]
            s_ke = sc_params["ke"]
            excess = bvps * (s_roe - s_ke) / max(0.01, (s_ke - s_g))
            iv = max(0.0, bvps + excess)
            mos = (((iv - price) / iv) * 100.0) if (price and price > 0 and iv > 0) else None
            results[sc_name] = {
                "intrinsic_value_per_share": round(iv, 2 if currency == "USD" else 0),
                "margin_of_safety_pct": round(mos, 1) if mos is not None else "N/A (Harga tidak tersedia)",
                "assumed_roe_pct": round(s_roe * 100.0, 1),
                "cost_of_equity_pct": round(s_ke * 100.0, 1),
            }

        return {
            "status": "COMPLETED",
            "model_type": "EXCESS_RETURN_BANK_MODEL",
            "currency": currency,
            "current_price": price,
            "bvps": round(bvps, 2),
            "scenarios": results,
        }

    # Non-financial Corporate DCF Model
    revenue = (values.get("revenue") or 0.0) * mult
    ebit = (values.get("operating_income") or 0.0) * mult
    ocf = (values.get("operating_cash_flow") or 0.0) * mult
    capex = abs((values.get("capital_expenditure") or 0.0) * mult)
    base_fcf = ocf - capex

    net_income = (values.get("net_income_attributable") or values.get("net_income") or 0.0) * mult
    used_fcf = base_fcf if base_fcf > 0 else max(100_000.0, net_income * 0.7)

    debt = (values.get("interest_bearing_debt") or values.get("total_liabilities") or 0.0) * mult
    cash = (values.get("cash_and_equivalents") or 0.0) * mult

    wacc_base = 0.10 if currency == "IDR" else 0.085
    scenarios_params = {
        "Bear": {"growth": 0.03, "wacc": wacc_base + 0.02, "terminal_g": 0.025},
        "Base": {"growth": 0.07, "wacc": wacc_base, "terminal_g": 0.030},
        "Bull": {"growth": 0.12, "wacc": wacc_base - 0.01, "terminal_g": 0.035},
    }

    def _calc_dcf(g: float, wacc: float, tg: float) -> float:
        pv_fcfs = 0.0
        proj_fcf = used_fcf
        for year in range(1, 6):
            proj_fcf *= (1.0 + g)
            pv_fcfs += proj_fcf / ((1.0 + wacc) ** year)
        tv = (proj_fcf * (1.0 + tg)) / max(0.005, (wacc - tg))
        pv_tv = tv / ((1.0 + wacc) ** 5)
        ev = pv_fcfs + pv_tv
        equity_val = ev - debt + cash
        return max(0.0, equity_val / shares)

    scenario_outputs = {}
    for sc_name, p in scenarios_params.items():
        iv = _calc_dcf(p["growth"], p["wacc"], p["terminal_g"])
        mos = (((iv - price) / iv) * 100.0) if (price and price > 0 and iv > 0) else None
        scenario_outputs[sc_name] = {
            "intrinsic_value_per_share": round(iv, 2 if currency == "USD" else 0),
            "margin_of_safety_pct": round(mos, 1) if mos is not None else "N/A (Harga tidak tersedia)",
            "growth_rate_pct": round(p["growth"] * 100.0, 1),
            "wacc_pct": round(p["wacc"] * 100.0, 1),
            "terminal_g_pct": round(p["terminal_g"] * 100.0, 1),
        }

    # Sensitivity Matrix 1: WACC vs Terminal Growth
    wacc_rates = [wacc_base - 0.02, wacc_base - 0.01, wacc_base, wacc_base + 0.01, wacc_base + 0.02]
    tg_rates = [0.020, 0.025, 0.030, 0.035]
    matrix_wacc_tg = []
    base_g = scenarios_params["Base"]["growth"]

    for w in wacc_rates:
        row = {"wacc_pct": round(w * 100.0, 1)}
        for tg in tg_rates:
            iv = _calc_dcf(base_g, w, tg)
            row[f"g_{round(tg*100, 1)}%"] = round(iv, 2 if currency == "USD" else 0)
        matrix_wacc_tg.append(row)

    # Sensitivity Matrix 2: Operating Margin vs Revenue Growth
    base_op_margin = (ebit / revenue) if (revenue > 0 and ebit > 0) else 0.15
    rev_growth_rates = [0.03, 0.05, 0.07, 0.10, 0.12]
    op_margins = [max(0.05, base_op_margin * 0.8), base_op_margin, base_op_margin * 1.2]
    matrix_margin_growth = []

    for mg in op_margins:
        row = {"operating_margin_pct": round(mg * 100.0, 1)}
        for rg in rev_growth_rates:
            # Scale FCF proportionally by margin relative to base
            margin_scalar = mg / base_op_margin if base_op_margin > 0 else 1.0
            pv_fcfs = 0.0
            proj_fcf = used_fcf * margin_scalar
            for year in range(1, 6):
                proj_fcf *= (1.0 + rg)
                pv_fcfs += proj_fcf / ((1.0 + wacc_base) ** year)
            tv = (proj_fcf * (1.0 + 0.03)) / max(0.005, (wacc_base - 0.03))
            pv_tv = tv / ((1.0 + wacc_base) ** 5)
            iv = max(0.0, (pv_fcfs + pv_tv - debt + cash) / shares)
            row[f"rev_g_{round(rg*100, 1)}%"] = round(iv, 2 if currency == "USD" else 0)
        matrix_margin_growth.append(row)

    return {
        "status": "COMPLETED",
        "model_type": "FCF_DISCOUNTED_CASH_FLOW",
        "currency": currency,
        "current_price": price,
        f"base_fcf_{currency}": round(used_fcf, 2 if currency == "USD" else 0),
        "scenarios": scenario_outputs,
        "sensitivity_matrix": matrix_wacc_tg,
        "sensitivity_wacc_terminal_growth": matrix_wacc_tg,
        "sensitivity_margin_revenue_growth": matrix_margin_growth,
    }
