"""Optional TradingView MCP Bridge for OpenBagus.

Provides a secure, sandboxed MCP client for local TradingView chart rendering
and indicator verification via stdio subprocess.
Requires explicit user setup; zero impact on core CLI if not configured.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from openbagus.intelligence.local_language import get_local_appdata_dir

ALLOWED_TOOLS = {
    "render_chart",
    "capture_chart_png",
    "get_technical_indicators",
}


@dataclass
class MCPStatus:
    available: bool
    runtime: str  # "node" | "python" | "unavailable"
    server_path: str | None
    configured: bool
    message: str


class TradingViewMCPClient:
    """Manages an optional local-first TradingView MCP subprocess via JSON-RPC stdio."""

    def __init__(self, server_path: Path | None = None, root: Path | None = None) -> None:
        self.root = root
        self.app_dir = get_local_appdata_dir() / "integrations" / "tradingview_mcp"
        self.app_dir.mkdir(parents=True, exist_ok=True)
        self.server_path = server_path or self._detect_server_path()

    def status(self) -> MCPStatus:
        """Alias for get_status."""
        return self.get_status()

    def _detect_server_path(self) -> Path | None:
        # Check local app data installation
        candidate_js = self.app_dir / "index.js"
        if candidate_js.exists():
            return candidate_js
        candidate_ts = self.app_dir / "dist" / "index.js"
        if candidate_ts.exists():
            return candidate_ts
        return None

    def get_status(self) -> MCPStatus:
        """Inspects runtime and server availability without side effects."""
        node_bin = shutil.which("node")
        runtime = f"Node.js ({node_bin})" if node_bin else "unavailable"

        if not node_bin:
            return MCPStatus(
                available=False,
                runtime=runtime,
                server_path=None,
                configured=False,
                message="Node.js tidak terdeteksi di PATH sistem. Integrasi MCP TradingView bersifat opsional dan tidak aktif.",
            )

        if not self.server_path or not self.server_path.exists():
            return MCPStatus(
                available=False,
                runtime=runtime,
                server_path=None,
                configured=False,
                message="Server TradingView MCP belum terpasang di direktori lokal. Gunakan '/integrations tradingview setup' untuk panduan.",
            )

        return MCPStatus(
            available=True,
            runtime=runtime,
            server_path=str(self.server_path),
            configured=True,
            message="TradingView MCP aktif dan siap menerima perintah visualisasi lokal.",
        )

    def execute_tool(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        timeout_seconds: float = 8.0,
    ) -> dict[str, Any]:
        """Executes an allowlisted MCP tool via stdio with strict timeout and sanitization."""
        if tool_name not in ALLOWED_TOOLS:
            return {
                "success": False,
                "error": f"Tool '{tool_name}' tidak diizinkan dalam kebijakan keamanan OpenBagus MCP.",
            }

        status = self.get_status()
        if not status.available or not self.server_path:
            return {
                "success": False,
                "error": f"TradingView MCP tidak tersedia: {status.message}",
            }

        # Safe subprocess execution over stdio
        node_bin = shutil.which("node") or "node"
        rpc_request = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {
                "name": tool_name,
                "arguments": arguments,
            },
        }

        # Block environment leakage
        safe_env = {
            "PATH": os.environ.get("PATH", ""),
            "SYSTEMROOT": os.environ.get("SYSTEMROOT", ""),
            "TEMP": os.environ.get("TEMP", ""),
        }

        try:
            proc = subprocess.Popen(
                [node_bin, str(self.server_path)],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                env=safe_env,
            )
            stdout, stderr = proc.communicate(input=json.dumps(rpc_request) + "\n", timeout=timeout_seconds)
            if proc.returncode != 0:
                return {"success": False, "error": f"MCP process error ({proc.returncode}): {stderr.strip()[:200]}"}

            resp = json.loads(stdout.strip())
            return {"success": True, "result": resp.get("result", {})}

        except subprocess.TimeoutExpired:
            proc.kill()
            return {"success": False, "error": f"MCP execution timed out after {timeout_seconds}s."}
        except Exception as ex:
            return {"success": False, "error": f"Gagal mengeksekusi MCP: {ex}"}


def format_integrations_view(client_or_status: Any = None) -> str:
    """Renders user-facing integrations status table."""
    if isinstance(client_or_status, MCPStatus):
        st = client_or_status
    elif isinstance(client_or_status, TradingViewMCPClient):
        st = client_or_status.get_status()
    elif client_or_status is None:
        c = TradingViewMCPClient()
        st = c.get_status()
    else:
        fn = getattr(client_or_status, "status", getattr(client_or_status, "get_status", None))
        if callable(fn):
            res = fn()
            st = res if isinstance(res, MCPStatus) else TradingViewMCPClient().get_status()
        else:
            st = TradingViewMCPClient().get_status()

    lines = [
        "=== OpenBagus Open-Source Integrations ===",
        "",
        "1. Matplotlib & mplfinance (Grafik Publikasi & Dokumen):",
        "   - Status: AKTIF (Headless Agg backend)",
        "   - Fitur: Ekspor PNG, grafik candlestick, pie chart kepemilikan, equity curve",
        "",
        "2. TradingView Lightweight Charts (Window Desktop Interaktif):",
        "   - Status: AKTIF (WebView2 native window)",
        "   - Fitur: Pan/zoom, crosshair, volume, candlestick, S/R overlays",
        "",
        "3. TradingView MCP Adapter (Opsional Local Server):",
        f"   - Status: {'TERPASANG' if st.available else 'TIDAK TERPASANG (OPSIONAL)'}",
        f"   - Runtime: {st.runtime}",
        f"   - Lokasi: {st.server_path or 'Belum dikonfigurasi'}",
        f"   - Keterangan: {st.message}",
        "",
        "Perintah yang tersedia:",
        "  /integrations tradingview status  - Periksa status koneksi MCP",
        "  /integrations tradingview setup   - Panduan konfigurasi server lokal",
        "  /integrations tradingview test    - Uji coba komunikasi stdio",
    ]
    return "\n".join(lines)
