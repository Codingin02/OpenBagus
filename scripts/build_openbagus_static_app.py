"""Build OpenBagus Static PWA Dashboard.

Compiles and outputs the interactive PWA client to reports/runtime/app.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from openbagus.reporting.dashboard import PwaDashboardRenderer


def build_static_app() -> dict[str, str]:
    renderer = PwaDashboardRenderer(REPO_ROOT)
    result = renderer.write()
    print(json.dumps(result, indent=2))
    return result


if __name__ == "__main__":
    build_static_app()
