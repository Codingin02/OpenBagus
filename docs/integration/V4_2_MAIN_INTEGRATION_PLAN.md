# OPENBAGUS — MASTER INTEGRATION PLAN V4.2
## Strategy for Porting Verified Financial Intelligence into Main Repository

**Status:** DRAFT / PROPOSED (Strictly No Direct Main Modification in V4.2)  
**Author:** Antigravity  
**Worktree:** `E:\Projects\OpenBagus-Data`  
**Target Main Worktree:** `E:\Projects\OpenBagus`  
**Target Branch:** `main`

---

## 1. Executive Context & Boundary Guarantee

To ensure absolute stability, zero regression, and strict compliance with the project's zero-risk mandate:
1. **Zero Modifications to Main Worktree (`E:\Projects\OpenBagus`):** All development, testing, and verification in V4.2 remain isolated to `E:\Projects\OpenBagus-Data`.
2. **Zero Modifications to Voice Worktree (`E:\Projects\OpenBagus-Voice`):** Voice models, audio DSP, TTS pipelines, and Faster-Whisper remain completely untouched.
3. **Zero Modifications to 3D Art Worktree (`E:\Projects\OpenBagus-3D`):** All 3D Blender models, shaders, textures, and renderer scripts owned by Codex are completely untouched.

---

## 2. Commit Ancestry & Porting Manifest

The changes to be merged from `E:\Projects\OpenBagus-Data` into `main` comprise three sequential, tested commits:

| Commit Hash | Message | Scope & Description |
|---|---|---|
| `b75bc54` | `feat(data): Automated Live Data Intelligence...` | Introduces core multi-provider data layer, ZeroKey, SEC EDGAR client, and tools. |
| `acaf025` | `feat(data): V4.1 Critical Recovery, Financial Data Quarantine...` | Quarantines synthetic financial statements into `data/quarantine/`, fixes root pathing. |
| `[PENDING_V4_2]` | `feat(data): V4.2 Authentic IDX Ingestion, Indonesian Numbering & Provable Accounting Invariants` | Authentic PDF parsing for Indonesian conventions, TLKM/BBCA ingestion, Sharia funds invariant, facts DB sync. |

---

## 3. Conflict Analysis & File Overlaps

### A. Exclusively Data-Domain Files (Zero Conflict Risk):
- `openbagus/domains/equities/financial_model.py`
- `openbagus/domains/equities/parsers/pdf_parser.py`
- `openbagus/domains/equities/parsers/xlsx_parser.py`
- `openbagus/domains/equities/storage.py`
- `openbagus/domains/equities/facts_db.py`
- `openbagus/domains/equities/sec_edgar.py`
- `openbagus/data/` (all submodules)
- `tests/test_data_intelligence_live.py`
- `docs/data/` (all reports and evidence)

### B. Shared Files Requiring Verification:
1. `openbagus/domains/equities/data.py`:
   - Contains `EquityData.import_financial_statement` and database sync logic.
   - Clean addition that does not touch voice or audio logic.
2. `openbagus/ai/tools/finance_tools.py`:
   - Contains tool definitions (`CalculateFinancialRatiosTool`, `GetFinancialProvenanceTool`, etc.).
   - Tool interface signatures match `BaseFinancialTool`.
3. `openbagus/ai/providers/llama_server.py`:
   - Timeout increased from 60.0s to 120.0s. Compatible with all workloads.

---

## 4. Step-by-Step Integration Execution Protocol

When the user explicitly authorizes integration into `main`:

### Step 1: Pre-Integration Sanity Check on Main
```powershell
cd E:\Projects\OpenBagus
git status # Ensure clean working tree
git checkout main
```

### Step 2: Create Integration Feature Branch
```powershell
git checkout -b feat/integrate-data-intelligence-v4-2
```

### Step 3: Cherry-Pick or Fast-Forward Merge
```powershell
# Fetch commits from local Data worktree
git fetch E:\Projects\OpenBagus-Data feat/openbagus-automated-data-intelligence
# Merge changes
git merge --ff-only FETCH_HEAD
```

### Step 4: Run Post-Integration Test Verification Suite
```powershell
# 1. Run live data intelligence suite
E:\Projects\OpenBagus\.venv\Scripts\python.exe -m unittest tests/test_data_intelligence_live.py

# 2. Run voice recovery test suite (to confirm zero regression on voice)
E:\Projects\OpenBagus\.venv\Scripts\python.exe -m unittest tests/test_voice_recovery.py
```

### Step 5: Final Review & Merge to Main
Only after both suites return `OK`:
```powershell
git checkout main
git merge feat/integrate-data-intelligence-v4-2
```
