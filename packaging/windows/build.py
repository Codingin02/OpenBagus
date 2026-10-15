"""Build the local Windows package and checksum its release artifacts."""

import argparse
import hashlib
import importlib.metadata
import json
from pathlib import Path
import subprocess
import sys
from datetime import datetime, timezone


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--inno", type=Path, required=True)
    parser.add_argument("--release", type=Path, default=Path("E:/Projects/OpenBagus/release"))
    arguments = parser.parse_args()
    root = Path(__file__).resolve().parents[2]
    release = arguments.release.resolve()
    release.mkdir(parents=True, exist_ok=True)
    log_path = root / "reports/runtime/release/build.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("w", encoding="utf-8") as log:
        print(f"Building frozen executable. Log: {log_path}", flush=True)
        subprocess.run([sys.executable, "-m", "PyInstaller", "--noconfirm", "--distpath", str(root / "dist"),
                        "--workpath", str(root / "build"), str(root / "packaging/windows/OpenBagus.spec")], cwd=root, check=True, stdout=log, stderr=subprocess.STDOUT)
        print("Compiling Windows setup...", flush=True)
        subprocess.run([str(arguments.inno.resolve()), "/DSourceDir=" + str(root / "dist/OpenBagus"),
                        "/DReleaseDir=" + str(release), str(root / "packaging/windows/OpenBagus.iss")], check=True, cwd=root, stdout=log, stderr=subprocess.STDOUT)
    installer = release / "OpenBagus-Setup.exe"
    with installer.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    (release / "SHA256SUMS.txt").write_text(f"{digest}  {installer.name}\n", encoding="ascii")
    manifest = {"created_at_utc": datetime.now(timezone.utc).isoformat(),
                "source_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip(),
                "source_dirty": bool(subprocess.check_output(["git", "status", "--porcelain"], cwd=root, text=True).strip()),
                "installer": installer.name, "size_bytes": installer.stat().st_size, "sha256": digest,
                "models_bundled": False, "canonical_models": "E:/Projects/OpenBagus/models",
                "signed": False, "acceptance": "REVIEW_REQUIRED",
                "packaging": {name: importlib.metadata.version(name) for name in ("pyinstaller", "pyinstaller-hooks-contrib")}}
    (release / "release_manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
