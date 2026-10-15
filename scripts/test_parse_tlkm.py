#!/usr/bin/env python3
"""Test parsing the authentic TLKM Q1 2026 financial report."""

import sys
from pathlib import Path
repo_root = Path(__file__).resolve().parents[1]
if str(repo_root) not in sys.path:
    sys.path.insert(0, str(repo_root))

from openbagus.domains.equities.parsers.pdf_parser import IdxPdfParser

def main():
    pdf_path = repo_root / "data/equities/downloads/TLKM/TW-I-2026-FS-Konsolidasian-Telkom-Bahasa.pdf"
    parser = IdxPdfParser()
    stmt = parser.parse_file(pdf_path, ticker="TLKM")
    print("=== PARSER RESULT ===")
    print("Symbol:", stmt.symbol)
    print("Period:", stmt.period)
    print("Period Type:", stmt.period_type)
    print("Currency:", stmt.currency)
    print("Unit:", stmt.unit)
    print("Multiplier:", stmt.unit_multiplier)
    print("Audit status:", stmt.audit_status)
    print("Validation status:", stmt.validation_status)
    print("Validation notes:", stmt.validation_notes)
    print("\nExtracted Line Items:")
    fields = [
        "revenue", "cost_of_revenue", "gross_profit", "operating_expenses",
        "operating_income", "profit_before_tax", "tax_expense", "net_income_total",
        "net_income_attributable", "total_assets", "total_liabilities", "total_equity",
        "cash_and_equivalents", "short_term_debt", "long_term_debt", "interest_bearing_debt",
        "operating_cash_flow", "capital_expenditures"
    ]
    for f in fields:
        val = getattr(stmt, f, None)
        if val is not None:
            print(f"  {f}: {val:,.2f}")
    print(f"\nTotal citations: {len(stmt.citations)}")
    for k, c in list(stmt.citations.items())[:6]:
        print(f"  {k}: Page {c.page_number}, row: '{c.row_label}', text: '{c.raw_reported_text}'")

if __name__ == "__main__":
    main()
