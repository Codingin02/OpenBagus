# OpenBagus V4.3 Runtime Data Migration & Operational Root

**Document Version:** 4.3.0  
**Date:** 2026-10-15  
**Author:** Antigravity (Data Engineering Agent)  
**Status:** VERIFIED & OPERATIONAL  

---

## 1. Executive Problem Statement

In the previous multi-worktree layout of OpenBagus:
- Main worktree: `E:\Projects\OpenBagus`
- Data worktree: `E:\Projects\OpenBagus-Data`
- Voice worktree: `E:\Projects\OpenBagus-Voice`

Each worktree maintained its own isolated `data/` directory. Because operational market data, downloaded official issuer filings (PDF/XLSX), and canonical SQLite facts (`financial_facts.db`) are excluded from Git version control via `.gitignore`, running the application from `OpenBagus` (main) or `OpenBagus-Voice` resulted in complete data invisibility or "DATA_GAP" errors, despite data being ingested in `OpenBagus-Data`.

V4.3 solves this root-cause architectural divergence by implementing a **Unified Cross-Worktree Operational Data Root** accessible seamlessly across all worktrees.

---

## 2. Operational Data Root Architecture

### Resolution Precedence
The resolver function `get_operational_data_root()` in `openbagus/core/env.py` evaluates paths according to the following strict priority:

1. **Explicit Environment Variable**:
   `OPENBAGUS_DATA_ROOT` (e.g. `C:\CustomData\OpenBagus\data`).
2. **Central Shared Operational Path**:
   - Windows: `%LOCALAPPDATA%\OpenBagus\data` (`C:\Users\<user>\AppData\Local\OpenBagus\data`)
   - POSIX / Linux: `~/.local/share/openbagus/data`
3. **Repository Fallback**:
   If the central directory has not been populated yet, falls back to `repo_root / "data"`.

### Integrated Subsystems
All data-handling components resolve through the unified operational data root:
- `FinancialStatementStorage` (`openbagus/domains/equities/storage.py`)
- `FinancialFactsDatabase` (`openbagus/domains/equities/facts_db.py`)
- `EquityData` (`openbagus/domains/equities/data.py`)
- Financial Tools (`openbagus/ai/tools/finance_tools.py`)
- Conversational Harness (`openbagus/ai/harness/orchestrator.py`)

---

## 3. Migration Utility: `scripts/migrate_operational_data.py`

The migration utility provides safe, verified, atomic synchronization between worktree caches and the central operational root.

### Core Safeguards
1. **Pre-Migration Backup**:
   If target data already exists, automatically creates a timestamped snapshot in:
   `%LOCALAPPDATA%\OpenBagus\backups\backup_YYYYMMDD_HHMMSS`
2. **Pre- and Post-Migration SQLite Integrity Check**:
   Executes `PRAGMA integrity_check;` on all database files before copying and after arrival at the target. Any integrity corruption immediately aborts the run.
3. **Cryptographic SHA-256 Bitrot Verification**:
   Calculates SHA-256 hash for every file before copy and re-verifies after writing to target disk.
4. **Deduplication**:
   Files with identical byte size and SHA-256 are skipped to eliminate unnecessary SSD writes.
5. **Dry-Run Mode**:
   `python scripts/migrate_operational_data.py --dry-run` simulates the entire migration and prints audit telemetry without disk mutation.
6. **One-Command Rollback**:
   `python scripts/migrate_operational_data.py --rollback <backup_directory>` restores previous target data immediately.

---

## 4. Migration Execution & Audit Results

### Migration Run
- **Command:** `python scripts/migrate_operational_data.py --report docs/integration/migration_audit.json`
- **Source:** `E:\Projects\OpenBagus-Data\data`
- **Target:** `C:\Users\bagus\AppData\Local\OpenBagus\data`
- **Files Scanned:** 178
- **Files Migrated:** 178
- **Corruptions / Errors:** 0
- **Target SQLite PRAGMA integrity_check:** `OK`

### Target Directory Content
```
C:\Users\bagus\AppData\Local\OpenBagus\data\
├── equities\
│   ├── downloads\
│   │   ├── TLKM\ (Authentic 2025-FY and 2026-Q1 PDFs)
│   │   ├── BBCA\ (Authentic 2025-FY and 2026-Q1 PDFs)
│   │   └── RATU\ (Authentic 2025-FY and 2026-Q1 PDFs)
│   ├── financials\
│   │   ├── TLKM\ (2025-FY.json, 2026-Q1.json)
│   │   ├── BBCA\ (2025-FY.json, 2026-Q1.json)
│   │   └── RATU\ (2025-FY.json, 2026-Q1.json)
│   ├── financial_facts.db (SQLite WAL canonical facts repository)
│   └── idx_universe.json (968 verified instruments)
└── quarantine\
    └── financials\ (Preserved synthetic files from V4.0)
```

---

## 5. Rollback & Troubleshooting Protocol

In the event of database contention or rollbacks:
```bash
# Verify integrity of target directory
python scripts/migrate_operational_data.py --verify-only

# Rollback target directory from a specific backup
python scripts/migrate_operational_data.py --rollback "C:\Users\bagus\AppData\Local\OpenBagus\backups\backup_20261015_114400"
```
