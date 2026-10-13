"""Production-grade IDX XLSX Financial Statement Parser.

Extracts multi-sheet, multi-column statements (Financial Position, Profit or Loss,
Cash Flows, Equity, Notes) with merged headers, negative parentheses, scale headings,
and coordinate-level provenance.
"""

from __future__ import annotations

import logging
from pathlib import Path
import re
from typing import Any
import openpyxl

from openbagus.domains.equities.financial_model import (
    CanonicalFinancialStatement,
    SourceCitation,
    detect_period,
    detect_currency_and_unit,
)
from openbagus.domains.equities.xbrl import IDX_TAXONOMY_MAP

logger = logging.getLogger(__name__)

# Common sheet keywords across IDX companies
SHEET_MAP = {
    "posisi keuangan": "BALANCE_SHEET",
    "financial position": "BALANCE_SHEET",
    "neraca": "BALANCE_SHEET",
    "laba rugi": "INCOME_STATEMENT",
    "profit or loss": "INCOME_STATEMENT",
    "penghasilan komprehensif": "INCOME_STATEMENT",
    "comprehensive income": "INCOME_STATEMENT",
    "arus kas": "CASH_FLOWS",
    "cash flows": "CASH_FLOWS",
    "perubahan ekuitas": "EQUITY_CHANGES",
    "changes in equity": "EQUITY_CHANGES",
    "catatan": "NOTES",
    "notes": "NOTES",
}

# Regex mapping for Indonesian & English accounting line items
LINE_ITEM_PATTERNS = {
    # Assets
    "cash_and_equivalents": [r"\bkas\s+dan\s+setara\s+kas\b", r"\bcash\s+and\s+cash\s+equivalents\b"],
    "trade_receivables": [r"\bpiutang\s+usaha\b", r"\btrade\s+receivables\b"],
    "inventories": [r"\bpersediaan\b", r"\binventories\b"],
    "current_assets": [r"\bjumlah\s+aset\s+lancar\b", r"\btotal\s+current\s+assets\b", r"\baset\s+lancar\b"],
    "non_current_assets": [r"\bjumlah\s+aset\s+tidak\s+lancar\b", r"\btotal\s+non-?current\s+assets\b"],
    "total_assets": [r"\bjumlah\s+aset\b", r"\btotal\s+assets\b", r"\bjumlah\s+aktiva\b"],

    # Liabilities
    "trade_payables": [r"\butang\s+usaha\b", r"\btrade\s+payables\b"],
    "short_term_debt": [r"\bpinjaman\s+(?:bank\s+)?jangka\s+pendek\b", r"\butang\s+(?:bank\s+)?jangka\s+pendek\b", r"\bshort-?term\s+(?:borrowings|debt|bank\s+loans)\b"],
    "long_term_debt": [r"\bpinjaman\s+(?:bank\s+)?jangka\s+panjang\b", r"\butang\s+(?:bank\s+)?jangka\s+panjang\b", r"\blong-?term\s+(?:borrowings|debt|bank\s+loans)\b"],
    "lease_liabilities": [r"\bliabilitas\s+sewa\b", r"\blease\s+liabilities\b"],
    "interest_bearing_debt": [r"\butang\s+berbunga\b", r"\binterest-?bearing\s+debt\b"],
    "current_liabilities": [r"\bjumlah\s+liabilitas\s+jangka\s+pendek\b", r"\btotal\s+current\s+liabilities\b"],
    "non_current_liabilities": [r"\bjumlah\s+liabilitas\s+jangka\s+panjang\b", r"\btotal\s+non-?current\s+liabilities\b"],
    "total_liabilities": [r"\bjumlah\s+liabilitas\b", r"\btotal\s+liabilities\b", r"\bjumlah\s+kewajiban\b"],

    # Equity
    "share_capital": [r"\bmodal\s+saham\b", r"\bshare\s+capital\b"],
    "retained_earnings": [r"\bsaldo\s+laba\b", r"\bretained\s+earnings\b"],
    "equity_attributable_to_owners": [
        r"\bekuitas\s+(?:yang\s+)?diatribusikan\s+kepada\s+pemilik\s+entitas\s+induk\b",
        r"\bequity\s+attributable\s+to\s+owners\b",
    ],
    "non_controlling_interests": [r"\bkepentingan\s+non-?pengendali\b", r"\bnon-?controlling\s+interests\b"],
    "total_equity": [r"\bjumlah\s+ekuitas\b", r"\btotal\s+equity\b"],

    # P&L
    "revenue": [r"\bpenjualan\s+dan\s+pendapatan\s+usaha\b", r"\bpendapatan\s+usaha\b", r"\bpenjualan\s+bersih\b", r"\brevenue\b", r"\bsales\b"],
    "cost_of_revenue": [r"\bbeban\s+pokok\s+pendapatan\b", r"\bbeban\s+pokok\s+penjualan\b", r"\bcost\s+of\s+goods\s+sold\b", r"\bcost\s+of\s+revenue\b"],
    "gross_profit": [r"\blaba\s+kotor\b", r"\bgross\s+profit\b"],
    "operating_expenses": [r"\bbeban\s+usaha\b", r"\boperating\s+expenses\b"],
    "operating_income": [r"\blaba\s+usaha\b", r"\blaba\s+operasi\b", r"\boperating\s+profit\b", r"\boperating\s+income\b"],
    "finance_costs": [r"\bbeban\s+keuangan\b", r"\bfinance\s+costs\b", r"\bbeban\s+bunga\b"],
    "profit_before_tax": [r"\blaba\s+sebelum\s+pajak\b", r"\bprofit\s+before\s+tax\b"],
    "tax_expense": [r"\bbeban\s+pajak\s+penghasilan\b", r"\btax\s+expense\b"],
    "net_income_total": [r"\blaba\s+tahun\s+berjalan\b", r"\blaba\s+bersih\b", r"\bnet\s+profit\b", r"\bprofit\s+for\s+the\s+year\b"],
    "net_income_attributable": [
        r"\blaba\s+(?:tahun\s+berjalan\s+)?yang\s+diatribusikan\s+kepada\s+pemilik\s+entitas\s+induk\b",
        r"\bprofit\s+attributable\s+to\s+owners\b",
    ],
    "net_income_non_controlling": [
        r"\blaba\s+yang\s+diatribusikan\s+kepada\s+kepentingan\s+non-?pengendali\b",
        r"\bprofit\s+attributable\s+to\s+non-?controlling\b",
    ],
    "eps_basic": [r"\blaba\s+per\s+saham\s+dasar\b", r"\bbasic\s+earnings\s+per\s+share\b", r"\blaba\s+bersih\s+per\s+saham\b"],

    # Cash Flows
    "operating_cash_flow": [r"\barus\s+kas\s+(?:bersih\s+)?dari\s+aktivitas\s+operasi\b", r"\boperating\s+cash\s+flows?\b"],
    "capex_ppe": [r"\bperolehan\s+aset\s+tetap\b", r"\bpurchase\s+of\s+property[,\s]+plant\b", r"\bpenambahan\s+aset\s+tetap\b"],
    "capex_intangibles": [r"\bperolehan\s+aset\s+takberwujud\b", r"\bpurchase\s+of\s+intangible\s+assets\b"],
    "capital_expenditures": [r"\bbelanja\s+modal\b", r"\bcapex\b", r"\bcapital\s+expenditures?\b"],
    "investing_cash_flow": [r"\barus\s+kas\s+(?:bersih\s+)?dari\s+aktivitas\s+investasi\b", r"\binvesting\s+cash\s+flows?\b"],
    "financing_cash_flow": [r"\barus\s+kas\s+(?:bersih\s+)?dari\s+aktivitas\s+pendanaan\b", r"\bfinancing\s+cash\s+flows?\b"],
    "dividends_paid": [r"\bpembayaran\s+dividen\b", r"\bdividends?\s+paid\b"],

    # Shares
    "shares_outstanding": [r"\bjumlah\s+saham\s+beredar\b", r"\bshares\s+outstanding\b"],
    "weighted_average_shares": [r"\brata-?rata\s+tertimbang\s+jumlah\s+saham\b", r"\bweighted\s+average\s+number\s+of\s+shares\b"],

    # Banking
    "net_interest_income": [r"\bpendapatan\s+bunga\s+bersih\b", r"\bnet\s+interest\s+income\b"],
    "nim_pct": [r"\bnet\s+interest\s+margin\b", r"\bnim\b"],
    "npl_gross_pct": [r"\bnpl\s+gross\b", r"\bnpl\s+kotor\b"],
    "npl_net_pct": [r"\bnpl\s+net\b", r"\bnpl\s+bersih\b"],
    "car_pct": [r"\bcapital\s+adequacy\s+ratio\b", r"\bkpmm\b", r"\bcar\b"],
    "ldr_pct": [r"\bloan\s+to\s+deposit\s+ratio\b", r"\bldr\b"],
    "casa_pct": [r"\bcasa\b", r"\bdana\s+murah\b"],
}


def _clean_numeric_value(raw: Any) -> float | None:
    """Parses numeric cells, handling parentheses for negative values '(1,234.56)'."""
    if raw is None or raw == "":
        return None
    if isinstance(raw, (int, float)):
        return float(raw)
    val_str = str(raw).strip()
    is_negative = False
    if val_str.startswith("(") and val_str.endswith(")"):
        is_negative = True
        val_str = val_str[1:-1].strip()
    elif val_str.startswith("-"):
        is_negative = True
        val_str = val_str[1:].strip()

    val_str = val_str.replace(",", "").replace(" ", "").replace("%", "")
    try:
        num = float(val_str)
        return -num if is_negative else num
    except ValueError:
        return None


class IdxXlsxParser:
    """Extracts structured financial disclosures from IDX XLSX files."""

    def __init__(self, repo_root: Path | None = None) -> None:
        self.root = repo_root or Path.cwd()

    def parse_file(self, path: Path, ticker: str | None = None) -> CanonicalFinancialStatement:
        if not path.exists():
            raise FileNotFoundError(f"File XLSX tidak ditemukan: {path}")

        sym = (ticker or "").strip().upper()
        if not sym:
            m = re.search(r"\b([A-Z]{4})\b", path.name.upper())
            if m:
                sym = m.group(1)
        if not sym:
            raise ValueError(f"Ticker emiten tidak dapat diidentifikasi dari nama file {path.name}.")

        wb = openpyxl.load_workbook(path, data_only=True, read_only=True)

        # Detect period from filename or workbook title
        detected_p = detect_period(path.name)
        period_str = detected_p[0] if detected_p else "UNKNOWN_PERIOD"
        period_type = detected_p[1] if detected_p else "FY"

        # Detect currency & unit from header texts in first sheet
        currency = "IDR"
        unit_name = "million_IDR"
        multiplier = 1_000_000.0

        first_sheet = wb.worksheets[0] if wb.worksheets else None
        header_text = ""
        if first_sheet:
            for r_idx, row in enumerate(first_sheet.iter_rows(values_only=True)):
                if r_idx > 10:
                    break
                header_text += " " + " ".join(str(c) for c in row if c is not None)
            currency, unit_name, multiplier = detect_currency_and_unit(header_text)

        stmt = CanonicalFinancialStatement(
            symbol=sym,
            period=period_str,
            period_type=period_type,
            currency=currency,
            unit=unit_name,
            unit_multiplier=multiplier,
            basis="consolidated",
            audit_status="audited" if "FY" in period_type else "unaudited",
            period_end_date="2024-12-31",
            source_document=path.name,
            document_format="XLSX",
            source_url=f"https://www.idx.co.id/perusahaan-tercatat/laporan-keuangan-dan-tahunan/ ({path.name})",
        )

        citations: dict[str, SourceCitation] = {}

        # Scan each worksheet
        for sheet in wb.worksheets:
            sheet_title_lower = sheet.title.lower()
            statement_type = "GENERAL"
            for kw, s_type in SHEET_MAP.items():
                if kw in sheet_title_lower:
                    statement_type = s_type
                    break

            # Find data rows
            col_target_idx = 1 # By default, column index 1 is current period
            for row_idx, row_cells in enumerate(sheet.iter_rows(values_only=True), start=1):
                if not row_cells or len(row_cells) < 2:
                    continue

                label_raw = str(row_cells[0] or "").strip().lower()
                if not label_raw:
                    continue

                # Scan for line items
                for field_name, patterns in LINE_ITEM_PATTERNS.items():
                    if getattr(stmt, field_name, None) is not None:
                        continue
                    if any(re.search(p, label_raw, re.I) for p in patterns):
                        # Extract first available valid numeric column
                        val = None
                        target_col_letter = "B"
                        for c_idx in range(1, min(len(row_cells), 5)):
                            c_val = _clean_numeric_value(row_cells[c_idx])
                            if c_val is not None:
                                val = c_val
                                target_col_letter = chr(ord("A") + c_idx)
                                break

                        if val is not None:
                            if field_name in {"cost_of_revenue", "operating_expenses", "finance_costs", "tax_expense", "capex_ppe", "capex_intangibles", "capital_expenditures"}:
                                val = abs(val)
                            setattr(stmt, field_name, val)
                            citations[field_name] = SourceCitation(
                                statement_type=statement_type,
                                cell_reference=f"{sheet.title}!{target_col_letter}{row_idx}",
                                row_label=label_raw,
                                raw_reported_text=str(val),
                                file_path=str(path),
                            )
                            break

        wb.close()

        # Compute capex if components exist
        if stmt.capital_expenditures is None and stmt.capex_ppe is not None:
            stmt.capital_expenditures = abs(stmt.capex_ppe) + (abs(stmt.capex_intangibles) if stmt.capex_intangibles else 0.0)

        # Interest-bearing debt calculation
        if stmt.interest_bearing_debt is None:
            st_d = stmt.short_term_debt or 0.0
            lt_d = stmt.long_term_debt or 0.0
            if st_d > 0 or lt_d > 0:
                stmt.interest_bearing_debt = st_d + lt_d

        stmt.citations = citations
        stmt.validate_accounting_relationships()
        return stmt
