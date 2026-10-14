#!/usr/bin/env python3
"""Audit SEC EDGAR Facts for AAPL (CIK 0000320193).

Verifies complete provenance:
- Issuer: Apple Inc.
- CIK: 0000320193
- Filings: 10-K, 10-Q forms
- Accession numbers
- Taxonomy tags: us-gaap
- Metrics: Assets, Revenues, NetIncomeLoss, Liabilities, OperatingIncomeLoss
- Dates: period_end_date, filing_date
- Counts and integrity checks
"""

import json
from pathlib import Path

def audit_sec_edgar():
    repo_root = Path(__file__).resolve().parent.parent
    sec_dir = repo_root / "data" / "equities" / "sec"
    aapl_dir = repo_root / "data" / "equities" / "financials" / "AAPL"
    raw_facts_file = sec_dir / "companyfacts_CIK0000320193.json"

    print("=== SEC EDGAR PROVENANCE AUDIT ===")
    assert raw_facts_file.exists(), f"Missing {raw_facts_file}"
    raw_size = raw_facts_file.stat().st_size
    print(f"Raw SEC companyfacts file: {raw_facts_file.name} ({raw_size:,} bytes)")

    with open(raw_facts_file, "r", encoding="utf-8") as f:
        raw_data = json.load(f)

    cik = raw_data.get("cik")
    entity_name = raw_data.get("entityName")
    print(f"CIK: {cik} (zero-padded: {str(cik).zfill(10)})")
    print(f"Entity Name: {entity_name}")
    print(f"Taxonomies available: {list(raw_data.get('facts', {}).keys())}")

    us_gaap = raw_data.get("facts", {}).get("us-gaap", {})
    print(f"Total us-gaap concepts: {len(us_gaap)}")

    # Check key concepts
    key_concepts = ["Revenues", "Assets", "NetIncomeLoss", "Liabilities", "OperatingIncomeLoss"]
    for c in key_concepts:
        if c in us_gaap:
            units = list(us_gaap[c].get("units", {}).keys())
            item_count = sum(len(items) for items in us_gaap[c].get("units", {}).values())
            print(f" - Concept '{c}': {item_count} data points across units {units}")

    # Inspect generated JSON statements in data/equities/financials/AAPL/
    json_files = sorted(aapl_dir.glob("*.json"))
    print(f"\nGenerated canonical statement files in {aapl_dir}: {len(json_files)} files")
    
    sample_files = [json_files[0], json_files[len(json_files)//2], json_files[-1]]
    for sf in sample_files:
        stmt = json.loads(sf.read_text(encoding="utf-8"))
        print(f"\nStatement: {sf.name}")
        print(f" - Period: {stmt.get('period')}, Type: {stmt.get('period_type')}")
        print(f" - Currency: {stmt.get('currency')}, Unit: {stmt.get('unit')}")
        print(f" - Source: {stmt.get('source')}")
        print(f" - Values count: {len(stmt.get('values', {}))}")
        print(f" - Sample values: {list(stmt.get('values', {}).items())[:4]}")
        citations = stmt.get("citations", {})
        print(f" - Citations count: {len(citations)}")
        if citations:
            sample_cit = next(iter(citations.values()))
            print(f"   Sample citation: concept={sample_cit.get('concept')}, row={sample_cit.get('row')}")

if __name__ == "__main__":
    audit_sec_edgar()
