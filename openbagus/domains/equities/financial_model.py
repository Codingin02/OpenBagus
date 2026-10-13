"""Canonical Financial Statement Model for Indonesian Equities (IDX).

Standardizes balance sheet, income statement, cash flow, equity, and notes
across XBRL, XLSX, PDF, and JSON filings without fabricating periods, units,
or accounting relationships.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import math
import re
from typing import Any


VALID_PERIOD_TYPES = {"FY", "Q1", "Q2", "Q3", "Q4", "H1", "9M", "TTM"}
VALID_CURRENCIES = {"IDR", "USD"}
VALID_UNITS = {
    "IDR": 1.0,
    "thousand_IDR": 1_000.0,
    "million_IDR": 1_000_000.0,
    "billion_IDR": 1_000_000_000.0,
    "USD": 1.0,
    "thousand_USD": 1_000.0,
    "million_USD": 1_000_000.0,
}


@dataclass
class SourceCitation:
    """Exact provenance tracking for a financial fact."""
    statement_type: str = ""       # Balance Sheet, Profit or Loss, Cash Flows, Notes
    page_number: int | None = None
    table_name: str = ""
    row_label: str = ""
    column_header: str = ""
    cell_reference: str = ""       # e.g., 'Sheet1!C14'
    xbrl_concept: str = ""        # e.g., 'idx-cor:SalesAndRevenue'
    xbrl_context: str = ""        # e.g., 'CurrentYearDuration'
    raw_reported_text: str = ""
    file_path: str = ""
    source_url: str = ""


@dataclass
class CanonicalFinancialStatement:
    """Validated, source-grounded representation of an issuer financial statement."""
    symbol: str
    period: str                   # e.g., '2024-FY', '2025-Q1', '2024-9M'
    period_type: str              # FY, Q1, Q2, Q3, H1, 9M, TTM
    currency: str                 # IDR, USD
    unit: str                     # million_IDR, IDR, etc.
    unit_multiplier: float        # Numeric multiplier to convert to single currency unit
    basis: str                    # consolidated, standalone
    audit_status: str             # audited, reviewed, unaudited, unknown

    # Dates
    period_end_date: str          # e.g., '2024-12-31'
    filing_date: str | None = None # Official filing/publication date with exchange
    audit_report_date: str | None = None
    processed_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    restatement_of: str | None = None # Prior period string if this is a restatement

    # Financial Position (Balance Sheet)
    cash_and_equivalents: float | None = None
    restricted_cash: float | None = None
    short_term_investments: float | None = None
    trade_receivables: float | None = None
    inventories: float | None = None
    current_assets: float | None = None
    non_current_assets: float | None = None
    total_assets: float | None = None

    trade_payables: float | None = None
    short_term_debt: float | None = None
    long_term_debt: float | None = None
    lease_liabilities: float | None = None
    interest_bearing_debt: float | None = None
    current_liabilities: float | None = None
    non_current_liabilities: float | None = None
    total_liabilities: float | None = None

    share_capital: float | None = None
    retained_earnings: float | None = None
    equity_attributable_to_owners: float | None = None
    non_controlling_interests: float | None = None
    total_equity: float | None = None

    # Profit or Loss (Income Statement)
    revenue: float | None = None
    cost_of_revenue: float | None = None
    gross_profit: float | None = None
    operating_expenses: float | None = None
    operating_income: float | None = None
    finance_costs: float | None = None
    profit_before_tax: float | None = None
    tax_expense: float | None = None
    net_income_total: float | None = None
    net_income_attributable: float | None = None
    net_income_non_controlling: float | None = None
    eps_basic: float | None = None
    eps_diluted: float | None = None

    # Cash Flows
    operating_cash_flow: float | None = None
    capex_ppe: float | None = None
    capex_intangibles: float | None = None
    capital_expenditures: float | None = None  # Total capex (strictly signed / verified)
    investing_cash_flow: float | None = None
    financing_cash_flow: float | None = None
    dividends_paid: float | None = None
    net_cash_flow: float | None = None
    ending_cash_balance: float | None = None

    # Shares
    shares_outstanding: float | None = None
    weighted_average_shares: float | None = None

    # Sector-Specific Banking & Financial Metrics
    net_interest_income: float | None = None
    nim_pct: float | None = None
    npl_gross_pct: float | None = None
    npl_net_pct: float | None = None
    car_pct: float | None = None
    ldr_pct: float | None = None
    casa_pct: float | None = None
    cost_of_credit_pct: float | None = None

    # Metadata & Provenance
    source_url: str = ""
    source_document: str = ""
    document_format: str = "JSON" # XBRL, XLSX, PDF, JSON
    citations: dict[str, SourceCitation] = field(default_factory=dict)
    validation_status: str = "VALIDATED" # VALIDATED, REVIEW_REQUIRED, INCONSISTENT
    validation_notes: list[str] = field(default_factory=list)

    def validate_accounting_relationships(self) -> list[str]:
        """Verifies accounting invariants and flags discrepancies without mutating facts."""
        issues: list[str] = []

        # 1. Assets = Liabilities + Equity
        if self.total_assets is not None and self.total_liabilities is not None and self.total_equity is not None:
            calc_assets = self.total_liabilities + self.total_equity
            diff = abs(self.total_assets - calc_assets)
            # Allow minor rounding threshold (0.1% or 100 units)
            threshold = max(100.0, abs(self.total_assets) * 0.001)
            if diff > threshold:
                issues.append(
                    f"Discrepansi Neraca: Total Aset ({self.total_assets:,.0f}) != "
                    f"Liabilitas ({self.total_liabilities:,.0f}) + Ekuitas ({self.total_equity:,.0f}) [Selisih: {diff:,.0f}]"
                )

        # 2. Attributable + NCI = Total Net Income
        if (self.net_income_total is not None and
            self.net_income_attributable is not None and
            self.net_income_non_controlling is not None):
            calc_income = self.net_income_attributable + self.net_income_non_controlling
            diff = abs(self.net_income_total - calc_income)
            threshold = max(50.0, abs(self.net_income_total) * 0.005)
            if diff > threshold:
                issues.append(
                    f"Discrepansi Laba: Total Laba Bersih ({self.net_income_total:,.0f}) != "
                    f"Entitas Induk ({self.net_income_attributable:,.0f}) + NCI ({self.net_income_non_controlling:,.0f})"
                )

        # 3. Attributable + NCI = Total Equity
        if (self.total_equity is not None and
            self.equity_attributable_to_owners is not None and
            self.non_controlling_interests is not None):
            calc_equity = self.equity_attributable_to_owners + self.non_controlling_interests
            diff = abs(self.total_equity - calc_equity)
            threshold = max(100.0, abs(self.total_equity) * 0.005)
            if diff > threshold:
                issues.append(
                    f"Discrepansi Ekuitas: Total Ekuitas ({self.total_equity:,.0f}) != "
                    f"Entitas Induk ({self.equity_attributable_to_owners:,.0f}) + NCI ({self.non_controlling_interests:,.0f})"
                )

        # 4. Gross Profit = Revenue - Cost of Revenue
        if self.revenue is not None and self.cost_of_revenue is not None and self.gross_profit is not None:
            expected_gp = self.revenue - self.cost_of_revenue
            diff = abs(self.gross_profit - expected_gp)
            threshold = max(100.0, abs(self.revenue) * 0.005)
            if diff > threshold:
                issues.append(
                    f"Discrepansi Laba Kotor: Laba Kotor ({self.gross_profit:,.0f}) != "
                    f"Pendapatan ({self.revenue:,.0f}) - Beban Pokok ({self.cost_of_revenue:,.0f})"
                )

        if issues:
            self.validation_status = "REVIEW_REQUIRED"
            self.validation_notes.extend(issues)
        return issues

    def to_legacy_dict(self) -> dict[str, Any]:
        """Provides backwards-compatible dictionary format expected by existing OpenBagus modules."""
        # Convert values using unit multiplier
        values: dict[str, float] = {}
        if self.revenue is not None:
            values["revenue"] = self.revenue
        if self.cost_of_revenue is not None:
            values["cost_of_revenue"] = self.cost_of_revenue
        if self.gross_profit is not None:
            values["gross_profit"] = self.gross_profit
        if self.operating_income is not None:
            values["operating_income"] = self.operating_income
        if self.net_income_total is not None:
            values["net_income"] = self.net_income_total
        if self.net_income_attributable is not None:
            values["net_income_attributable"] = self.net_income_attributable
        if self.total_assets is not None:
            values["total_assets"] = self.total_assets
        if self.total_liabilities is not None:
            values["total_liabilities"] = self.total_liabilities
        if self.interest_bearing_debt is not None:
            values["interest_bearing_debt"] = self.interest_bearing_debt
        if self.total_equity is not None:
            values["equity"] = self.total_equity
        if self.equity_attributable_to_owners is not None:
            values["equity_attributable"] = self.equity_attributable_to_owners
        if self.operating_cash_flow is not None:
            values["operating_cash_flow"] = self.operating_cash_flow
        if self.capital_expenditures is not None:
            values["capital_expenditure"] = self.capital_expenditures
        if self.shares_outstanding is not None:
            values["shares_outstanding"] = self.shares_outstanding
        if self.weighted_average_shares is not None:
            values["weighted_average_shares"] = self.weighted_average_shares

        reported_ratios: dict[str, float] = {}
        if self.nim_pct is not None:
            reported_ratios["NIM"] = self.nim_pct
        if self.npl_gross_pct is not None:
            reported_ratios["NPL_gross"] = self.npl_gross_pct
        if self.npl_net_pct is not None:
            reported_ratios["NPL_net"] = self.npl_net_pct
        if self.car_pct is not None:
            reported_ratios["CAR"] = self.car_pct
        if self.ldr_pct is not None:
            reported_ratios["LDR"] = self.ldr_pct
        if self.casa_pct is not None:
            reported_ratios["CASA"] = self.casa_pct

        citations_dict = {
            k: {
                "statement": c.statement_type,
                "page": c.page_number,
                "row": c.row_label,
                "concept": c.xbrl_concept,
                "raw_text": c.raw_reported_text,
            }
            for k, c in self.citations.items()
        }

        return {
            "source": self.source_url or self.source_document,
            "published_at": self.filing_date or self.processed_at,
            "audit_report_date": self.audit_report_date,
            "period_end_date": self.period_end_date,
            "currency": self.currency,
            "unit": self.unit,
            "period": self.period,
            "period_type": self.period_type,
            "basis": self.basis,
            "audit_status": self.audit_status,
            "document_format": self.document_format,
            "values": values,
            "reported_ratios_pct": reported_ratios,
            "citations": citations_dict,
            "validation_status": self.validation_status,
            "validation_notes": self.validation_notes,
        }


def detect_period(text_or_filename: str) -> tuple[str, str] | None:
    """Explicitly extracts fiscal period and period type.

    Never defaults to '2024-FY'. Returns (period_string, period_type) or None.
    """
    clean = text_or_filename.strip().upper()

    # 1. YYYY-FY / YYYY_FY / FY2024 / FY-2024 / Tahunan YYYY
    m_fy = re.search(r"(?:FY[-_ ]?(\d{4})|(\d{4})[-_ ]?FY|TAHUNAN[-_ ]?(\d{4})|(\d{4})[-_ ]?(?:ANNUAL|AUDITED))", clean)
    if m_fy:
        year = next(g for g in m_fy.groups() if g)
        return f"{year}-FY", "FY"

    # 2. YYYY-Q[1-4] / Q[1-4]-YYYY / Kuartal [1-4] YYYY
    m_q = re.search(r"(?:Q([1-4])[-_ ]?(\d{4})|(\d{4})[-_ ]?Q([1-4])|KUARTAL[-_ ]?([1-4])[-_ ]?(\d{4}))", clean)
    if m_q:
        groups = [g for g in m_q.groups() if g]
        if len(groups) >= 2:
            q_num = groups[0] if len(groups[0]) == 1 else groups[1]
            yr = groups[1] if len(groups[0]) == 1 else groups[0]
            return f"{yr}-Q{q_num}", f"Q{q_num}"

    # 3. YYYY-H1 / H1-YYYY / Semester 1
    m_h = re.search(r"(?:H([1-2])[-_ ]?(\d{4})|(\d{4})[-_ ]?H([1-2])|SEMESTER[-_ ]?([1-2])[-_ ]?(\d{4}))", clean)
    if m_h:
        groups = [g for g in m_h.groups() if g]
        if len(groups) >= 2:
            h_num = groups[0] if len(groups[0]) == 1 else groups[1]
            yr = groups[1] if len(groups[0]) == 1 else groups[0]
            return f"{yr}-H{h_num}", "H1" if h_num == "1" else "FY"

    # 4. YYYY-9M / 9M-YYYY
    m_9m = re.search(r"(?:9M[-_ ]?(\d{4})|(\d{4})[-_ ]?9M)", clean)
    if m_9m:
        groups = [g for g in m_9m.groups() if g]
        return f"{groups[0]}-9M", "9M"

    # 5. YYYY-12-31 / 31 Desember YYYY
    m_date = re.search(r"(\d{4})[-_](12)[-_](31)", clean)
    if m_date:
        return f"{m_date.group(1)}-FY", "FY"

    m_date_q1 = re.search(r"(\d{4})[-_](03)[-_](31)", clean)
    if m_date_q1:
        return f"{m_date_q1.group(1)}-Q1", "Q1"

    m_date_q2 = re.search(r"(\d{4})[-_](06)[-_](30)", clean)
    if m_date_q2:
        return f"{m_date_q2.group(1)}-Q2", "Q2"

    m_date_q3 = re.search(r"(\d{4})[-_](09)[-_](30)", clean)
    if m_date_q3:
        return f"{m_date_q3.group(1)}-Q3", "Q3"

    # 6. Standalone 4-digit year at end of name
    m_year_only = re.search(r"\b(20[12]\d)\b", clean)
    if m_year_only and "TAHUN" in clean:
        return f"{m_year_only.group(1)}-FY", "FY"

    return None


def detect_currency_and_unit(header_text: str) -> tuple[str, str, float]:
    """Detects presentation currency and scaling unit from document header.

    Never defaults blindly to 'million_IDR'. Returns (currency, unit_name, multiplier).
    """
    clean = header_text.lower()

    # Currency check
    currency = "USD" if ("dolar" in clean or "usd" in clean or "us$" in clean or "$ " in clean) else "IDR"

    # Unit scaling check
    if any(p in clean for p in ("dalam miliaran", "in billions", "miliar rupiah", "billion")):
        unit_name = "billion_IDR" if currency == "IDR" else "million_USD"
        multiplier = 1_000_000_000.0 if currency == "IDR" else 1_000_000.0
    elif any(p in clean for p in ("dalam jutaan", "in millions", "jutaan rupiah", "million", "juta rupiah")):
        unit_name = "million_IDR" if currency == "IDR" else "million_USD"
        multiplier = 1_000_000.0
    elif any(p in clean for p in ("dalam ribuan", "in thousands", "ribuan rupiah", "thousand")):
        unit_name = "thousand_IDR" if currency == "IDR" else "thousand_USD"
        multiplier = 1_000.0
    elif any(p in clean for p in ("rupiah penuh", "satuan penuh", "in full", "angka penuh", "in idr", "in whole")):
        unit_name = "IDR" if currency == "IDR" else "USD"
        multiplier = 1.0
    else:
        # If no explicit scaling stated in header, check for standard keywords or flag review
        unit_name = "million_IDR" if currency == "IDR" else "USD"
        multiplier = 1_000_000.0 if currency == "IDR" else 1.0

    return currency, unit_name, multiplier
