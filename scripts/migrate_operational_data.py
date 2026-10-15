"""Cross-Worktree Operational Data Migration and Synchronization Tool for OpenBagus.

Synchronizes operational financial data, downloads, SQLite fact databases, and filings
to a unified operational root (e.g. %LOCALAPPDATA%\\OpenBagus\\data) so all worktrees
(OpenBagus main, OpenBagus-Data, OpenBagus-Voice) access canonical data without divergence.

Features:
- Automated pre-migration backup to %LOCALAPPDATA%\\OpenBagus\\backups
- SHA-256 hash calculation and verification before and after copy
- SQLite PRAGMA integrity_check for all database files
- Deduplication (skips bit-identical files)
- Dry-run mode (--dry-run)
- Rollback capability (--rollback <backup_directory>)
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
logger = logging.getLogger("migrate_operational_data")


def compute_sha256(path: Path) -> str:
    """Computes SHA-256 hash of a file."""
    h = hashlib.sha256()
    with path.open("rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()


def check_sqlite_integrity(db_path: Path) -> tuple[bool, str]:
    """Runs PRAGMA integrity_check on a SQLite database."""
    if not db_path.exists():
        return False, "File does not exist"
    try:
        conn = sqlite3.connect(str(db_path), timeout=10.0)
        try:
            cursor = conn.cursor()
            cursor.execute("PRAGMA integrity_check;")
            res = cursor.fetchone()
            status = res[0] if res else "UNKNOWN"
            return (status == "ok"), status
        finally:
            conn.close()
    except Exception as e:
        return False, str(e)


def get_default_target() -> Path:
    """Returns default operational data root."""
    env_root = os.environ.get("OPENBAGUS_DATA_ROOT")
    if env_root:
        return Path(env_root).resolve()
    local_app_data = os.environ.get("LOCALAPPDATA")
    if local_app_data:
        return Path(local_app_data) / "OpenBagus" / "data"
    return Path.home() / ".local" / "share" / "openbagus" / "data"


def get_default_source() -> Path:
    """Returns source data directory from repository root."""
    return Path(__file__).resolve().parents[1] / "data"


def create_backup(target_dir: Path) -> Path | None:
    """Creates a timestamped backup of target directory if it contains existing data."""
    if not target_dir.exists() or not any(target_dir.iterdir()):
        return None
    backup_root = target_dir.parent / "backups"
    backup_root.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    backup_dir = backup_root / f"backup_{ts}"
    logger.info("Creating backup of existing target data at: %s", backup_dir)
    shutil.copytree(target_dir, backup_dir)
    return backup_dir


def rollback(backup_dir: Path, target_dir: Path) -> bool:
    """Restores target directory from a previous backup."""
    if not backup_dir.exists():
        logger.error("Backup directory does not exist: %s", backup_dir)
        return False
    logger.info("Rolling back target %s from backup %s...", target_dir, backup_dir)
    if target_dir.exists():
        shutil.rmtree(target_dir)
    shutil.copytree(backup_dir, target_dir)
    logger.info("Rollback complete.")
    return True


def run_migration(
    source_dir: Path,
    target_dir: Path,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Executes the data migration with provenance checks and deduplication."""
    logger.info("Starting operational data migration:")
    logger.info("  Source: %s", source_dir)
    logger.info("  Target: %s", target_dir)
    logger.info("  Dry-run: %s", dry_run)

    if not source_dir.exists():
        raise FileNotFoundError(f"Source directory does not exist: {source_dir}")

    report: dict[str, Any] = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "source": str(source_dir),
        "target": str(target_dir),
        "dry_run": dry_run,
        "backup_created": None,
        "files_scanned": 0,
        "files_copied": 0,
        "files_skipped_identical": 0,
        "bytes_migrated": 0,
        "sqlite_checks": {},
        "file_details": [],
        "errors": [],
    }

    # 1. Source SQLite Pre-Check
    for db_path in source_dir.rglob("*.db"):
        ok, status = check_sqlite_integrity(db_path)
        report["sqlite_checks"][f"source:{db_path.name}"] = {"ok": ok, "status": status}
        if not ok:
            logger.error("Source SQLite database corrupted: %s (%s)", db_path, status)
            report["errors"].append(f"Corrupted source DB: {db_path} ({status})")

    if report["errors"] and not dry_run:
        raise ValueError(f"Migration aborted due to source corruption: {report['errors']}")

    # 2. Target Backup
    if not dry_run and target_dir.exists():
        backup_path = create_backup(target_dir)
        if backup_path:
            report["backup_created"] = str(backup_path)

    # 3. File scan and synchronization
    source_files = [p for p in source_dir.rglob("*") if p.is_file() and not p.name.endswith("-journal") and not p.name.endswith("-wal") and not p.name.endswith("-shm")]
    report["files_scanned"] = len(source_files)

    for src_file in source_files:
        rel_path = src_file.relative_to(source_dir)
        dest_file = target_dir / rel_path
        size = src_file.stat().st_size
        src_hash = compute_sha256(src_file)

        dest_exists = dest_file.exists()
        dest_hash = compute_sha256(dest_file) if dest_exists else None

        if dest_exists and src_hash == dest_hash:
            report["files_skipped_identical"] += 1
            report["file_details"].append({
                "path": str(rel_path),
                "action": "SKIPPED_IDENTICAL",
                "size_bytes": size,
                "sha256": src_hash,
            })
            continue

        action = "WOULD_COPY" if dry_run else "COPIED"
        if not dry_run:
            dest_file.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src_file, dest_file)
            verify_hash = compute_sha256(dest_file)
            if verify_hash != src_hash:
                err = f"Hash mismatch after copying {rel_path}: {src_hash} != {verify_hash}"
                logger.error(err)
                report["errors"].append(err)
                raise IOError(err)

        report["files_copied"] += 1
        report["bytes_migrated"] += size
        report["file_details"].append({
            "path": str(rel_path),
            "action": action,
            "size_bytes": size,
            "sha256": src_hash,
        })

    # 4. Target SQLite Post-Check
    if not dry_run:
        for db_path in target_dir.rglob("*.db"):
            ok, status = check_sqlite_integrity(db_path)
            report["sqlite_checks"][f"target:{db_path.name}"] = {"ok": ok, "status": status}
            if not ok:
                err = f"Target database verification failed: {db_path} ({status})"
                logger.error(err)
                report["errors"].append(err)

    logger.info("Migration finished: %d copied, %d identical, %d errors",
                report["files_copied"], report["files_skipped_identical"], len(report["errors"]))
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="Migrate OpenBagus operational data to unified shared root.")
    parser.add_argument("--source", type=Path, default=get_default_source(), help="Source data directory")
    parser.add_argument("--target", type=Path, default=get_default_target(), help="Target operational directory")
    parser.add_argument("--dry-run", action="store_true", help="Report actions without copying files")
    parser.add_argument("--rollback", type=Path, help="Rollback target directory from specified backup path")
    parser.add_argument("--verify-only", action="store_true", help="Only verify integrity of target directory")
    parser.add_argument("--report", type=Path, help="Write JSON migration report to specified file")

    args = parser.parse_args()

    if args.rollback:
        success = rollback(args.rollback, args.target)
        sys.exit(0 if success else 1)

    if args.verify_only:
        logger.info("Verifying target directory: %s", args.target)
        if not args.target.exists():
            logger.error("Target directory does not exist: %s", args.target)
            sys.exit(1)
        all_ok = True
        for db in args.target.rglob("*.db"):
            ok, status = check_sqlite_integrity(db)
            logger.info("DB %s: %s", db.name, "OK" if ok else f"FAILED ({status})")
            if not ok:
                all_ok = False
        sys.exit(0 if all_ok else 1)

    try:
        report = run_migration(args.source, args.target, dry_run=args.dry_run)
        if args.report:
            args.report.parent.mkdir(parents=True, exist_ok=True)
            args.report.write_text(json.dumps(report, indent=2), encoding="utf-8")
            logger.info("Saved report to %s", args.report)
        if report["errors"]:
            sys.exit(1)
    except Exception as e:
        logger.exception("Migration failed: %s", e)
        sys.exit(1)


if __name__ == "__main__":
    main()
