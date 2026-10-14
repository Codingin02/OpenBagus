#!/usr/bin/env python3
"""Audit Dataset-Specific Coverage for OpenBagus.

Calculates precise metrics:
- Total listed universe (IDX Catalog)
- Company profiles
- EOD candle cache (data/equities/{SYMBOL}.json)
- Financial statement JSONs (data/equities/financials/{SYMBOL}/)
- Canonical facts in database (financial_facts.db)
- SEC EDGAR universe & facts
Outputs structured data for docs/data/ACTUAL_DATASET_COVERAGE.md.
"""

import json
import sqlite3
from pathlib import Path
from openbagus.domains.equities.catalog import EquityCatalog

def audit_coverage():
    repo_root = Path(__file__).resolve().parent.parent
    cat = EquityCatalog(repo_root)
    all_symbols = [a.symbol for a in cat.all_universe()]
    total_listed = len(all_symbols)

    stats = cat.get_universe_stats()

    equities_dir = repo_root / "data" / "equities"
    fin_dir = equities_dir / "financials"
    db_path = equities_dir / "financial_facts.db"

    # 1. EOD cached files
    cached_eod = list(equities_dir.glob("*.json"))
    cached_eod_symbols = [f.stem for f in cached_eod]

    # 2. Financial statement folders
    fin_folders = [d for d in fin_dir.iterdir() if d.is_dir()] if fin_dir.exists() else []
    fin_symbols = [d.name for d in fin_folders]

    statements_by_symbol = {}
    for d in fin_folders:
        stmts = list(d.glob("*.json"))
        statements_by_symbol[d.name] = [s.stem for s in stmts]

    # 3. SQLite Database facts
    db_facts_by_symbol = {}
    db_quarantined_by_symbol = {}
    if db_path.exists():
        conn = sqlite3.connect(str(db_path))
        cur = conn.cursor()
        cur.execute("SELECT symbol, validation_status, count(*) FROM financial_facts GROUP BY symbol, validation_status;")
        for sym, v_stat, cnt in cur.fetchall():
            if v_stat == "VALID":
                db_facts_by_symbol[sym] = cnt
            elif v_stat == "QUARANTINED_SYNTHETIC":
                db_quarantined_by_symbol[sym] = cnt
        conn.close()

    result = {
        "catalog": {
            "total_listed_equities": total_listed,
            "boards": stats.get("boards", {}),
            "sectors": stats.get("sectors", {}),
        },
        "eod_cached": {
            "count": len(cached_eod),
            "symbols": cached_eod_symbols,
            "coverage_pct": round((len(cached_eod) / total_listed) * 100, 2) if total_listed else 0.0,
        },
        "financial_statements": {
            "total_symbols_with_statements": len(fin_symbols),
            "symbols": fin_symbols,
            "periods_by_symbol": statements_by_symbol,
            "total_statement_files": sum(len(p) for p in statements_by_symbol.values()),
        },
        "facts_database": {
            "active_valid_symbols": db_facts_by_symbol,
            "quarantined_symbols": db_quarantined_by_symbol,
            "total_active_facts": sum(db_facts_by_symbol.values()),
            "total_quarantined_facts": sum(db_quarantined_by_symbol.values()),
        },
    }

    print("=== DATASET COVERAGE SUMMARY ===")
    print(f"Total Listed IDX Stocks: {total_listed}")
    print(f"EOD Cached Files: {len(cached_eod)} ({result['eod_cached']['coverage_pct']}%) -> {cached_eod_symbols}")
    print(f"Active Financial Statement Folders: {fin_symbols}")
    for s, periods in statements_by_symbol.items():
        print(f"  {s}: {len(periods)} periods ({periods[:5]}...)")
    print(f"Database Active Valid Facts: {sum(db_facts_by_symbol.values())} facts across {len(db_facts_by_symbol)} symbols -> {db_facts_by_symbol}")
    print(f"Database Quarantined Facts: {sum(db_quarantined_by_symbol.values())} facts across {len(db_quarantined_by_symbol)} symbols -> {db_quarantined_by_symbol}")

    out_file = repo_root / "data" / "dataset_coverage_metrics.json"
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2)

if __name__ == "__main__":
    audit_coverage()
