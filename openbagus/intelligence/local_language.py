"""OpenBagus Local Language Engine.

Provides offline, private, zero-API-key local language intelligence using
Qwen3-0.6B-Q8_0.gguf through direct llama.cpp CLI subprocess execution.

Roles:
1. Intent Interpreter: Free-form conversational intent classification with strict JSON output.
2. Natural Narrative: Professional consultant-style crypto trader note narrative.
3. System Profile: Canonical factual responses about OpenBagus architecture and origins.

QuantEngine remains 100% authoritative for all calculations, decisions, and prices.
"""

from __future__ import annotations

import hashlib
import io
import json
import os
import re
import ssl
import subprocess
import sys
import time
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
MODEL_NAME = "Qwen3-0.6B-Q8_0.gguf"
MODEL_FILE = MODELS_DIR / MODEL_NAME
LLAMA_CLI_EXE = BIN_DIR / ("llama-cli.exe" if os.name == "nt" else "llama-cli")

# Official SHA-256 Checksum for Qwen3-0.6B-Q8_0.gguf from Hugging Face LFS
QWEN3_SHA256 = "9465e63a22add5354d9bb4b99e90117043c7124007664907259bd16d043bb031"

# Canonical Factual OpenBagus System Profile (Section 12)
SYSTEM_PROFILE: dict[str, str] = {
    "name": "OpenBagus",
    "creator": "Ahmad Bagus Idkholus Surur",
    "purpose": "Crypto quantitative research and decision-support CLI",
    "core": "Local deterministic QuantEngine (Microstructure & Risk)",
    "data": "Online Zero-Key public providers (16 active) + optional keyed providers",
    "language_layer": "Local lightweight model (Qwen3-0.6B-Q8_0.gguf via direct llama.cpp)",
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


class LocalLanguageEngine:
    """Manages local llama.cpp execution for intent parsing and consultant narrative."""

    def __init__(
        self,
        model_path: Path | None = None,
        llama_bin: Path | None = None,
        repo_root: Path | None = None,
    ) -> None:
        self.root = repo_root or get_repo_root()
        custom_model = os.environ.get("OPENBAGUS_MODEL_PATH")
        custom_llama = os.environ.get("OPENBAGUS_LLAMA_CLI")

        self.model_path = Path(custom_model) if custom_model else (model_path or MODEL_FILE)
        self.llama_bin = Path(custom_llama) if custom_llama else (llama_bin or LLAMA_CLI_EXE)

    def is_available(self) -> bool:
        """Returns True only if both llama.cpp CLI and the Qwen model GGUF exist on disk."""
        return self.llama_bin.is_file() and self.model_path.is_file()

    def get_runtime_state(self) -> str:
        """Returns runtime state: ACTIVE, FALLBACK, or UNAVAILABLE."""
        if not self.is_available():
            if not self.model_path.is_file() and not self.llama_bin.is_file():
                return "UNAVAILABLE"
            return "FALLBACK"

        smoke_file = CACHE_DIR / "llm_smoke.ok"
        if smoke_file.is_file():
            try:
                if smoke_file.stat().st_mtime >= self.llama_bin.stat().st_mtime:
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
        }

    def _smoke_test(self, timeout: float = 12.0) -> bool:
        """Runs ONE real inference smoke test against llama-cli to verify readiness."""
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
        timeout: float = 15.0,
    ) -> str | None:
        """Executes llama-cli subprocess directly without HTTP server overhead."""
        if not self.is_available():
            return None

        cmd = [
            str(self.llama_bin),
            "-m", str(self.model_path),
            "-p", prompt,
            "-n", str(max_tokens),
            "-c", "1024",
            "--temp", str(temp),
            "--top-p", str(top_p),
            "--top-k", str(top_k),
            "-ngl", "0",
            "--no-display-prompt",
            "--single-turn",
            "--simple-io",
            "--chat-template-kwargs", '{"enable_thinking":false}',
        ]
        try:
            res = subprocess.run(
                cmd,
                stdin=subprocess.DEVNULL,
                capture_output=True,
                text=True,
                timeout=timeout,
                encoding="utf-8",
                errors="replace",
            )
            if res.returncode == 0 and res.stdout:
                raw = res.stdout
                # Clean prompt echo, banner, and performance footer
                clean = re.sub(r"\[\s*Prompt:.*?\]", "", raw, flags=re.DOTALL)
                clean = re.sub(r"Exiting\.\.\.", "", clean)
                if "(truncated)" in clean:
                    clean = clean.split("(truncated)")[-1]
                elif "<|im_start|>assistant" in clean:
                    clean = clean.split("<|im_start|>assistant")[-1]
                elif "\n\n> " in clean:
                    clean = clean.split("\n\n> ")[-1]
                return clean.strip()
            return None
        except Exception:
            return None

    def interpret_intent(self, text: str, session_context: dict[str, Any] | None = None) -> dict[str, Any] | None:
        """Interprets free-form natural language query into constrained JSON intent schema."""
        if not self.is_available():
            return None

        ctx = session_context or {}
        last_asset = ctx.get("last_asset") or "null"
        last_market = ctx.get("last_market") or "PERPETUAL"
        last_tf = ctx.get("last_timeframe") or "H1"

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
            f"Input: {text}<|im_end|>\n"
            "<|im_start|>assistant\n"
        )

        output = self._run_llama(system_instruction, max_tokens=128, temp=0.0)
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
            )
        if facts.fibonacci_level is not None:
            facts.price_vs_fib = "ABOVE" if facts.price > facts.fibonacci_level else ("BELOW" if facts.price < facts.fibonacci_level else "AT")

        lang_label = "Indonesian (Bahasa Indonesia)" if language == "id" else "English"

        prompt = (
            f"<|im_start|>system\n"
            f"You are a senior quantitative crypto research consultant. Write an objective, concise 4-8 sentence trader note in {lang_label}.\n"
            "STRICT RULES:\n"
            f"1. You MUST keep the decision '{facts.decision}' and asset '{facts.asset}'.\n"
            "2. DO NOT invent prices, stops, targets, or percentages not provided in the facts.\n"
            "3. Sound like an objective institutional consultant giving high-conviction decision support, not an AI bot.\n"
            "4. Do NOT repeat formulaic phrases like 'diperdagangkan pada' or 'disarankan menahan diri'.<|im_end|>\n"
            f"<|im_start|>user\nFacts from QuantEngine:\n"
            f"- Asset: {facts.asset} ({facts.timeframe})\n"
            f"- Price: {format_price(facts.price)}\n"
            f"- Market: {facts.market}\n"
            f"- RR Long: {facts.rr_long}; RR Short: {facts.rr_short}; Gate passed: {facts.rr_gate_passed}\n"
            f"- Event dates: {', '.join(facts.event_dates) or 'none'}\n"
            f"- Quant Decision: {facts.decision}\n"
            f"- Market Regime: {facts.regime}\n"
            f"- Reason: {facts.reason} (RR: {facts.reward_risk_str})\n"
            f"- Bullish Validation: {facts.bullish_trigger}\n"
            f"- Bearish Validation: {facts.bearish_trigger}\n"
            + (f"- Chart Pattern: {facts.pattern_name}\n" if facts.pattern_name else "")
            + (f"- Fibonacci: {facts.fibonacci_level}; price relation: {facts.price_vs_fib}; {facts.fibonacci_confluence}\n" if facts.fibonacci_level is not None else (f"- Fibonacci Confluence: {facts.fibonacci_confluence}\n" if facts.fibonacci_confluence else ""))
            + (f"- Stochastic: {facts.stochastic_summary}\n" if facts.stochastic_summary else "")
            + (f"- Arbitrage: {facts.arbitrage_summary}\n" if facts.arbitrage_summary else "")
            + (f"- Frequency: {facts.frequency}\n" if facts.frequency else "")
            + (f"- Macro: {facts.macro_event}\n" if facts.macro_event else "")
            + (f"- Flow Activity: {facts.large_flow_summary}\n" if facts.large_flow_summary else "")
            + f"<|im_end|>\n<|im_start|>assistant\n"
        )

        res = self._run_llama(prompt, max_tokens=220, temp=0.35, top_p=0.8, top_k=20)
        if not res:
            return None

        clean_narrative = re.sub(r"^(?:Trader Note:?|Note:?|Summary:?)\s*", "", res.strip(), flags=re.IGNORECASE)

        # Integrity Validation 1: Verify decision alignment
        upper_text = clean_narrative.upper()
        if facts.decision in ("NO_TRADE", "WAIT"):
            if "BUY NOW" in upper_text or "SEGERA BELI" in upper_text or "ENTRY SEKARANG" in upper_text:
                return None
        elif facts.decision in ("BUY", "LONG"):
            if "SHORT NOW" in upper_text or "JUAL SEKARANG" in upper_text:
                return None

        # Semantic Grounding Guard 1: Fibonacci relative position contradiction
        lower_narrative = clean_narrative.lower()
        if facts.price_vs_fib == "ABOVE":
            if re.search(r"(?:di\s+bawah|below|under)\s+(?:(?:the|level)\s+){0,2}fib(?:onacci)?", lower_narrative):
                return None
        elif facts.price_vs_fib == "BELOW":
            if re.search(r"(?:di\s+atas|above|over)\s+(?:(?:the|level)\s+){0,2}fib(?:onacci)?", lower_narrative):
                return None

        # Semantic Grounding Guard 2: Hallucinated date / temporal horizon
        raw_facts = f"{facts.price} {format_price(facts.price)} {facts.fibonacci_level} {facts.rr_long} {facts.rr_short} {facts.reward_risk_str} {facts.bullish_trigger} {facts.bearish_trigger} {facts.reason} {facts.fibonacci_confluence} {facts.pattern_name} {facts.stochastic_summary} {facts.arbitrage_summary} {facts.frequency} {facts.macro_event} {facts.large_flow_summary} {' '.join(facts.event_dates)}"
        for phrase in ("akhir bulan", "end of month", "bulan depan", "next month", "minggu depan", "next week"):
            if phrase in lower_narrative and phrase not in " ".join(facts.event_dates).lower():
                return None

        # Semantic Grounding Guard 3: Bullish trigger mislabeled as opening price
        if re.search(r"harga\s+pembukaan\s*(?:di|pada|sebesar)?\s*\$?\d+", lower_narrative):
            return None

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
                # Model invented a price or number not in facts
                return None

        return clean_narrative

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


def provision_local_runtime(download_model: bool = True, download_llama: bool = True) -> bool:
    """Provisions llama-cli and Qwen3-0.6B-Q8_0.gguf into %LOCALAPPDATA%\\OpenBagus.

    - Queries GitHub Releases API dynamically for the newest Windows x64 CPU binary.
    - Validates SHA-256 for both llama.cpp and Qwen model.
    - Executes ONE real inference smoke test before reporting success.
    """
    MODELS_DIR.mkdir(parents=True, exist_ok=True)
    BIN_DIR.mkdir(parents=True, exist_ok=True)
    CACHE_DIR.mkdir(parents=True, exist_ok=True)

    ssl_ctx = ssl.create_default_context()
    headers = {"User-Agent": "OpenBagus-Setup/1.0", "Accept": "application/vnd.github.v3+json"}

    # 1. llama.cpp Windows binaries
    if download_llama and not LLAMA_CLI_EXE.is_file():
        print("[....] Querying latest llama.cpp release from GitHub")
        llama_asset = None
        for attempt in range(4):
            try:
                req = urllib.request.Request(
                    "https://api.github.com/repos/ggml-org/llama.cpp/releases?per_page=3",
                    headers=headers,
                )
                with urllib.request.urlopen(req, context=ssl_ctx, timeout=15) as resp:
                    releases = json.loads(resp.read().decode("utf-8"))
                    for r in releases:
                        for a in r.get("assets", []):
                            aname = a.get("name", "").lower()
                            if "bin-win-cpu-x64.zip" in aname or ("win" in aname and "cpu" in aname and "x64" in aname and aname.endswith(".zip")):
                                llama_asset = a
                                break
                        if llama_asset:
                            break
                if llama_asset:
                    break
            except Exception as e:
                time.sleep(1.5)

        if not llama_asset:
            print("[WARN] Could not find suitable llama.cpp binary in GitHub releases.")
            return False

        dl_url = llama_asset["browser_download_url"]
        expected_sha = llama_asset.get("digest", "").replace("sha256:", "").strip()
        print(f"[....] Downloading {llama_asset['name']}")

        tmp_zip = BIN_DIR / "llama_win.tmp.zip"
        downloaded = False
        for attempt in range(4):
            try:
                req_dl = urllib.request.Request(dl_url, headers={"User-Agent": "OpenBagus-Setup/1.0"})
                with urllib.request.urlopen(req_dl, context=ssl_ctx, timeout=60) as resp:
                    with open(tmp_zip, "wb") as f:
                        f.write(resp.read())

                if tmp_zip.is_file() and tmp_zip.stat().st_size > 1_000_000:
                    if expected_sha:
                        if not _verify_sha256(tmp_zip, expected_sha):
                            print("[WARN] SHA-256 mismatch on downloaded llama.cpp; aborting.")
                            tmp_zip.unlink(missing_ok=True)
                            return False
                    with zipfile.ZipFile(tmp_zip, "r") as z:
                        z.extractall(BIN_DIR)
                    downloaded = True
                    break
            except Exception as e:
                time.sleep(2.0)
            finally:
                tmp_zip.unlink(missing_ok=True)

        if not downloaded:
            print("[WARN] Failed downloading llama.cpp runtime.")
            return False

    # 2. Qwen3-0.6B-Q8_0.gguf (~639 MB)
    if download_model:
        if MODEL_FILE.is_file():
            print("[....] Verifying existing Qwen3-0.6B model checksum")
            if not _verify_sha256(MODEL_FILE, QWEN3_SHA256):
                print("[WARN] Existing model checksum mismatch; removing corrupted file.")
                MODEL_FILE.unlink(missing_ok=True)
            else:
                print(f"[PASS] Model verified: {MODEL_FILE}")

        if not MODEL_FILE.is_file():
            model_urls = [
                "https://huggingface.co/Qwen/Qwen3-0.6B-GGUF/resolve/main/Qwen3-0.6B-Q8_0.gguf",
                "https://huggingface.co/bartowski/Qwen_Qwen3-0.6B-GGUF/resolve/main/Qwen3-0.6B-Q8_0.gguf",
            ]
            tmp_model = MODELS_DIR / "qwen3_model.tmp.gguf"
            downloaded = False
            for url in model_urls:
                try:
                    print(f"[....] Downloading {MODEL_NAME} (~639 MB) from {url}")
                    for attempt in range(4):
                        try:
                            req_m = urllib.request.Request(url, headers={"User-Agent": "OpenBagus-Setup/1.0"})
                            with urllib.request.urlopen(req_m, context=ssl_ctx, timeout=120) as resp:
                                with open(tmp_model, "wb") as f:
                                    while chunk := resp.read(1024 * 1024):
                                        f.write(chunk)
                            if tmp_model.is_file() and tmp_model.stat().st_size > 300_000_000:
                                if _verify_sha256(tmp_model, QWEN3_SHA256):
                                    tmp_model.rename(MODEL_FILE)
                                    downloaded = True
                                    print(f"[PASS] Model verified and saved: {MODEL_FILE}")
                                    break
                                else:
                                    print("[WARN] Model SHA-256 verification failed; retrying.")
                                    tmp_model.unlink(missing_ok=True)
                        except Exception:
                            time.sleep(2.0)
                    if downloaded:
                        break
                except Exception as e:
                    print(f"[WARN] Failed downloading model from {url}: {e}")
                finally:
                    tmp_model.unlink(missing_ok=True)

            if not downloaded:
                print("[WARN] Model download incomplete; falling back safely.")
                return False

    # 3. Real Inference Smoke Test Verification
    engine = LocalLanguageEngine()
    print("[....] Running local LLM smoke test inference")
    if engine._smoke_test():
        try:
            (CACHE_DIR / "llm_smoke.ok").write_text("OK", encoding="utf-8")
        except Exception:
            pass
        print("[PASS] Local Language Engine: ACTIVE")
        return True
    else:
        print("[WARN] Local Language Engine: FALLBACK (smoke test did not succeed)")
        return False
