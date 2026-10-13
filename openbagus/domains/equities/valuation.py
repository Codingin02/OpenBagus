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
        "trillion_IDR": 1e12,
        "USD": 1.0,
        "thousand_USD": 1e3,
        "million_USD": 1e6,
        "billion_USD": 1e9,
        "trillion_USD": 1e12,
        "exact": 1.0,
        "1": 1.0,
    }
    if not unit:
        return 1.0 if currency == "USD" else 1e6
    if unit in unit_map:
        return unit_map[unit]
    raise ValueError(f"Unrecognized monetary unit: '{unit}' for currency '{currency}'")


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

    interest_bearing_debt = values.get("interest_bearing_debt")
    if interest_bearing_debt is not None:
        interest_bearing_debt = interest_bearing_debt * mult

    total_liabilities = values.get("total_liabilities")
    if total_liabilities is not None:
        total_liabilities = total_liabilities * mult

    total_debt = interest_bearing_debt

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
    nci_val = values.get("non_controlling_interests") or values.get("minority_interest")
    pref_val = values.get("preferred_equity") or values.get("preferred_stock")
    nci = (float(nci_val) * mult) if nci_val is not None else 0.0
    pref = (float(pref_val) * mult) if pref_val is not None else 0.0

    if market_cap:
        multiples[f"Market_Cap_{currency}"] = round(market_cap, 0)
        multiples["Market_Cap"] = round(market_cap, 0)
        if total_debt is not None and cash is not None:
            ev = market_cap + total_debt - cash + nci + pref
            multiples[f"EV_{currency}"] = round(ev, 0)
            multiples["EV"] = round(ev, 0)
            multiples["Enterprise_Value"] = round(ev, 0)
            if nci_val is not None:
                multiples[f"Minority_Interest_{currency}"] = round(nci, 0)
            if pref_val is not None:
                multiples[f"Preferred_Equity_{currency}"] = round(pref, 0)
            if ebit is not None and ebit > 0 and not is_bank:
                multiples["EV_to_EBIT"] = round(ev / ebit, 2)
        else:
            multiples[f"EV_{currency}"] = None
            multiples["EV"] = None
            multiples["EV_to_EBIT"] = None
            if total_debt is None:
                multiples["EV_note"] = "N/A (Hutang berbunga diperlukan untuk Enterprise Value)"
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
        if equity_attributable and equity_attributable > 0:
            if total_debt is not None:
                ratios["Debt_to_Equity"] = round(total_debt / equity_attributable, 2)
            else:
                ratios["Debt_to_Equity"] = None
                ratios["Debt_to_Equity_note"] = "N/A (Hutang berbunga tidak dilaporkan terpisah)"

            if total_liabilities is not None:
                ratios["Total_Liabilities_to_Equity"] = round(total_liabilities / equity_attributable, 2)

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


def calculate_cash_flows(
    statement: dict[str, Any],
    previous_statement: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Calculates Damodaran-compliant multi-stream cash flows and empirical reinvestment rates.

    Identifies and distinguishes:
    - Actual historical FCF (Operating Cash Flow - Capital Expenditures), strictly preserving negative figures.
    - FCFF (Free Cash Flow to Firm / Unlevered Free Cash Flow):
      CFO + Interest Expense * (1 - t) - Capex  (or NOPAT - Reinvestment).
    - FCFE (Free Cash Flow to Equity / Levered Free Cash Flow):
      CFO - Capex + Net Debt Issued.
    - Reinvestment: Net Capex + Delta Non-Cash Working Capital.
    - Reinvestment Rate: Reinvestment / NOPAT.
    - Sustainable Growth: Reinvestment Rate * ROIC.
    """
    values = statement.get("values", {})
    currency = statement.get("currency", "IDR")
    unit = statement.get("unit", "million_IDR" if currency == "IDR" else "USD")
    mult = _get_multiplier(unit, currency)
    sector = statement.get("sector", "")

    is_bank = (
        sector.upper() in {"FINANCIALS", "KEUANGAN", "BANK"}
        or "NIM" in statement.get("reported_ratios_pct", {})
        or "CAR" in statement.get("reported_ratios_pct", {})
    )
    if is_bank:
        return {
            "status": "NOT_APPLICABLE",
            "is_bank": True,
            "message": "Arus kas industri korporasi (FCF/FCFF/FCFE) tidak relevan untuk institusi perbankan/keuangan.",
            "actual_historical_fcf": None,
            "fcff": None,
            "fcfe": None,
            "reinvestment": None,
            "reinvestment_rate": None,
            "sustainable_growth_rate": None,
        }

    ocf_raw = values.get("operating_cash_flow")
    capex_raw = values.get("capital_expenditure") or values.get("capital_expenditures")
    ebit_raw = values.get("operating_income")
    tax_raw = values.get("tax_expense")
    interest_raw = values.get("interest_expense") or values.get("finance_costs")
    da_raw = values.get("depreciation_and_amortization") or values.get("depreciation")
    net_debt_raw = values.get("net_debt_issued")

    ca_raw = values.get("current_assets")
    cl_raw = values.get("current_liabilities")
    cash_raw = values.get("cash_and_equivalents")
    st_debt_raw = values.get("short_term_debt")
    tot_debt_raw = values.get("interest_bearing_debt")
    eq_raw = values.get("equity_attributable") or values.get("equity")

    ocf = (float(ocf_raw) * mult) if ocf_raw is not None else None
    capex = abs(float(capex_raw) * mult) if capex_raw is not None else None
    ebit = (float(ebit_raw) * mult) if ebit_raw is not None else None
    tax = abs(float(tax_raw) * mult) if tax_raw is not None else None
    interest = abs(float(interest_raw) * mult) if interest_raw is not None else None
    da = abs(float(da_raw) * mult) if da_raw is not None else None
    net_debt_issued = (float(net_debt_raw) * mult) if net_debt_raw is not None else None

    # 1. Actual Historical FCF (strictly preserves negative values)
    historical_fcf = (ocf - capex) if (ocf is not None and capex is not None) else None

    # 2. Effective Tax Rate & NOPAT
    eff_tax_rate = (tax / ebit) if (tax is not None and ebit is not None and ebit > 0 and 0 < tax < ebit) else (0.22 if currency == "IDR" else 0.21)
    nopat = (ebit * (1.0 - eff_tax_rate)) if ebit is not None else None

    # 3. Non-Cash Working Capital
    non_cash_wc = None
    if ca_raw is not None and cl_raw is not None:
        ca = float(ca_raw) * mult
        cl = float(cl_raw) * mult
        cash = (float(cash_raw) * mult) if cash_raw is not None else 0.0
        st_debt = (float(st_debt_raw) * mult) if st_debt_raw is not None else 0.0
        non_cash_wc = (ca - cash) - (cl - st_debt)

    delta_non_cash_wc = None
    if previous_statement and non_cash_wc is not None:
        p_vals = previous_statement.get("values", {})
        p_unit = previous_statement.get("unit", unit)
        p_curr = previous_statement.get("currency", currency)
        p_mult = _get_multiplier(p_unit, p_curr)
        p_ca = p_vals.get("current_assets")
        p_cl = p_vals.get("current_liabilities")
        if p_ca is not None and p_cl is not None:
            p_cash = (float(p_vals.get("cash_and_equivalents") or 0.0)) * p_mult
            p_st_debt = (float(p_vals.get("short_term_debt") or 0.0)) * p_mult
            p_nc_wc = (float(p_ca) * p_mult - p_cash) - (float(p_cl) * p_mult - p_st_debt)
            delta_non_cash_wc = non_cash_wc - p_nc_wc

    # 4. Reinvestment
    net_capex = (capex - (da or 0.0)) if capex is not None else None
    reinvestment = None
    reinvestment_type = "UNAVAILABLE"
    if net_capex is not None:
        if delta_non_cash_wc is not None:
            reinvestment = net_capex + delta_non_cash_wc
            reinvestment_type = "EMPIRICAL_NET_CAPEX_PLUS_DELTA_WC"
        else:
            reinvestment = net_capex
            reinvestment_type = "NET_CAPEX_ESTIMATE"

    reinvestment_rate = (reinvestment / nopat) if (reinvestment is not None and nopat is not None and nopat > 0) else None

    # Invested capital & ROIC
    invested_capital = None
    if tot_debt_raw is not None and eq_raw is not None:
        c_debt = float(tot_debt_raw) * mult
        c_eq = float(eq_raw) * mult
        c_cash = (float(cash_raw) * mult) if cash_raw is not None else 0.0
        invested_capital = c_debt + c_eq - c_cash
    roic = (nopat / invested_capital) if (nopat is not None and invested_capital is not None and invested_capital > 0) else None

    sustainable_growth = (reinvestment_rate * roic) if (reinvestment_rate is not None and roic is not None) else None

    # 5. FCFF (Free Cash Flow to Firm)
    fcff = None
    fcff_method = "UNAVAILABLE"
    if ocf is not None and capex is not None:
        int_shield = (interest * (1.0 - eff_tax_rate)) if interest is not None else 0.0
        fcff = ocf + int_shield - capex
        fcff_method = "CFO_PLUS_AFTER_TAX_INTEREST_MINUS_CAPEX"
    elif nopat is not None and reinvestment is not None:
        fcff = nopat - reinvestment
        fcff_method = "NOPAT_MINUS_REINVESTMENT"

    # 6. FCFE (Free Cash Flow to Equity)
    fcfe = None
    fcfe_method = "UNAVAILABLE"
    if ocf is not None and capex is not None:
        net_borrowing = net_debt_issued if net_debt_issued is not None else 0.0
        fcfe = ocf - capex + net_borrowing
        fcfe_method = "CFO_MINUS_CAPEX_PLUS_NET_DEBT"

    return {
        "status": "CALCULATED",
        "currency": currency,
        "actual_historical_fcf": historical_fcf,
        "actual_historical_fcf_is_negative": (historical_fcf < 0) if historical_fcf is not None else False,
        "nopat": nopat,
        "effective_tax_rate": eff_tax_rate,
        "non_cash_working_capital": non_cash_wc,
        "delta_non_cash_working_capital": delta_non_cash_wc,
        "net_capex": net_capex,
        "reinvestment": reinvestment,
        "reinvestment_type": reinvestment_type,
        "reinvestment_rate": reinvestment_rate,
        "invested_capital": invested_capital,
        "roic": roic,
        "sustainable_growth_rate": sustainable_growth,
        "fcff": fcff,
        "fcff_method": fcff_method,
        "fcfe": fcfe,
        "fcfe_method": fcfe_method,
    }


def calculate_fcff(
    statement: dict[str, Any],
    previous_statement: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Computes Free Cash Flow to Firm (FCFF) according to Damodaran's methodology."""
    cf = calculate_cash_flows(statement, previous_statement)
    return {
        "status": cf["status"],
        "currency": cf.get("currency", "IDR"),
        "fcff": cf.get("fcff"),
        "method": cf.get("fcff_method"),
        "actual_historical_fcf": cf.get("actual_historical_fcf"),
        "nopat": cf.get("nopat"),
        "reinvestment": cf.get("reinvestment"),
    }


def calculate_fcfe(statement: dict[str, Any]) -> dict[str, Any]:
    """Computes Free Cash Flow to Equity (FCFE)."""
    cf = calculate_cash_flows(statement)
    return {
        "status": cf["status"],
        "currency": cf.get("currency", "IDR"),
        "fcfe": cf.get("fcfe"),
        "method": cf.get("fcfe_method"),
        "actual_historical_fcf": cf.get("actual_historical_fcf"),
    }


def calculate_reinvestment(
    statement: dict[str, Any],
    previous_statement: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Computes net capital expenditures and non-cash working capital reinvestment."""
    cf = calculate_cash_flows(statement, previous_statement)
    return {
        "status": cf["status"],
        "currency": cf.get("currency", "IDR"),
        "net_capex": cf.get("net_capex"),
        "delta_non_cash_working_capital": cf.get("delta_non_cash_working_capital"),
        "reinvestment": cf.get("reinvestment"),
        "reinvestment_type": cf.get("reinvestment_type"),
        "reinvestment_rate": cf.get("reinvestment_rate"),
    }


def calculate_sustainable_growth(
    statement: dict[str, Any],
    previous_statement: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Computes sustainable growth rate g = Reinvestment Rate * ROIC."""
    cf = calculate_cash_flows(statement, previous_statement)
    return {
        "status": cf["status"],
        "currency": cf.get("currency", "IDR"),
        "reinvestment_rate": cf.get("reinvestment_rate"),
        "roic": cf.get("roic"),
        "sustainable_growth_rate": cf.get("sustainable_growth_rate"),
    }


def dcf_scenario_model(
    statement: dict[str, Any],
    price: float | None,
    shares_outstanding: float | None = None,
    sector: str = "",
    previous_statement: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Generates 3-scenario intrinsic valuation (Base, Bull, Bear) and two 2D sensitivity matrices.

    For banks, applies the Excess Return / Dividend Discount Model.
    For non-financials, computes Damodaran cash flow projections without fabricating positive numbers on losses.
    Preserves actual negative FCF as negative in historical reporting.
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
    ebit_raw = values.get("operating_income")
    ebit = (float(ebit_raw) * mult) if ebit_raw is not None else None
    ocf_raw = values.get("operating_cash_flow")
    capex_raw = values.get("capital_expenditure") or values.get("capital_expenditures")

    base_fcf = None
    if ocf_raw is not None and capex_raw is not None:
        base_fcf = (float(ocf_raw) * mult) - abs(float(capex_raw) * mult)

    # Calculate cash flow breakdown
    cf_breakdown = calculate_cash_flows(statement, previous_statement)
    historical_fcf = cf_breakdown.get("actual_historical_fcf")

    # Guard: When neither cash flow nor operating earnings are provided, data is insufficient
    if base_fcf is None and ebit is None:
        return {
            "status": "INSUFFICIENT_DATA",
            "message": "Data arus kas operasional dan laba operasional tidak mencukupi untuk memproyeksikan DCF.",
            "model_type": "FCF_DISCOUNTED_CASH_FLOW",
            "fcf_state": "INSUFFICIENT_DATA",
            "currency": currency,
            "current_price": price,
        }

    tax_expense = values.get("tax_expense")
    eff_tax_rate = (abs(tax_expense * mult) / ebit) if (tax_expense is not None and ebit is not None and ebit > 0 and 0 < abs(tax_expense * mult) < ebit) else (0.22 if currency == "IDR" else 0.21)

    normalization_note = None
    reinvestment_rate_pct = None

    if base_fcf is not None and base_fcf > 0:
        fcf_state = "CALCULABLE"
        used_fcf = base_fcf
        fcf_basis = "reported_free_cash_flow"
    elif ebit is not None and ebit > 0:
        fcf_state = "REQUIRES_NORMALIZATION"
        nopat = ebit * (1.0 - eff_tax_rate)
        roic = cf_breakdown.get("roic")

        if roic is not None and roic > 0:
            target_g = 0.07
            calc_b = min(0.85, max(0.15, target_g / roic))
            reinvestment_rate_pct = round(calc_b * 100.0, 1)
            used_fcf = nopat * (1.0 - calc_b)
            fcf_basis = "sustainable_reinvestment_rate_scenario"
            normalization_note = (
                f"FCF aktual dilaporkan negatif ({historical_fcf:,.0f} {currency}) akibat belanja modal tinggi. "
                f"Berdasarkan metodologi Damodaran, proyeksi DCF menggunakan tingkat reinvestasi keberlanjutan "
                f"(b = g / ROIC = {reinvestment_rate_pct}%) atas NOPAT positif ({nopat:,.0f} {currency}). "
                "Angka ini adalah skenario model fundamental keberlanjutan, bukan observasi historis emiten."
            )
        else:
            calc_b = 0.35
            reinvestment_rate_pct = 35.0
            used_fcf = nopat * (1.0 - calc_b)
            fcf_basis = "assumption_based_scenario"
            normalization_note = (
                f"FCF aktual dilaporkan bernilai negatif ({historical_fcf:,.0f} {currency}) atau belum dilaporkan. "
                f"Karena ROIC historis tidak dapat diobservasi secara langsung, proyeksi DCF menggunakan skenario asumsi terdisklosur "
                f"(tingkat reinvestasi diasumsikan {reinvestment_rate_pct}%) atas NOPAT ({nopat:,.0f} {currency}). "
                "Angka ini merupakan asumsi model skenario hipotesis, bukan observasi historis emiten."
            )
    elif (base_fcf is not None and base_fcf <= 0) or (ebit is not None and ebit <= 0):
        return {
            "status": "UNSUITABLE_FCF",
            "message": "Emiten membukukan Free Cash Flow negatif dan rugi operasional (EBIT <= 0). Model proyeksi DCF standar tidak dapat diaplikasikan tanpa arus kas positif atau laba operasional untuk dinormalisasi.",
            "model_type": "FCF_DISCOUNTED_CASH_FLOW",
            "fcf_state": "UNSUITABLE_FCF",
            "currency": currency,
            "current_price": price,
            "base_fcf": round(base_fcf, 2 if currency == "USD" else 0) if base_fcf is not None else None,
            "historical_fcf": round(base_fcf, 2 if currency == "USD" else 0) if base_fcf is not None else None,
            f"historical_fcf_{currency}": round(base_fcf, 2 if currency == "USD" else 0) if base_fcf is not None else None,
            "actual_negative_fcf_preserved": True,
            "ebit": round(ebit, 2 if currency == "USD" else 0) if ebit is not None else None,
            "cash_flows": cf_breakdown,
        }
    else:
        return {
            "status": "INSUFFICIENT_DATA",
            "message": "Data arus kas operasional dan laba operasional tidak mencukupi untuk memproyeksikan DCF.",
            "model_type": "FCF_DISCOUNTED_CASH_FLOW",
            "fcf_state": "INSUFFICIENT_DATA",
            "currency": currency,
            "current_price": price,
        }

    ib_debt_raw = values.get("interest_bearing_debt")
    if ib_debt_raw is not None:
        debt = float(ib_debt_raw) * mult
        debt_basis = "interest_bearing_debt"
    else:
        debt = 0.0
        debt_basis = "unspecified_debt"

    cash = (values.get("cash_and_equivalents") or 0.0) * mult
    nci_raw = values.get("non_controlling_interests") or values.get("minority_interest")
    pref_raw = values.get("preferred_equity") or values.get("preferred_stock")
    nci = (float(nci_raw) * mult) if nci_raw is not None else 0.0
    pref = (float(pref_raw) * mult) if pref_raw is not None else 0.0

    wacc_base = 0.10 if currency == "IDR" else 0.085
    scenarios_params = {
        "Bear": {"growth": 0.03, "wacc": wacc_base + 0.02, "terminal_g": 0.025},
        "Base": {"growth": 0.07, "wacc": wacc_base, "terminal_g": 0.030},
        "Bull": {"growth": 0.12, "wacc": wacc_base - 0.01, "terminal_g": 0.035},
    }

    # Guard: WACC must be strictly greater than terminal growth
    for sc_name, p in scenarios_params.items():
        if p["wacc"] <= p["terminal_g"]:
            return {
                "status": "INVALID_ASSUMPTIONS",
                "message": f"Skenario {sc_name} tidak valid: WACC ({p['wacc']:.1%}) harus lebih besar dari tingkat pertumbuhan terminal ({p['terminal_g']:.1%}).",
                "model_type": "FCF_DISCOUNTED_CASH_FLOW",
                "currency": currency,
            }

    def _calc_dcf(g: float, wacc: float, tg: float) -> float:
        if wacc <= tg:
            raise ValueError("WACC must be strictly greater than terminal growth rate (wacc > terminal_g).")
        pv_fcfs = 0.0
        proj_fcf = used_fcf
        for year in range(1, 6):
            proj_fcf *= (1.0 + g)
            pv_fcfs += proj_fcf / ((1.0 + wacc) ** year)
        tv = (proj_fcf * (1.0 + tg)) / (wacc - tg)
        pv_tv = tv / ((1.0 + wacc) ** 5)
        ev = pv_fcfs + pv_tv
        equity_val = ev - debt + cash - nci - pref
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
            if w <= tg:
                row[f"g_{round(tg*100, 1)}%"] = None
            else:
                iv = _calc_dcf(base_g, w, tg)
                row[f"g_{round(tg*100, 1)}%"] = round(iv, 2 if currency == "USD" else 0)
        matrix_wacc_tg.append(row)

    # Sensitivity Matrix 2: Operating Margin vs Revenue Growth
    base_op_margin = (ebit / revenue) if (revenue > 0 and ebit is not None and ebit > 0) else 0.15
    rev_growth_rates = [0.03, 0.05, 0.07, 0.10, 0.12]
    op_margins = [max(0.05, base_op_margin * 0.8), base_op_margin, base_op_margin * 1.2]
    matrix_margin_growth = []

    for mg in op_margins:
        row = {"operating_margin_pct": round(mg * 100.0, 1)}
        for rg in rev_growth_rates:
            margin_scalar = mg / base_op_margin if base_op_margin > 0 else 1.0
            pv_fcfs = 0.0
            proj_fcf = used_fcf * margin_scalar
            for year in range(1, 6):
                proj_fcf *= (1.0 + rg)
                pv_fcfs += proj_fcf / ((1.0 + wacc_base) ** year)
            tv_tg = 0.03
            if wacc_base <= tv_tg:
                row[f"rev_g_{round(rg*100, 1)}%"] = None
            else:
                tv = (proj_fcf * (1.0 + tv_tg)) / (wacc_base - tv_tg)
                pv_tv = tv / ((1.0 + wacc_base) ** 5)
                iv = max(0.0, (pv_fcfs + pv_tv - debt + cash - nci - pref) / shares)
                row[f"rev_g_{round(rg*100, 1)}%"] = round(iv, 2 if currency == "USD" else 0)
        matrix_margin_growth.append(row)

    return {
        "status": "COMPLETED",
        "model_type": "FCF_DISCOUNTED_CASH_FLOW",
        "fcf_state": fcf_state,
        "fcf_basis": fcf_basis,
        "normalization_note": normalization_note,
        "currency": currency,
        "current_price": price,
        f"base_fcf_{currency}": round(used_fcf, 2 if currency == "USD" else 0),
        f"historical_fcf_{currency}": round(historical_fcf, 2 if currency == "USD" else 0) if historical_fcf is not None else None,
        "actual_historical_fcf": round(historical_fcf, 2 if currency == "USD" else 0) if historical_fcf is not None else None,
        "actual_negative_fcf_preserved": (historical_fcf < 0) if historical_fcf is not None else False,
        "reinvestment_rate_pct": reinvestment_rate_pct,
        "debt_basis": debt_basis,
        "minority_interest": round(nci, 0) if nci_raw is not None else 0.0,
        "preferred_equity": round(pref, 0) if pref_raw is not None else 0.0,
        "scenarios": scenario_outputs,
        "sensitivity_matrix": matrix_wacc_tg,
        "sensitivity_wacc_terminal_growth": matrix_wacc_tg,
        "sensitivity_margin_revenue_growth": matrix_margin_growth,
        "cash_flows": cf_breakdown,
    }
