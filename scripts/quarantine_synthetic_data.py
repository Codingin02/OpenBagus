#!/usr/bin/env python3
"""Quarantine Migration Script for Synthetic Financial Statements & Facts.

This script identifies, documents, backs up, and quarantines fabricated financial
statement JSON files and contaminated rows in financial_facts.db for BBCA and RATU.

Features:
- Full backup to data/backup_pre_quarantine_20261015/
- Dry-run mode (--dry-run)
- Idempotent quarantine execution (--quarantine)
- Full rollback capability (--rollback)
- Generates data/quarantine_manifest.json with complete cryptographic hashes and audit trail
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import shutil
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("quarantine")

KNOWN_CONTAMINATED_SYMBOLS = ["BBCA", "RATU"]
SYNTHETIC_SOURCE_PATTERNS = [
    "https://www.idx.co.id/filings/BBCA_2024.json",
    "https://www.idx.co.id/filings/BBCA_2023.json",
    "https://www.idx.co.id/filings/RATU_2024.json",
    "https://www.idx.co.id/filings/RATU_2023.json",
]


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()


def run_dry_run(repo_root: Path) -> dict[str, Any]:
    logger.info("=== RUNNING DRY RUN INSPECTION ===")
    financials_dir = repo_root / "data" / "equities" / "financials"
    db_path = repo_root / "data" / "equities" / "financial_facts.db"

    files_to_quarantine = []
    for sym in KNOWN_CONTAMINATED_SYMBOLS:
        sym_dir = financials_dir / sym
        if sym_dir.exists():
            for f in sorted(sym_dir.glob("*.json")):
                files_to_quarantine.append({
                    "path": str(f.relative_to(repo_root)).replace("\\", "/"),
                    "size_bytes": f.stat().st_size,
                    "sha256": sha256_file(f),
                    "symbol": sym,
                    "period": f.stem,
                })

    db_rows_to_quarantine = []
    if db_path.exists():
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        for sym in KNOWN_CONTAMINATED_SYMBOLS:
            cur.execute(
                "SELECT fact_id, symbol, period, metric_name, value, validation_status, source_provider, source_url FROM financial_facts WHERE symbol = ?",
                (sym,),
            )
            rows = [dict(r) for r in cur.fetchall()]
            for r in rows:
                db_rows_to_quarantine.append(r)
        conn.close()

    logger.info("Found %d JSON files to quarantine: %s", len(files_to_quarantine), [f["path"] for f in files_to_quarantine])
    logger.info("Found %d DB fact rows to quarantine in financial_facts.db", len(db_rows_to_quarantine))
    return {
        "files_to_quarantine": files_to_quarantine,
        "db_rows_count": len(db_rows_to_quarantine),
        "db_rows": db_rows_to_quarantine,
    }


def run_backup(repo_root: Path) -> Path:
    backup_dir = repo_root / "data" / "backup_pre_quarantine_20261015"
    backup_dir.mkdir(parents=True, exist_ok=True)

    financials_dir = repo_root / "data" / "equities" / "financials"
    target_fin = backup_dir / "financials"
    if financials_dir.exists() and not target_fin.exists():
        shutil.copytree(financials_dir, target_fin)
        logger.info("Backed up %s to %s", financials_dir, target_fin)

    db_path = repo_root / "data" / "equities" / "financial_facts.db"
    target_db = backup_dir / "financial_facts.db"
    if db_path.exists() and not target_db.exists():
        shutil.copy2(db_path, target_db)
        logger.info("Backed up %s to %s", db_path, target_db)

    return backup_dir


def run_quarantine(repo_root: Path) -> Path:
    logger.info("=== STARTING QUARANTINE PROCESS ===")
    backup_dir = run_backup(repo_root)

    financials_dir = repo_root / "data" / "equities" / "financials"
    quarantine_base = repo_root / "data" / "quarantine" / "financials"
    quarantine_base.mkdir(parents=True, exist_ok=True)
    db_path = repo_root / "data" / "equities" / "financial_facts.db"

    manifest: dict[str, Any] = {
        "action": "QUARANTINE_SYNTHETIC_FINANCIAL_DATA",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "backup_location": str(backup_dir.relative_to(repo_root)).replace("\\", "/"),
        "quarantined_files": [],
        "quarantined_db_rows": [],
    }

    # 1. Move files to quarantine
    for sym in KNOWN_CONTAMINATED_SYMBOLS:
        sym_dir = financials_dir / sym
        if sym_dir.exists():
            target_sym_dir = quarantine_base / sym
            target_sym_dir.mkdir(parents=True, exist_ok=True)
            for f in sorted(sym_dir.glob("*.json")):
                file_rel = str(f.relative_to(repo_root)).replace("\\", "/")
                file_hash = sha256_file(f)
                file_size = f.stat().st_size
                content = json.loads(f.read_text(encoding="utf-8"))

                dest_file = target_sym_dir / f.name
                shutil.move(f, dest_file)
                logger.info("Moved %s -> %s", f, dest_file)

                manifest["quarantined_files"].append({
                    "original_path": file_rel,
                    "quarantine_path": str(dest_file.relative_to(repo_root)).replace("\\", "/"),
                    "sha256": file_hash,
                    "size_bytes": file_size,
                    "symbol": sym,
                    "period": f.stem,
                    "fabricated_source": content.get("source"),
                    "reason": "Synthetic financial statement generated without official primary source document or filing hash.",
                })
            # Remove empty sym_dir if empty
            try:
                sym_dir.rmdir()
            except OSError:
                pass

    # 2. Update DB records
    if db_path.exists():
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()

        now_iso = datetime.now(timezone.utc).isoformat()
        for sym in KNOWN_CONTAMINATED_SYMBOLS:
            cur.execute(
                "SELECT fact_id, symbol, period, metric_name, value, source_provider, source_url, validation_status FROM financial_facts WHERE symbol = ?",
                (sym,),
            )
            rows = [dict(r) for r in cur.fetchall()]
            for r in rows:
                manifest["quarantined_db_rows"].append({
                    "fact_id": r["fact_id"],
                    "symbol": r["symbol"],
                    "period": r["period"],
                    "metric_name": r["metric_name"],
                    "value": r["value"],
                    "source_provider": r["source_provider"],
                    "source_url": r["source_url"],
                    "prior_validation_status": r["validation_status"],
                    "new_validation_status": "QUARANTINED_SYNTHETIC",
                    "reason": "Synthetic seed fact lacking authentic primary source document hash",
                })

            cur.execute(
                """
                UPDATE financial_facts
                SET validation_status = 'QUARANTINED_SYNTHETIC',
                    computation_lineage = json_set(COALESCE(computation_lineage, '{}'), '$.quarantined_at', ?, '$.quarantine_reason', 'SYNTHETIC_SEED_DATA')
                WHERE symbol = ?;
                """,
                (now_iso, sym),
            )
            logger.info("Updated %d rows for %s to QUARANTINED_SYNTHETIC", cur.rowcount, sym)

        conn.commit()
        conn.close()

    manifest_path = repo_root / "data" / "quarantine_manifest.json"
    with open(manifest_path, "w", encoding="utf-8") as mf:
        json.dump(manifest, mf, indent=2, ensure_ascii=False)
    logger.info("Quarantine manifest written to %s", manifest_path)
    return manifest_path


def run_rollback(repo_root: Path) -> bool:
    logger.info("=== RUNNING ROLLBACK ===")
    backup_dir = repo_root / "data" / "backup_pre_quarantine_20261015"
    if not backup_dir.exists():
        logger.error("Backup directory %s does not exist! Cannot rollback.", backup_dir)
        return False

    financials_dir = repo_root / "data" / "equities" / "financials"
    backup_fin = backup_dir / "financials"
    if backup_fin.exists():
        for sym in KNOWN_CONTAMINATED_SYMBOLS:
            bf_sym = backup_fin / sym
            if bf_sym.exists():
                tf_sym = financials_dir / sym
                tf_sym.mkdir(parents=True, exist_ok=True)
                for f in bf_sym.glob("*.json"):
                    shutil.copy2(f, tf_sym / f.name)
                    logger.info("Restored %s", tf_sym / f.name)

    backup_db = backup_dir / "financial_facts.db"
    target_db = repo_root / "data" / "equities" / "financial_facts.db"
    if backup_db.exists():
        shutil.copy2(backup_db, target_db)
        logger.info("Restored database from %s", backup_db)

    # Clean quarantine directory
    quarantine_base = repo_root / "data" / "quarantine" / "financials"
    if quarantine_base.exists():
        for sym in KNOWN_CONTAMINATED_SYMBOLS:
            q_sym = quarantine_base / sym
            if q_sym.exists():
                shutil.rmtree(q_sym)

    logger.info("Rollback complete.")
    return True


def run_verify(repo_root: Path) -> bool:
    logger.info("=== VERIFYING QUARANTINE STATUS ===")
    financials_dir = repo_root / "data" / "equities" / "financials"
    for sym in KNOWN_CONTAMINATED_SYMBOLS:
        p = financials_dir / sym
        if p.exists() and any(p.glob("*.json")):
            logger.error("Verification failed: %s still contains JSON files in %s", sym, p)
            return False

    db_path = repo_root / "data" / "equities" / "financial_facts.db"
    if db_path.exists():
        conn = sqlite3.connect(str(db_path))
        cur = conn.cursor()
        cur.execute(
            "SELECT count(*) FROM financial_facts WHERE symbol IN ('BBCA', 'RATU') AND validation_status != 'QUARANTINED_SYNTHETIC';"
        )
        unquarantined = cur.fetchone()[0]
        cur.execute(
            "SELECT count(*) FROM financial_facts WHERE symbol IN ('BBCA', 'RATU') AND validation_status = 'QUARANTINED_SYNTHETIC';"
        )
        quarantined = cur.fetchone()[0]
        conn.close()

        if unquarantined > 0:
            logger.error("Verification failed: %d unquarantined rows found for BBCA/RATU in DB", unquarantined)
            return False
        logger.info("Database verification passed: 0 active rows, %d properly quarantined rows.", quarantined)

    logger.info("Verification passed completely. No synthetic records active.")
    return True


def main() -> None:
    parser = argparse.ArgumentParser(description="Quarantine synthetic financial statements & facts.")
    parser.add_argument("--dry-run", action="store_true", help="Inspect without modifying")
    parser.add_argument("--quarantine", action="store_true", help="Execute quarantine and backup")
    parser.add_argument("--rollback", action="store_true", help="Rollback from backup")
    parser.add_argument("--verify", action="store_true", help="Verify quarantine state")
    args = parser.parse_args()

    repo_root = Path(__file__).resolve().parent.parent

    if args.dry-run if hasattr(args, "dry-run") else args.dry_run:
        run_dry_run(repo_root)
    elif args.rollback:
        run_rollback(repo_root)
    elif args.verify:
        ok = run_verify(repo_root)
        sys.exit(0 if ok else 1)
    elif args.quarantine:
        run_quarantine(repo_root)
        run_verify(repo_root)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
