"""OpenBagus Local Data Management, Privacy Controls, and Reset Infrastructure.

Provides secure, bounded data management commands (Section E):
- /privacy status & /privacy clear
- /cache clear & /cache refresh
- /harness clear
- /reset all (strict safety boundaries, confirmed deletion)
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import Any

from openbagus.core.env import get_repo_root
from openbagus.data.cache import MarketDataCache
from openbagus.intelligence.local_language import get_local_appdata_dir

FULL_RESET_CONFIRMATION_PHRASE = "DELETE OPENBAGUS LOCAL DATA"


def _safe_dir_size(path: Path) -> tuple[int, int]:
    """Return (total_bytes, file_count) for a directory safely without following external symlinks."""
    if not path.exists():
        return 0, 0
    total_bytes = 0
    file_count = 0
    try:
        if path.is_file():
            return path.stat().st_size, 1
        for root, dirs, files in os.walk(path):
            for f in files:
                fp = Path(root) / f
                try:
                    if not fp.is_symlink():
                        total_bytes += fp.stat().st_size
                        file_count += 1
                except OSError:
                    pass
    except OSError:
        pass
    return total_bytes, file_count


def _fmt_size(bytes_val: int) -> str:
    if bytes_val >= 1024 * 1024 * 1024:
        return f"{bytes_val / (1024 * 1024 * 1024):.2f} GB"
    if bytes_val >= 1024 * 1024:
        return f"{bytes_val / (1024 * 1024):.1f} MB"
    if bytes_val >= 1024:
        return f"{bytes_val / 1024:.1f} KB"
    return f"{bytes_val} B"


def get_privacy_status(repo_root: Path | None = None) -> dict[str, Any]:
    """Inspect all locally stored OpenBagus data categories (Section E3)."""
    appdata = get_local_appdata_dir()
    root = repo_root or get_repo_root()

    categories: dict[str, dict[str, Any]] = {}

    # 1. Harness Context
    harness_path = appdata / "harness"
    h_bytes, h_files = _safe_dir_size(harness_path)
    categories["harness"] = {
        "name": "Persistent Harness Context",
        "path": str(harness_path),
        "exists": harness_path.exists(),
        "bytes": h_bytes,
        "files": h_files,
        "description": "Multi-turn conversational context, active asset & market snapshot.",
    }

    # 2. Market Data Cache
    cache_path = appdata / "cache"
    c_bytes, c_files = _safe_dir_size(cache_path)
    categories["cache"] = {
        "name": "Market Data Cache",
        "path": str(cache_path),
        "exists": cache_path.exists(),
        "bytes": c_bytes,
        "files": c_files,
        "description": "Public Zero-Key market quotes, OHLCV candles, and order books.",
    }

    # 3. Research Reports
    reports_path = appdata / "reports"
    r_bytes, r_files = _safe_dir_size(reports_path)
    runtime_reports = root / "reports/runtime"
    rr_bytes, rr_files = _safe_dir_size(runtime_reports)
    categories["reports"] = {
        "name": "Generated Reports & Output",
        "path": str(reports_path),
        "exists": reports_path.exists() or runtime_reports.exists(),
        "bytes": r_bytes + rr_bytes,
        "files": r_files + rr_files,
        "description": "Interactive HTML charts, Word .docx summaries, and CSV run logs.",
    }

    # 4. Feedback Telemetry
    fb_path = appdata / "feedback"
    fb_bytes, fb_files = _safe_dir_size(fb_path)
    categories["feedback"] = {
        "name": "Opt-in Feedback & Corrections",
        "path": str(fb_path),
        "exists": fb_path.exists(),
        "bytes": fb_bytes,
        "files": fb_files,
        "description": "Explicit local user corrections and preference feedback.",
    }

    # 5. Cloud Authentication
    cloud_path = appdata / "cloud"
    cl_bytes, cl_files = _safe_dir_size(cloud_path)
    categories["cloud"] = {
        "name": "Cloud AI Auth Token (Puter)",
        "path": str(cloud_path),
        "exists": cloud_path.exists(),
        "bytes": cl_bytes,
        "files": cl_files,
        "description": "DPAPI-encrypted browser session token for optional Puter bridge.",
    }

    # 6. Local AI Model & Binaries
    models_path = appdata / "models"
    m_bytes, m_files = _safe_dir_size(models_path)
    bin_path = appdata / "bin"
    b_bytes, b_files = _safe_dir_size(bin_path)
    categories["models"] = {
        "name": "Local AI Models & Binaries",
        "path": str(models_path),
        "exists": models_path.exists() or bin_path.exists(),
        "bytes": m_bytes + b_bytes,
        "files": m_files + b_files,
        "description": "Qwen3-4B-Q4_K_M GGUF model and managed loopback llama-server executable.",
    }

    # 7. Local Configuration
    env_file = root / ".env"
    flags_file = root / "config/openbagus_local_flags.json"
    cfg_bytes = (env_file.stat().st_size if env_file.exists() else 0) + (flags_file.stat().st_size if flags_file.exists() else 0)
    categories["config"] = {
        "name": "Local Environment & Flags",
        "path": str(env_file),
        "exists": env_file.exists() or flags_file.exists(),
        "bytes": cfg_bytes,
        "files": (1 if env_file.exists() else 0) + (1 if flags_file.exists() else 0),
        "description": "Optional provider API keys, email SMTP settings, and local flags.",
    }

    return categories


def format_privacy_status(repo_root: Path | None = None) -> str:
    """Format stored data categories for terminal display (Section E3)."""
    categories = get_privacy_status(repo_root)
    lines = [
        "OpenBagus Local Data Storage & Privacy Status",
        "=============================================",
        "All data remains strictly on your local machine and is never auto-uploaded.",
        "",
    ]
    total_bytes = 0
    for key, info in categories.items():
        total_bytes += info["bytes"]
        status = f"Stored ({_fmt_size(info['bytes'])}, {info['files']} files)" if info["exists"] and info["files"] > 0 else "Empty / Not Stored"
        lines.append(f"{info['name']:<32} {status}")
        lines.append(f"  Path: {info['path']}")
        lines.append(f"  Info: {info['description']}")
        lines.append("")

    lines.append(f"Total Local Footprint: {_fmt_size(total_bytes)}")
    lines.append("")
    lines.append("Management Commands:")
    lines.append("  /harness clear   Delete saved conversational turns and context")
    lines.append("  /cache clear     Delete market data caches (preserves settings)")
    lines.append("  /privacy clear   Delete personal context, preferences, and feedback")
    lines.append("  /reset all       Complete local reset (requires typed confirmation)")
    return "\n".join(lines)


# --- Windows DPAPI Sensitive Credential Protection (Section E) ---

def encrypt_secret_dpapi(secret: str) -> str:
    """Encrypt sensitive string using Windows DPAPI, returning base64. On non-Windows, returns base64 raw."""
    import base64
    import sys
    if sys.platform == "win32":
        try:
            import ctypes
            import ctypes.wintypes

            class DATA_BLOB(ctypes.Structure):
                _fields_ = [("cbData", ctypes.wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_byte))]

            raw = secret.encode("utf-8")
            b_in = (ctypes.c_byte * len(raw))(*raw)
            blob_in = DATA_BLOB(len(raw), b_in)
            blob_out = DATA_BLOB()
            if ctypes.windll.crypt32.CryptProtectData(ctypes.byref(blob_in), None, None, None, None, 0, ctypes.byref(blob_out)):
                out = bytes(ctypes.string_at(blob_out.pbData, blob_out.cbData))
                ctypes.windll.kernel32.LocalFree(blob_out.pbData)
                return "dpapi:" + base64.b64encode(out).decode("ascii")
        except Exception:
            pass
    return "raw:" + base64.b64encode(secret.encode("utf-8")).decode("ascii")


def decrypt_secret_dpapi(stored: str) -> str:
    """Decrypt a secret string stored via encrypt_secret_dpapi."""
    import base64
    import sys
    if stored.startswith("dpapi:") and sys.platform == "win32":
        try:
            import ctypes
            import ctypes.wintypes

            class DATA_BLOB(ctypes.Structure):
                _fields_ = [("cbData", ctypes.wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_byte))]

            raw = base64.b64decode(stored[6:])
            b_in = (ctypes.c_byte * len(raw))(*raw)
            blob_in = DATA_BLOB(len(raw), b_in)
            blob_out = DATA_BLOB()
            if ctypes.windll.crypt32.CryptUnprotectData(ctypes.byref(blob_in), None, None, None, None, 0, ctypes.byref(blob_out)):
                out = bytes(ctypes.string_at(blob_out.pbData, blob_out.cbData))
                ctypes.windll.kernel32.LocalFree(blob_out.pbData)
                return out.decode("utf-8")
        except Exception:
            return ""
    elif stored.startswith("raw:"):
        return base64.b64decode(stored[4:]).decode("utf-8")
    return stored


class RemoveResult:
    """Represents deletion outcome with precise status semantics (Section E)."""

    def __init__(self, status: str, detail: str = "") -> None:
        self.status = status
        self.detail = detail

    def __bool__(self) -> bool:
        return self.status in ("DELETED", "EMPTY")

    def __str__(self) -> str:
        return self.status

    def __repr__(self) -> str:
        return f"RemoveResult('{self.status}', '{self.detail}')"

    def __eq__(self, other: Any) -> bool:
        if isinstance(other, bool):
            return bool(self) == other
        return self.status == str(other)


def _safe_remove(path: Path, appdata: Path, repo_root: Path) -> RemoveResult:
    """Safely delete a file or directory ensuring it strictly resides in OpenBagus-managed paths (Section E5).

    Verifies actual removal and returns precise status: DELETED, EMPTY, FAILED_LOCKED, FAILED_PERMISSION, BOUNDARY_VIOLATION.
    """
    try:
        resolved = path.resolve()
        appdata_res = appdata.resolve()
        repo_res = repo_root.resolve()
        runtime_res = (repo_root / "reports/runtime").resolve()

        # Strict boundary check: MUST be inside appdata OR repo_root/reports/runtime OR repo_root/.env
        is_in_appdata = resolved.is_relative_to(appdata_res)
        is_runtime_report = resolved.is_relative_to(runtime_res)
        is_local_env = resolved == (repo_res / ".env") or resolved == (repo_res / "config/openbagus_local_flags.json")

        if not (is_in_appdata or is_runtime_report or is_local_env):
            return RemoveResult("BOUNDARY_VIOLATION", f"Path {path} is outside allowed OpenBagus roots.")

        # Never touch git directories or repository root
        if ".git" in str(resolved).lower() or resolved == repo_res:
            return RemoveResult("BOUNDARY_VIOLATION", "Cannot delete Git repository root or metadata.")

        if not resolved.exists() and not resolved.is_symlink():
            return RemoveResult("EMPTY", "Path does not exist on disk.")

        if resolved.is_file() or resolved.is_symlink():
            try:
                resolved.unlink()
            except PermissionError as exc:
                return RemoveResult("FAILED_LOCKED", str(exc))
            except OSError as exc:
                return RemoveResult("FAILED_PERMISSION", str(exc))
        elif resolved.is_dir():
            err_holder: list[Exception] = []

            def on_error(fn: Any, p: str, exc: Any) -> None:
                if isinstance(exc, tuple) and exc[1]:
                    err_holder.append(exc[1])
                elif isinstance(exc, Exception):
                    err_holder.append(exc)

            try:
                shutil.rmtree(resolved, onexc=lambda fn, p, exc: err_holder.append(exc))
            except TypeError:
                shutil.rmtree(resolved, onerror=on_error)

            if err_holder:
                first_err = err_holder[0]
                if isinstance(first_err, PermissionError):
                    return RemoveResult("FAILED_LOCKED", str(first_err))
                return RemoveResult("FAILED_PERMISSION", str(first_err))

        # Real verification check: verify target is actually gone from filesystem
        if resolved.exists():
            return RemoveResult("FAILED_LOCKED", f"File remained present after deletion: {resolved}")

        return RemoveResult("DELETED", f"Successfully removed {resolved}")
    except PermissionError as exc:
        return RemoveResult("FAILED_LOCKED", str(exc))
    except Exception as exc:
        return RemoveResult("FAILED_PERMISSION", str(exc))


def clear_privacy_data(repo_root: Path | None = None) -> dict[str, str]:
    """Delete conversational context, feedback, and cloud credentials (Section E3)."""
    appdata = get_local_appdata_dir()
    root = repo_root or get_repo_root()
    results: dict[str, str] = {}

    # 1. Clear Persistent Harness
    harness_path = appdata / "harness"
    if harness_path.exists():
        res = _safe_remove(harness_path, appdata, root)
        results["Harness Context"] = "CLEARED" if res else res.status
    else:
        results["Harness Context"] = "EMPTY"

    # 2. Clear Feedback
    fb_path = appdata / "feedback"
    if fb_path.exists():
        res = _safe_remove(fb_path, appdata, root)
        results["Feedback Store"] = "CLEARED" if res else res.status
    else:
        results["Feedback Store"] = "EMPTY"

    # 3. Clear Cloud Token
    cloud_path = appdata / "cloud"
    if cloud_path.exists():
        res = _safe_remove(cloud_path, appdata, root)
        results["Cloud Auth"] = "CLEARED" if res else res.status
    else:
        results["Cloud Auth"] = "EMPTY"

    return results


def execute_full_reset(repo_root: Path | None = None, delete_models: bool = False) -> dict[str, str]:
    """Execute complete local reset strictly within OpenBagus-managed paths (Section E4, E5)."""
    appdata = get_local_appdata_dir()
    root = repo_root or get_repo_root()
    results: dict[str, str] = {}

    # Close active cache DB connection first
    MarketDataCache.get_instance().close()
    MarketDataCache.reset_instance()

    targets = [
        ("harness", appdata / "harness", "Harness Context"),
        ("cache", appdata / "cache", "Market Cache"),
        ("feedback", appdata / "feedback", "Feedback Data"),
        ("cloud", appdata / "cloud", "Cloud Auth"),
        ("reports", appdata / "reports", "Reports (AppData)"),
        ("runtime_reports", root / "reports/runtime", "Reports (Runtime Sheets)"),
        ("flags", root / "config/openbagus_local_flags.json", "Local Flags"),
        ("env", root / ".env", "Environment Config (.env)"),
    ]

    if delete_models:
        targets.extend([
            ("models", appdata / "models", "AI Models (~2.5GB)"),
            ("bin", appdata / "bin", "llama-server Executable"),
        ])

    for key, path, label in targets:
        if path.exists():
            res = _safe_remove(path, appdata, root)
            results[label] = res.status
        else:
            results[label] = "NOT_PRESENT"

    return results
