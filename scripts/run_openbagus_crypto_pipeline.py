"""Dedicated runner for OpenBagus Crypto Pipeline."""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from openbagus.runtime.orchestrator import run_pipeline


def main() -> int:
    print("Executing OpenBagus Full Crypto Pipeline (Active Domain: Crypto, NO_SEND mode)...")
    res = run_pipeline(mode="crypto-daily", all_core=True, dry_run=True, repo_root=REPO_ROOT)
    print(json.dumps(res, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
