"""OpenBagus Local Language Engine.

Provides offline, private, zero-API-key local language intelligence using
Qwen3-4B-Q4_K_M.gguf through one managed loopback-only llama.cpp server.

Roles:
1. Intent Interpreter: Free-form conversational intent classification with strict JSON output.
2. Natural Narrative: Professional consultant-style crypto trader note narrative.
3. System Profile: Canonical factual responses about OpenBagus architecture and origins.

QuantEngine remains 100% authoritative for all calculations, decisions, and prices.
"""

from __future__ import annotations

import atexit
import hashlib
import io
import json
import os
import re
import shutil
import socket
import ssl
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from openbagus.core.env import get_repo_root


@dataclass
class NarrativeFacts:
    asset: str
    price: float
    decision: str
    timeframe: str = "H1"
    regime: str = "Compressed"
    reason: str = ""
    reward_risk_str: str = "N/A"
    bullish_trigger: str = ""
    bearish_trigger: str = ""
    fibonacci_level: float | None = None
    fibonacci_confluence: str = ""
    price_vs_fib: str = ""  # "ABOVE", "BELOW", or ""
    pattern_name: str = ""
    stochastic_summary: str = ""
    arbitrage_summary: str = ""
    macro_event: str = ""
    large_flow_summary: str = ""
    event_dates: list[str] = field(default_factory=list)
    market: str = "GENERAL / SPOT REFERENCE"
    rr_long: float | None = None
    rr_short: float | None = None
    rr_gate_passed: bool = False
    frequency: str = ""
    bullish_trigger_level: float | None = None
    bullish_trigger_state: str = "UNKNOWN"
    bearish_trigger_level: float | None = None
    bearish_trigger_state: str = "UNKNOWN"
    data_freshness: str = "UNVERIFIED"
    contradictions: list[str] = field(default_factory=list)
    evidence_families: dict[str, str] = field(default_factory=dict)
    entry_zone: str = ""
    stop_price: float | None = None
    target_price: float | None = None
    data_quality: str = "UNKNOWN"


def format_price(value: float) -> str:
    """Format USD values without discarding small-price precision."""
    from decimal import Decimal
    if abs(value) >= 1:
        return f"${value:,.2f}"
    return "$" + format(Decimal(str(value)), "f")


def get_local_appdata_dir() -> Path:
    """Returns local app data directory for OpenBagus runtime files (%LOCALAPPDATA%\\OpenBagus)."""
    base = os.environ.get("LOCALAPPDATA")
    if base:
        p = Path(base) / "OpenBagus"
    else:
        p = Path.home() / ".openbagus"
    return p


LOCAL_RUNTIME_DIR = get_local_appdata_dir()
MODELS_DIR = LOCAL_RUNTIME_DIR / "models"
BIN_DIR = LOCAL_RUNTIME_DIR / "bin"
CACHE_DIR = LOCAL_RUNTIME_DIR / "cache"
MODEL_NAME = "Qwen3-4B-Q4_K_M.gguf"
MODEL_FILE = MODELS_DIR / MODEL_NAME
OLD_MODEL_FILE = MODELS_DIR / "Qwen3-0.6B-Q8_0.gguf"
LLAMA_SERVER_EXE = BIN_DIR / ("llama-server.exe" if os.name == "nt" else "llama-server")

QWEN3_SHA256 = "7485fe6f11af29433bc51cab58009521f205840f5b4ae3a32fa7f92e8534fdf5"
MODEL_REPOSITORY = "Qwen/Qwen3-4B-GGUF"
MODEL_URL = f"https://huggingface.co/{MODEL_REPOSITORY}/resolve/main/{MODEL_NAME}"

# Canonical Factual OpenBagus System Profile (Section 12)
SYSTEM_PROFILE: dict[str, str] = {
    "name": "OpenBagus",
    "creator": "Ahmad Bagus Idkholus Surur",
    "purpose": "Crypto quantitative research and decision-support CLI",
    "core": "Local deterministic QuantEngine (Microstructure & Risk)",
    "data": "Online Zero-Key public providers (16 active) + optional keyed providers",
    "language_layer": "Local Qwen3-4B Q4_K_M via managed llama.cpp server",
    "active_domain": "Crypto (Equities disabled)",
    "trading_execution": "Not implemented (research and risk analysis only)",
    "secrets": "Stored locally only (zero telemetry, zero cloud model inference)",
    "environment": "Local native Python / Windows terminal",
}

ALLOWED_LLM_REQUEST_TYPES = {
    "ANALYZE",
    "POSITION",
    "COMPARE",
    "RISK",
    "SYSTEM_INFO",
    "HARNESS",
    "FEEDBACK",
    "PREFERENCE",
    "CATEGORY",
    "CHART",
    "MARKET_OUTLOOK",
    "SETUP_CONFIG",
    "UNKNOWN",
}

ALLOWED_RELATION_TYPES = {
    "CONTINUE",
    "SWITCH",
    "UNRELATED",
    "UNCERTAIN",
}


def _verify_sha256(filepath: Path, expected_sha: str) -> bool:
    """Computes SHA-256 of file and checks against expected hex string."""
    if not filepath.is_file():
        return False
    h = hashlib.sha256()
    try:
        with open(filepath, "rb") as f:
            while chunk := f.read(1024 * 1024):
                h.update(chunk)
        return h.hexdigest().lower() == expected_sha.lower()
    except Exception:
        return False


def _safe_subprocess_env() -> dict[str, str]:
    blocked = ("KEY", "TOKEN", "SECRET", "PASSWORD", "CREDENTIAL", "SMTP", "WHATSAPP")
    return {key: value for key, value in os.environ.items() if not any(part in key.upper() for part in blocked)}


class _ManagedLlamaServer:
    _lock = threading.RLock()
    _process: subprocess.Popen[str] | None = None
    _signature: tuple[str, str] | None = None
    _port: int | None = None
    _backend = "CPU"

    @classmethod
    def detect_backend(cls, server_bin: Path) -> str:
        if not server_bin.is_file():
            return "UNAVAILABLE"
        try:
            result = subprocess.run(
                [str(server_bin), "--list-devices"], capture_output=True, text=True,
                timeout=10, encoding="utf-8", errors="replace", env=_safe_subprocess_env(),
            )
            output = (result.stdout + result.stderr).upper()
            if "CUDA" in output or "NVIDIA" in output:
                return "CUDA"
            if "VULKAN" in output:
                return "VULKAN"
        except (OSError, subprocess.SubprocessError):
            pass
        return "CPU"

    @classmethod
    def ensure(cls, server_bin: Path, model_path: Path, timeout: float = 90.0) -> tuple[int, str] | None:
        signature = (str(server_bin.resolve()), str(model_path.resolve()))
        with cls._lock:
            if cls._process and cls._process.poll() is None and cls._signature == signature and cls._port:
                return cls._port, cls._backend
            cls.stop()
            backend = cls.detect_backend(server_bin)
            with socket.socket() as sock:
                sock.bind(("127.0.0.1", 0))
                port = int(sock.getsockname()[1])
            command = [
                str(server_bin), "-m", str(model_path), "-c", "4096", "--host", "127.0.0.1",
                "--port", str(port), "--no-webui", "--flash-attn", "auto",
                "--reasoning", "off",
            ]
            if backend in {"CUDA", "VULKAN"}:
                command.extend(["-ngl", "all", "--fit", "on"])
            else:
                command.extend(["-ngl", "0"])
            creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0
            try:
                cls._process = subprocess.Popen(
                    command, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL, text=True, env=_safe_subprocess_env(),
                    creationflags=creationflags,
                )
                cls._signature, cls._port, cls._backend = signature, port, backend
                deadline = time.monotonic() + timeout
                while time.monotonic() < deadline:
                    if cls._process.poll() is not None:
                        cls.stop()
                        return None
                    try:
                        with urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=1) as response:
                            if response.status == 200:
                                return port, backend
                    except (OSError, urllib.error.URLError):
                        time.sleep(0.2)
            except OSError:
                pass
            cls.stop()
            return None

    @classmethod
    def stop(cls) -> None:
        process = cls._process
        cls._process = None
        cls._signature = None
        cls._port = None
        if process and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)


atexit.register(_ManagedLlamaServer.stop)


class LocalLanguageEngine:
    """Manages one loopback-only llama.cpp server for routing and narrative."""

    def __init__(
        self,
        model_path: Path | None = None,
        llama_bin: Path | None = None,
        repo_root: Path | None = None,
    ) -> None:
        self.root = repo_root or get_repo_root()
        custom_model = os.environ.get("OPENBAGUS_MODEL_PATH")
        custom_llama = os.environ.get("OPENBAGUS_LLAMA_SERVER") or os.environ.get("OPENBAGUS_LLAMA_CLI")

        self.model_path = Path(custom_model) if custom_model else (model_path or MODEL_FILE)
        self.llama_bin = Path(custom_llama) if custom_llama else (llama_bin or LLAMA_SERVER_EXE)
        from openbagus.intelligence.puter import PuterBackend
        self.cloud = PuterBackend()
        self.selected_backend = "local"

    def is_available(self) -> bool:
        """Returns True only if both llama-server and the canonical model exist."""
        return self.cloud.enabled or self._local_available()

    def _local_available(self) -> bool:
        return self.llama_bin.is_file() and self.model_path.is_file()

    def _complete(self, prompt: str, **options: Any) -> str | None:
        cloud = self.cloud.complete(prompt, options.get("temp", 0.0), options.get("max_tokens", 128))
        if cloud:
            self.selected_backend = "puter"
            return cloud
        self.selected_backend = "local"
        return self._run_llama(prompt, **options)

    def get_runtime_state(self) -> str:
        """Returns runtime state: ACTIVE, FALLBACK, or UNAVAILABLE."""
        if not self.is_available():
            if not self.model_path.is_file() and not self.llama_bin.is_file():
                return "UNAVAILABLE"
            return "FALLBACK"

        smoke_file = CACHE_DIR / "llm_4b_smoke.ok"
        if smoke_file.is_file():
            try:
                if smoke_file.stat().st_mtime >= max(self.llama_bin.stat().st_mtime, self.model_path.stat().st_mtime):
                    return "ACTIVE"
            except Exception:
                pass

        if self._smoke_test():
            try:
                CACHE_DIR.mkdir(parents=True, exist_ok=True)
                smoke_file.write_text("OK", encoding="utf-8")
            except Exception:
                pass
            return "ACTIVE"
        return "FALLBACK"

    def get_status_info(self) -> dict[str, Any]:
        """Returns local language runtime status metadata."""
        state = self.get_runtime_state()
        return {
            "state": state,
            "available": (state == "ACTIVE"),
            "model_name": MODEL_NAME,
            "model_path": str(self.model_path),
            "model_exists": self.model_path.is_file(),
            "model_size_mb": round(self.model_path.stat().st_size / (1024 * 1024), 1) if self.model_path.is_file() else 0.0,
            "llama_bin": str(self.llama_bin),
            "llama_exists": self.llama_bin.is_file(),
            "backend": _ManagedLlamaServer.detect_backend(self.llama_bin),
        }

    def _smoke_test(self, timeout: float = 12.0) -> bool:
        """Runs one real inference smoke against the managed local server."""
        if not self.is_available():
            return False
        prompt = (
            "<|im_start|>system\nYou are the intent classifier. Output ONLY valid JSON.<|im_end|>\n"
            '<|im_start|>user\nReturn JSON only: {"request_type": "SYSTEM_INFO"}<|im_end|>\n'
            "<|im_start|>assistant\n"
        )
        out = self._run_llama(prompt, max_tokens=32, temp=0.0, timeout=timeout)
        if not out:
            return False
        match = re.search(r"\{.*\}", out, re.DOTALL)
        if not match:
            return False
        try:
            d = json.loads(match.group(0))
            return isinstance(d, dict) and d.get("request_type") == "SYSTEM_INFO"
        except Exception:
            return False

    def _run_llama(
        self,
        prompt: str,
        max_tokens: int = 128,
        temp: float = 0.0,
        top_p: float = 0.95,
        top_k: int = 40,
        presence_penalty: float = 0.0,
        timeout: float = 45.0,
    ) -> str | None:
        """Runs inference through one process-local loopback llama-server."""
        if not self._local_available():
            return None
        marker = "<|im_end|>\n<|im_start|>assistant\n"
        if marker in prompt and "/no_think" not in prompt:
            head, separator, tail = prompt.rpartition(marker)
            prompt = f"{head}\n/no_think{separator}{tail}"
        server = _ManagedLlamaServer.ensure(self.llama_bin, self.model_path)
        if not server:
            return None
        port, _backend = server
        payload = json.dumps({
            "prompt": prompt,
            "n_predict": max_tokens,
            "temperature": temp,
            "top_p": top_p,
            "top_k": top_k,
            "presence_penalty": presence_penalty,
            "cache_prompt": True,
            "stop": ["<|im_end|>", "<|im_start|>user"],
        }).encode("utf-8")
        try:
            request = urllib.request.Request(
                f"http://127.0.0.1:{port}/completion", data=payload,
                headers={"Content-Type": "application/json"}, method="POST",
            )
            with urllib.request.urlopen(request, timeout=timeout) as response:
                result = json.loads(response.read().decode("utf-8"))
            content = result.get("content")
            if not isinstance(content, str):
                return None
            content = re.sub(r"<think>.*?</think>\s*", "", content, flags=re.DOTALL).strip()
            return content or None
        except (OSError, ValueError, urllib.error.URLError):
            return None

    @staticmethod
    def shutdown_runtime() -> None:
        _ManagedLlamaServer.stop()

    def interpret_intent(self, text: str, session_context: dict[str, Any] | None = None) -> dict[str, Any] | None:
        """Interprets free-form natural language query into constrained JSON intent schema."""
        if not self.is_available():
            return None

        ctx = session_context or {}
        last_asset = ctx.get("last_asset") or "null"
        last_market = ctx.get("last_market") or "PERPETUAL"
        last_tf = ctx.get("last_timeframe") or "H1"
        recent_turns = [] if self.cloud.enabled else (ctx.get("recent_turns") or [])
        history = "\n".join(
            f"User: {turn.get('user', '')}\nAssistant: {turn.get('assistant', '')[:240]}"
            for turn in recent_turns[-4:] if isinstance(turn, dict)
        )

        system_instruction = (
            "<|im_start|>system\n"
            "You are the intent router for OpenBagus crypto research terminal.\n"
            'Output JSON only: {"request_type": "...", "asset": "...", "relation_to_context": "..."}\n'
            'Allowed request_type: ["POSITION", "ANALYZE", "CHART", "MARKET_OUTLOOK", "SYSTEM_INFO", "PREFERENCE", "FEEDBACK", "HARNESS", "UNKNOWN"]\n'
            'Allowed relation_to_context: ["CONTINUE", "SWITCH", "UNRELATED", "UNCERTAIN"]\n\n'
            "Rules:\n"
            '- "posisi btc", "long atau short", "nunggu atau cari long" -> {"request_type": "POSITION", "asset": "BTC", "relation_to_context": "SWITCH"}\n'
            '- "kalau eth gimana", "analisa sol" -> {"request_type": "ANALYZE", "asset": "ETH", "relation_to_context": "SWITCH"}\n'
            '- "tampilkan chart", "grafik eth" -> {"request_type": "CHART", "asset": "ETH", "relation_to_context": "SWITCH"}\n'
            '- "kok no trade terus", "tolol nih" -> {"request_type": "FEEDBACK", "asset": null, "relation_to_context": "CONTINUE"}\n'
            '- "siapa pembuatnya", "tentang sistem" -> {"request_type": "SYSTEM_INFO", "asset": null, "relation_to_context": "UNRELATED"}\n'
            '- "jangan tampilin sources", "hide sources" -> {"request_type": "PREFERENCE", "asset": null, "relation_to_context": "CONTINUE"}\n'
            '- "ini masih nyambung sama btc nggak" -> {"request_type": "HARNESS", "asset": null, "relation_to_context": "CONTINUE"}\n'
            '- "gimana cpi pengaruh ke btc" -> {"request_type": "MARKET_OUTLOOK", "asset": "BTC", "relation_to_context": "SWITCH"}\n'
            "- NEVER classify slang or Indonesian words (lagi, ya, kok, terus, nih, dong) as crypto coins.<|im_end|>\n"
            f"<|im_start|>user\nContext: last_asset={last_asset}, last_market={last_market}, last_tf={last_tf}.\n"
            f"Recent conversation:\n{history or 'none'}\n"
            f"Input: {text}<|im_end|>\n"
            "<|im_start|>assistant\n"
        )

        output = self._complete(system_instruction, max_tokens=128, temp=0.0, top_p=1.0, top_k=1)
        if not output:
            return None

        matches = list(re.finditer(r"\{[^{}]*\}", output, re.DOTALL))
        if not matches:
            matches = list(re.finditer(r"\{.*\}", output, re.DOTALL))
        if not matches:
            return None

        try:
            data = json.loads(matches[-1].group(0))
            if not isinstance(data, dict):
                return None

            req_type = str(data.get("request_type", "UNKNOWN")).upper()
            if req_type not in ALLOWED_LLM_REQUEST_TYPES:
                req_type = "UNKNOWN"

            relation = str(data.get("relation_to_context", "UNCERTAIN")).upper()
            if relation not in ALLOWED_RELATION_TYPES:
                relation = "UNCERTAIN"

            # Asset Safety: non-asset request types MUST NOT have assets
            if req_type in ("FEEDBACK", "SYSTEM_INFO", "HARNESS", "PREFERENCE", "SETUP_CONFIG"):
                data["asset"] = None
                data["asset_2"] = None

            data["request_type"] = req_type
            data["relation_to_context"] = relation
            return data
        except Exception:
            return None

    def generate_narrative(
        self,
        research_packet: Any,
        user_query: str = "",
        language: str = "id",
    ) -> str | None:
        """Generates professional crypto analyst trader narrative strictly grounded in research packet.

        Guarded by numeric invariance check: invented or changed numbers cause immediate rejection.
        """
        if not self.is_available():
            return None

        # Extract structured packet attributes or use provided NarrativeFacts
        packet = research_packet
        if isinstance(packet, NarrativeFacts):
            facts = packet
        else:
            asset = getattr(packet, "asset", "ASSET")
            decision = getattr(packet, "decision", "NO_TRADE")
            price = getattr(packet, "price", 0.0)
            tf = getattr(packet, "timeframe", "H1")
            regime = getattr(packet, "regime", getattr(packet, "market_state", "Compressed"))
            reason = getattr(packet, "decision_reason", getattr(packet, "reason", ""))
            rr_str = getattr(packet, "reward_risk_str", "N/A")

            bull_trig = ""
            bear_trig = ""
            if hasattr(packet, "bullish_validation") and packet.bullish_validation:
                bull_trig = getattr(packet.bullish_validation, "trigger_condition", "")
            if hasattr(packet, "bearish_validation") and packet.bearish_validation:
                bear_trig = getattr(packet.bearish_validation, "trigger_condition", "")

            patterns_obj = getattr(packet, "patterns", {})
            fib_obj = getattr(packet, "fibonacci", {})
            stoch_obj = getattr(packet, "stochastic", {})
            arb_obj = getattr(packet, "arbitrage", {})
            macro_obj = getattr(packet, "macro_item", {})
            flow_obj = getattr(packet, "large_flow_item", {})

            pattern_name = getattr(packet, "pattern_name", "") if patterns_obj.get("material") else ""
            fib_confluence = getattr(packet, "fibonacci_confluence", "") if fib_obj.get("material") else ""
            stoch_note = stoch_obj.get("values", {}).get("summary", "") if stoch_obj.get("material") else ""
            arb_note = f"Net spread {arb_obj.get('values', {}).get('estimated_net_spread_pct', 0):+.2f}%" if arb_obj.get("material") else ""
            macro_note = getattr(packet, "event_risk", "") if macro_obj.get("material") else ""
            large_flow_val = getattr(packet, "large_flow", None)
            flow_note = large_flow_val.get("summary", "") if (flow_obj.get("material") and isinstance(large_flow_val, dict)) else ""

            fib_level = None
            fib_vals = fib_obj.get("values", {})
            if fib_obj.get("material") and isinstance(fib_vals, dict) and fib_vals.get("level") is not None:
                try:
                    fib_level = float(fib_vals["level"])
                except Exception:
                    pass
            elif fib_confluence:
                ratio = re.search(r"Fib\s+0\.(382|500|618|786)", fib_confluence, re.IGNORECASE)
                if ratio and fib_vals.get("fib_" + ratio.group(1)) is not None:
                    fib_level = float(fib_vals["fib_" + ratio.group(1)])
                m_fib = re.search(r"\$([0-9,]+(?:\.[0-9]+)?)", fib_confluence)
                if m_fib and fib_level is None:
                    try:
                        fib_level = float(m_fib.group(1).replace(",", ""))
                    except Exception:
                        pass

            price_vs_fib = ""
            if fib_level is not None and price > 0:
                if price > fib_level:
                    price_vs_fib = "ABOVE"
                elif price < fib_level:
                    price_vs_fib = "BELOW"

            facts = NarrativeFacts(
                asset=asset,
                price=price,
                decision=decision,
                timeframe=tf,
                regime=regime,
                reason=reason,
                reward_risk_str=rr_str,
                bullish_trigger=bull_trig,
                bearish_trigger=bear_trig,
                fibonacci_level=fib_level,
                fibonacci_confluence=fib_confluence,
                price_vs_fib=price_vs_fib,
                pattern_name=pattern_name,
                stochastic_summary=stoch_note,
                arbitrage_summary=arb_note,
                macro_event=macro_note,
                large_flow_summary=flow_note,
                market=getattr(packet, "market", "GENERAL / SPOT REFERENCE"),
                rr_long=getattr(getattr(packet, "bullish_validation", None), "reward_risk", None),
                rr_short=getattr(getattr(packet, "bearish_validation", None), "reward_risk", None),
                rr_gate_passed=bool(getattr(packet, "rr_gate_passed", False)),
                event_dates=re.findall(r"\b\d{4}-\d{2}-\d{2}\b", str(getattr(packet, "macro", {}))),
                frequency=getattr(packet, "frequency_cycle", {}).get("values", {}).get("summary", "") if re.search(r"\b(?:frequency|cycle)\b", user_query, re.IGNORECASE) and getattr(packet, "frequency_cycle", {}).get("material") else "",
                bullish_trigger_level=getattr(getattr(packet, "bullish_validation", None), "trigger_level", None),
                bullish_trigger_state=getattr(getattr(packet, "bullish_validation", None), "trigger_state", "UNKNOWN"),
                bearish_trigger_level=getattr(getattr(packet, "bearish_validation", None), "trigger_level", None),
                bearish_trigger_state=getattr(getattr(packet, "bearish_validation", None), "trigger_state", "UNKNOWN"),
                data_freshness=getattr(packet, "data_freshness", "UNVERIFIED"),
                contradictions=getattr(packet, "contradictions", []),
                evidence_families=getattr(packet, "evidence_families", {}),
                entry_zone=getattr(packet, "entry_zone", ""),
                stop_price=getattr(packet, "stop_price", None),
                target_price=getattr(packet, "tp1", None),
                data_quality=getattr(packet, "data_quality", "UNKNOWN"),
            )
        if facts.fibonacci_level is not None:
            facts.price_vs_fib = "ABOVE" if facts.price > facts.fibonacci_level else ("BELOW" if facts.price < facts.fibonacci_level else "AT")

        lang_label = "Indonesian (Bahasa Indonesia)" if language == "id" else "English"

        prompt = (
            f"<|im_start|>system\n"
            f"You are a senior quantitative crypto research consultant. Answer the user's actual question in {lang_label}, naturally and concisely.\n"
            "Use this ontology only when relevant: spot, perpetual, long, short, entry, invalidation, stop loss, TP, reward:risk, basis, funding, open interest, CVD, order flow, liquidity, volatility, support/resistance, market structure, Fibonacci confluence, Stochastic, patterns, cross-venue dislocation, arbitrage, large flow, whale context, CPI, FOMC, DXY, US10Y, VIX, gold, oil, DeFi, DEX, stablecoins.\n"
            "STRICT RULES:\n"
            f"1. You MUST keep the decision '{facts.decision}' and asset '{facts.asset}'.\n"
            "2. DO NOT invent prices, stops, targets, or percentages not provided in the facts.\n"
            "Unconfirmed or UNKNOWN triggers are future conditions, never completed breakouts/breakdowns. Use conditional language.\n"
            "3. Use short plain paragraphs, matching the question. Confidence categories describe data quality, not calibrated odds. Never invent whale activity, event dates or performance.\n"
            "4. Do NOT repeat formulaic phrases or dump a full report when the user asks a narrow follow-up.<|im_end|>\n"
            f"<|im_start|>user\nQuestion: {user_query or 'Explain the current research view.'}\nFacts from QuantEngine:\n"
            f"- Asset: {facts.asset} ({facts.timeframe})\n"
            f"- Price: {format_price(facts.price)}\n"
            f"- Market: {facts.market}\n"
            f"- RR Long: {facts.rr_long}; RR Short: {facts.rr_short}; Gate passed: {facts.rr_gate_passed}\n"
            f"- Event dates: {', '.join(facts.event_dates) or 'none'}\n"
            f"- Quant Decision: {facts.decision}\n"
            f"- Market Regime: {facts.regime}\n"
            f"- Reason: {facts.reason} (RR: {facts.reward_risk_str})\n"
            f"- Data freshness: {facts.data_freshness}\n"
            f"- Data quality: {facts.data_quality} (never upgrade this category)\n"
            f"- Entry: {facts.entry_zone}; stop: {facts.stop_price}; target: {facts.target_price}\n"
            f"- Independent evidence: {json.dumps(facts.evidence_families)}\n"
            f"- Contradictions: {json.dumps(facts.contradictions)}\n"
            f"- Bullish Validation: {facts.bullish_trigger}\n"
            f"- Bearish Validation: {facts.bearish_trigger}\n"
            f"- Bullish trigger level/state: {facts.bullish_trigger_level} / {facts.bullish_trigger_state}\n"
            f"- Bearish trigger level/state: {facts.bearish_trigger_level} / {facts.bearish_trigger_state}\n"
            + (f"- Chart Pattern: {facts.pattern_name}\n" if facts.pattern_name else "")
            + (f"- Fibonacci: {facts.fibonacci_level}; price relation: {facts.price_vs_fib}; {facts.fibonacci_confluence}\n" if facts.fibonacci_level is not None else (f"- Fibonacci Confluence: {facts.fibonacci_confluence}\n" if facts.fibonacci_confluence else ""))
            + (f"- Stochastic: {facts.stochastic_summary}\n" if facts.stochastic_summary else "")
            + (f"- Arbitrage: {facts.arbitrage_summary}\n" if facts.arbitrage_summary else "")
            + (f"- Frequency: {facts.frequency}\n" if facts.frequency else "")
            + (f"- Macro: {facts.macro_event}\n" if facts.macro_event else "")
            + (f"- Flow Activity: {facts.large_flow_summary}\n" if facts.large_flow_summary else "")
            + f"<|im_end|>\n<|im_start|>assistant\n"
        )

        for attempt in range(2):
            current_prompt = prompt if attempt == 0 else prompt.replace(
                "STRICT RULES:\n", "STRICT RULES:\nPrevious wording failed factual validation. Use only the supplied facts and conditional trigger language.\n",
            )
            res = self._complete(
                current_prompt, max_tokens=400, temp=0.4, top_p=0.8,
                top_k=20, presence_penalty=1.2,
            )
            if res:
                clean = re.sub(r"^(?:Trader Note:?|Note:?|Summary:?)\s*", "", res.strip(), flags=re.IGNORECASE)
                if self._narrative_is_grounded(facts, clean):
                    return clean
        return None

    @staticmethod
    def _narrative_is_grounded(facts: NarrativeFacts, clean_narrative: str) -> bool:
        upper_text = clean_narrative.upper()
        if facts.decision in ("NO_TRADE", "WAIT"):
            if "BUY NOW" in upper_text or "SEGERA BELI" in upper_text or "ENTRY SEKARANG" in upper_text:
                return False
        elif facts.decision in ("BUY", "LONG"):
            if "SHORT NOW" in upper_text or "JUAL SEKARANG" in upper_text:
                return False

        # Semantic Grounding Guard 1: Fibonacci relative position contradiction
        lower_narrative = clean_narrative.lower()
        from openbagus.delivery.safety import scan_text
        if not scan_text(clean_narrative)["passed"]:
            return False
        if re.search(r"\b(?:win.?rate|accuracy|probability|peluang|akurasi)\b.{0,30}\d+\s*%|\b(?:whales?\s+(?:buying|selling|accumulat)|paus\s+(?:membeli|menjual|akumulasi))", lower_narrative):
            return False
        if re.search(r"(?:decision|keputusan|recommendation)\s*[:=]?\s*(?:long|short|buy)\b", lower_narrative) and facts.decision in {"WAIT", "NO_TRADE", "AVOID_ENTRY"}:
            return False
        if facts.data_quality.upper() == "LOW" and re.search(r"kualitas\s+data\s+(?:tinggi|baik|memadai)|(?:high|good|adequate)\s+(?:data\s+)?quality|data\s+quality\s*[:=]?\s*high|konsistensi\s+pasar", lower_narrative):
            return False
        if facts.data_freshness not in {"FRESH", "UNVERIFIED"} and re.search(r"data\s+(?:segar|fresh)|fresh\s+data", lower_narrative):
            return False
        for name, expected in ((r"stop(?: loss)?|sl|invalidasi", facts.stop_price), (r"target|tp1", facts.target_price)):
            for claim in re.finditer(r"(?:" + name + r")\s*(?:at|di|pada|:|=)?\s*\$([0-9,]+(?:\.[0-9]+)?)", lower_narrative):
                # Conditional scenarios have their own levels, not an active stop/target.
                if expected is not None and float(claim.group(1).replace(",", "")) != expected:
                    return False
        confirmed_up = r"(?:crossed|closed|broke|broken)\s+above|breakout\s+(?:confirmed|has\s+occurred)|sudah\s+(?:menembus|breakout|close\s+di\s+atas)|telah\s+(?:menembus|breakout)"
        confirmed_down = r"(?:crossed|closed|broke|broken)\s+below|breakdown\s+(?:confirmed|has\s+occurred)|sudah\s+(?:breakdown|close\s+di\s+bawah|menembus\s+(?:ke\s+)?bawah)|telah\s+(?:breakdown|menembus\s+bawah)"
        if facts.bullish_trigger_state != "CONFIRMED" and re.search(confirmed_up, lower_narrative):
            return False
        if facts.bearish_trigger_state != "CONFIRMED" and re.search(confirmed_down, lower_narrative):
            return False
        if facts.price_vs_fib == "ABOVE":
            if re.search(r"(?:di\s+bawah|below|under)\s+(?:(?:the|level)\s+){0,2}fib(?:onacci)?", lower_narrative):
                return False
        elif facts.price_vs_fib == "BELOW":
            if re.search(r"(?:di\s+atas|above|over)\s+(?:(?:the|level)\s+){0,2}fib(?:onacci)?", lower_narrative):
                return False

        # Semantic Grounding Guard 2: Hallucinated date / temporal horizon
        raw_facts = f"{facts.price} {format_price(facts.price)} {facts.fibonacci_level} {facts.rr_long} {facts.rr_short} {facts.reward_risk_str} {facts.bullish_trigger} {facts.bearish_trigger} {facts.reason} {facts.fibonacci_confluence} {facts.pattern_name} {facts.stochastic_summary} {facts.arbitrage_summary} {facts.frequency} {facts.macro_event} {facts.large_flow_summary} {' '.join(facts.event_dates)} {facts.evidence_families} {facts.contradictions} {facts.entry_zone} {facts.stop_price} {facts.target_price}"
        for phrase in ("akhir bulan", "end of month", "bulan depan", "next month", "minggu depan", "next week"):
            if phrase in lower_narrative and phrase not in " ".join(facts.event_dates).lower():
                return False

        # Semantic Grounding Guard 3: Bullish trigger mislabeled as opening price
        if re.search(r"harga\s+pembukaan\s*(?:di|pada|sebesar)?\s*\$?\d+", lower_narrative):
            return False

        # Integrity Validation 2 (C3 Numeric Invariance Guard):
        # Extract numbers from narrative and check they exist in packet
        from decimal import Decimal
        number_pattern = r"(?<![\w.])\d+(?:,\d{3})*(?:\.\d+)?"
        valid_numbers = {Decimal(num.replace(",", "")) for num in re.findall(number_pattern, raw_facts)}

        # Numbers <= 10 or common integers (1, 2, 3, 4, 10, etc.) are allowed for sentence structure
        for match in re.finditer(number_pattern, clean_narrative):
            num_str = match.group()
            value = Decimal(num_str.replace(",", ""))
            monetary = clean_narrative[:match.start()].rstrip().endswith("$")
            if not monetary and "." not in num_str and value <= 10:
                continue
            if value not in valid_numbers:
                return False

        return True

    def answer_system_question(self, query: str = "", language: str = "id") -> str:
        """Returns factual OpenBagus system information strictly from the canonical profile."""
        p = SYSTEM_PROFILE
        if language == "en":
            lines = [
                f"{p['name']} Runtime & Architecture",
                "=" * 40,
                f"Creator:         {p['creator']}",
                f"Purpose:         {p['purpose']}",
                f"Core Engine:     {p['core']}",
                f"Market Data:     {p['data']}",
                f"Language Layer:  {p['language_layer']}",
                f"Active Domain:   {p['active_domain']}",
                f"Trading Exec:    {p['trading_execution']}",
                f"Secrets Safety:  {p['secrets']}",
            ]
        else:
            lines = [
                f"{p['name']} Runtime & Arsitektur",
                "=" * 40,
                f"Pembuat:         {p['creator']}",
                f"Tujuan:          {p['purpose']}",
                f"Mesin Utama:     {p['core']}",
                f"Penyedia Data:   {p['data']}",
                f"Lapisan Bahasa:  {p['language_layer']}",
                f"Domain Aktif:    {p['active_domain']}",
                f"Eksekusi Order:  {p['trading_execution']}",
                f"Privasi Rahasia: {p['secrets']}",
            ]
        return "\n".join(lines)


def _download_file(url: str, path: Path, expected_sha: str = "") -> bool:
    request = urllib.request.Request(url, headers={"User-Agent": "OpenBagus-Setup/2.0"})
    try:
        with urllib.request.urlopen(request, context=ssl.create_default_context(), timeout=120) as response:
            with path.open("wb") as output:
                while chunk := response.read(1024 * 1024):
                    output.write(chunk)
        return path.is_file() and path.stat().st_size > 1_000_000 and (
            not expected_sha or _verify_sha256(path, expected_sha)
        )
    except (OSError, urllib.error.URLError):
        return False


def _official_model_sha() -> str | None:
    try:
        request = urllib.request.Request(
            f"https://huggingface.co/api/models/{MODEL_REPOSITORY}/tree/main?recursive=true&expand=true",
            headers={"User-Agent": "OpenBagus-Setup/2.0"},
        )
        with urllib.request.urlopen(request, context=ssl.create_default_context(), timeout=20) as response:
            metadata = json.loads(response.read().decode("utf-8"))
        for item in metadata:
            if item.get("path") == MODEL_NAME:
                return item.get("lfs", {}).get("oid")
    except (OSError, ValueError, urllib.error.URLError):
        return None
    return None


def _select_llama_assets() -> tuple[str, list[dict[str, Any]]]:
    request = urllib.request.Request(
        "https://api.github.com/repos/ggml-org/llama.cpp/releases?per_page=5",
        headers={"User-Agent": "OpenBagus-Setup/2.0", "Accept": "application/vnd.github.v3+json"},
    )
    with urllib.request.urlopen(request, context=ssl.create_default_context(), timeout=20) as response:
        releases = json.loads(response.read().decode("utf-8"))
    nvidia = shutil.which("nvidia-smi") is not None
    preferences = ("cuda-13", "cuda-12", "vulkan", "cpu") if nvidia else ("vulkan", "cpu")
    for backend in preferences:
        for release in releases:
            assets = release.get("assets", [])
            runtime = next((
                a for a in assets
                if f"bin-win-{backend}" in a.get("name", "").lower()
                and "cudart-" not in a.get("name", "").lower()
                and a.get("name", "").lower().endswith("x64.zip")
            ), None)
            if not runtime:
                continue
            selected = [runtime]
            if backend.startswith("cuda"):
                cudart = next((a for a in assets if "cudart-llama-bin-win" in a.get("name", "").lower() and backend in a.get("name", "").lower() and a.get("name", "").lower().endswith("x64.zip")), None)
                if not cudart:
                    continue
                selected.append(cudart)
            return backend.upper(), selected
    return "UNAVAILABLE", []


def provision_local_runtime(download_model: bool = True, download_llama: bool = True) -> bool:
    """Safely provisions the canonical model and GPU-preferred llama.cpp runtime."""
    MODELS_DIR.mkdir(parents=True, exist_ok=True)
    BIN_DIR.parent.mkdir(parents=True, exist_ok=True)
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    backup_dir = BIN_DIR.parent / "bin-backup"
    staging_dir = BIN_DIR.parent / "bin-staging"
    current_backend = _ManagedLlamaServer.detect_backend(LLAMA_SERVER_EXE)
    runtime_changed = False

    def restore_runtime() -> bool:
        if not runtime_changed or not backup_dir.exists():
            return True
        _ManagedLlamaServer.stop()
        for _attempt in range(10):
            shutil.rmtree(BIN_DIR, ignore_errors=True)
            if not BIN_DIR.exists():
                backup_dir.rename(BIN_DIR)
                return True
            time.sleep(0.25)
        print(f"[WARN] Runtime rollback is pending; preserved backup at {backup_dir}")
        return False

    if download_llama and (not LLAMA_SERVER_EXE.is_file() or (shutil.which("nvidia-smi") and current_backend != "CUDA")):
        print("[....] Resolving current official llama.cpp Windows runtime")
        try:
            selected_backend, assets = _select_llama_assets()
        except (OSError, ValueError, urllib.error.URLError):
            selected_backend, assets = "UNAVAILABLE", []
        if not assets:
            print("[WARN] No suitable official llama.cpp Windows runtime was found.")
            return False
        shutil.rmtree(staging_dir, ignore_errors=True)
        staging_dir.mkdir(parents=True)
        for index, asset in enumerate(assets):
            archive = staging_dir / f"runtime-{index}.zip"
            digest = str(asset.get("digest") or "").removeprefix("sha256:")
            print(f"[....] Downloading {asset['name']}")
            if not _download_file(asset["browser_download_url"], archive, digest):
                shutil.rmtree(staging_dir, ignore_errors=True)
                print("[WARN] llama.cpp download or checksum verification failed.")
                return False
            with zipfile.ZipFile(archive) as package:
                package.extractall(staging_dir)
            archive.unlink(missing_ok=True)
        if not (staging_dir / LLAMA_SERVER_EXE.name).is_file():
            shutil.rmtree(staging_dir, ignore_errors=True)
            return False
        _ManagedLlamaServer.stop()
        shutil.rmtree(backup_dir, ignore_errors=True)
        if BIN_DIR.exists():
            BIN_DIR.rename(backup_dir)
        staging_dir.rename(BIN_DIR)
        runtime_changed = True
        print(f"[PASS] llama.cpp runtime installed ({selected_backend})")

    if download_model:
        official_sha = _official_model_sha()
        if official_sha != QWEN3_SHA256:
            restore_runtime()
            print("[WARN] Official Hugging Face metadata did not match the canonical model SHA-256.")
            return False
        if MODEL_FILE.is_file() and not _verify_sha256(MODEL_FILE, QWEN3_SHA256):
            MODEL_FILE.unlink(missing_ok=True)
        if not MODEL_FILE.is_file():
            temporary = MODEL_FILE.with_suffix(".part")
            temporary.unlink(missing_ok=True)
            print(f"[....] Downloading {MODEL_NAME} (~2.5 GB) from official Qwen repository")
            if not _download_file(MODEL_URL, temporary, QWEN3_SHA256):
                temporary.unlink(missing_ok=True)
                restore_runtime()
                print("[WARN] Model download or checksum verification failed.")
                return False
            temporary.replace(MODEL_FILE)
        print(f"[PASS] Model verified: {MODEL_FILE}")

    engine = LocalLanguageEngine()
    print("[....] Running routing and narrative inference smoke tests")
    routing_ok = engine._smoke_test(timeout=120)
    narrative = engine.generate_narrative(
        NarrativeFacts(asset="BTC", price=85000.0, decision="WAIT", reason="RR gate belum terpenuhi"),
        user_query="jelaskan singkat kondisi BTC", language="id",
    )
    if not routing_ok or not narrative:
        restore_runtime()
        print("[WARN] Local Language Engine smoke tests failed; old model remains available.")
        return False
    (CACHE_DIR / "llm_4b_smoke.ok").write_text("OK", encoding="utf-8")
    if OLD_MODEL_FILE.is_file():
        OLD_MODEL_FILE.unlink()
    shutil.rmtree(backup_dir, ignore_errors=True)
    print(f"[PASS] Local Language Engine: ACTIVE ({_ManagedLlamaServer.detect_backend(LLAMA_SERVER_EXE)})")
    return True
