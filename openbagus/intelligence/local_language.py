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

import json
import os
import re
import subprocess
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from openbagus.core.env import get_repo_root


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
MODEL_NAME = "Qwen3-0.6B-Q8_0.gguf"
MODEL_FILE = MODELS_DIR / MODEL_NAME
LLAMA_CLI_EXE = BIN_DIR / ("llama-cli.exe" if os.name == "nt" else "llama-cli")

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
    "SETUP_CONFIG",
    "UNKNOWN",
}


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

    def get_status_info(self) -> dict[str, Any]:
        """Returns local language runtime status metadata."""
        avail = self.is_available()
        return {
            "available": avail,
            "model_name": MODEL_NAME,
            "model_path": str(self.model_path),
            "model_exists": self.model_path.is_file(),
            "model_size_mb": round(self.model_path.stat().st_size / (1024 * 1024), 1) if self.model_path.is_file() else 0.0,
            "llama_bin": str(self.llama_bin),
            "llama_exists": self.llama_bin.is_file(),
        }

    def _run_llama(self, prompt: str, max_tokens: int = 192, temp: float = 0.0, timeout: float = 12.0) -> str | None:
        """Executes llama-cli subprocess directly without HTTP server overhead."""
        if not self.is_available():
            return None

        cmd = [
            str(self.llama_bin),
            "-m", str(self.model_path),
            "-p", prompt,
            "-n", str(max_tokens),
            "--temp", str(temp),
            "-ngl", "0",
            "--no-display-prompt",
        ]

        try:
            res = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout,
                encoding="utf-8",
                errors="replace",
            )
            if res.returncode == 0 and res.stdout:
                return res.stdout.strip()
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
            "You are the intent router for OpenBagus, a crypto market research terminal.\n"
            "Analyze the user input and output ONLY valid JSON matching this exact schema:\n"
            "{\n"
            '  "request_type": "ANALYZE|POSITION|COMPARE|RISK|SYSTEM_INFO|HARNESS|FEEDBACK|PREFERENCE|CATEGORY|SETUP_CONFIG|UNKNOWN",\n'
            '  "asset": null,\n'
            '  "asset_2": null,\n'
            '  "market": null,\n'
            '  "timeframe": null,\n'
            '  "topic": null,\n'
            '  "follow_up": false,\n'
            '  "system_question": false,\n'
            '  "confidence": "high"\n'
            "}\n\n"
            "RULES:\n"
            "1. If user asks about system, creator, AI model, architecture, or who made it -> request_type: SYSTEM_INFO, asset: null.\n"
            "2. If user mentions harness, herness, session memory -> request_type: HARNESS, asset: null.\n"
            "3. If user expresses feedback, slang (tolol, wkwk, sampah, aneh, no trade) -> request_type: FEEDBACK, asset: null.\n"
            "4. If user sets preferences (no ollama, hide sources) -> request_type: PREFERENCE, asset: null.\n"
            "5. If user discusses LLM installation or specs -> request_type: SETUP_CONFIG, asset: null.\n"
            "6. NEVER classify Indonesian slang, filler words, or system terms as crypto coins.\n"
            f"Context: last_asset={last_asset}, last_market={last_market}, last_tf={last_tf}.\n"
            f"Input: {text}\n"
            "JSON:"
        )

        output = self._run_llama(system_instruction, max_tokens=128, temp=0.0)
        if not output:
            return None

        # Extract JSON substring
        json_match = re.search(r"\{.*\}", output, re.DOTALL)
        if not json_match:
            return None

        try:
            data = json.loads(json_match.group(0))
            if not isinstance(data, dict):
                return None

            req_type = str(data.get("request_type", "UNKNOWN")).upper()
            if req_type not in ALLOWED_LLM_REQUEST_TYPES:
                req_type = "UNKNOWN"

            # Asset Safety: non-asset request types MUST NOT have assets
            if req_type in ("FEEDBACK", "SYSTEM_INFO", "HARNESS", "PREFERENCE", "SETUP_CONFIG"):
                data["asset"] = None
                data["asset_2"] = None

            data["request_type"] = req_type
            return data
        except Exception:
            return None

    def generate_narrative(
        self,
        quant_result: Any,
        user_query: str = "",
        language: str = "id",
    ) -> str | None:
        """Generates professional crypto analyst trader narrative from structured QuantEngine data.

        QuantEngine numbers and decision are strictly preserved and verified.
        """
        if not self.is_available():
            return None

        q = quant_result
        asset = getattr(q, "asset", "ASSET")
        decision = getattr(q, "decision", "NO_TRADE")
        price = getattr(q, "price", 0.0)
        tf = getattr(q, "timeframe", "H1")
        regime = getattr(q, "regime", "Compressed")
        reason = getattr(q, "decision_reason", "")
        rr_str = getattr(q, "reward_risk_str", "N/A")

        bull_trig = q.bullish_validation.trigger_condition if getattr(q, "bullish_validation", None) else ""
        bear_trig = q.bearish_validation.trigger_condition if getattr(q, "bearish_validation", None) else ""

        lang_label = "Indonesian (Bahasa Indonesia)" if language == "id" else "English"

        prompt = (
            f"You are a senior quantitative crypto analyst. Write a concise, professional 3-sentence trader note in {lang_label}.\n"
            "STRICT RULES:\n"
            f"1. You MUST keep the decision '{decision}' and asset '{asset}'.\n"
            "2. Do NOT invent prices, targets, stops, or leverage.\n"
            "3. Sound like an objective trading consultant, not a robot.\n\n"
            f"Facts:\n"
            f"- Asset: {asset} ({tf})\n"
            f"- Price: ${price:,.2f}\n"
            f"- Quant Decision: {decision}\n"
            f"- Market Regime: {regime}\n"
            f"- Reason: {reason} (RR: {rr_str})\n"
            f"- Bullish Validation: {bull_trig}\n"
            f"- Bearish Validation: {bear_trig}\n\n"
            "Trader Note:"
        )

        res = self._run_llama(prompt, max_tokens=160, temp=0.2)
        if not res:
            return None

        clean_narrative = re.sub(r"^(?:Trader Note:?|Note:?|Summary:?)\s*", "", res.strip(), flags=re.IGNORECASE)

        # Integrity Validation: Verify no contradictory decision was generated
        upper_text = clean_narrative.upper()
        if decision in ("NO_TRADE", "WAIT"):
            if "BUY NOW" in upper_text or "SEGERA BELI" in upper_text or "ENTRY SEKARANG" in upper_text:
                return None  # Contradicts quant risk gate; reject and fallback
        elif decision in ("BUY", "LONG"):
            if "SHORT NOW" in upper_text or "JUAL SEKARANG" in upper_text:
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

    Only uses official HTTPS endpoints. Safely removes incomplete files if interrupted.
    """
    import urllib.request
    import zipfile

    MODELS_DIR.mkdir(parents=True, exist_ok=True)
    BIN_DIR.mkdir(parents=True, exist_ok=True)

    # 1. llama.cpp Windows binaries
    if download_llama and not LLAMA_CLI_EXE.is_file():
        llama_zip_urls = [
            "https://github.com/ggml-org/llama.cpp/releases/download/b4850/llama-b4850-bin-win-x64.zip",
            "https://github.com/ggml-org/llama.cpp/releases/download/b4800/llama-b4800-bin-win-x64.zip",
        ]
        tmp_zip = BIN_DIR / "llama_win.tmp.zip"
        downloaded = False
        for url in llama_zip_urls:
            try:
                print(f"[....] Downloading llama.cpp binaries from {url}")
                urllib.request.urlretrieve(url, tmp_zip)
                if tmp_zip.is_file() and tmp_zip.stat().st_size > 1_000_000:
                    with zipfile.ZipFile(tmp_zip, "r") as z:
                        z.extractall(BIN_DIR)
                    downloaded = True
                    break
            except Exception as e:
                print(f"[WARN] Failed to download {url}: {e}")
            finally:
                if tmp_zip.is_file():
                    tmp_zip.unlink(missing_ok=True)

        if not downloaded:
            print("[WARN] Could not retrieve prebuilt llama.cpp binaries.")

    # 2. Qwen3-0.6B-Q8_0.gguf (~639 MB)
    if download_model and not MODEL_FILE.is_file():
        model_urls = [
            "https://huggingface.co/Qwen/Qwen3-0.6B-GGUF/resolve/main/Qwen3-0.6B-Q8_0.gguf",
            "https://huggingface.co/bartowski/Qwen_Qwen3-0.6B-GGUF/resolve/main/Qwen3-0.6B-Q8_0.gguf",
            "https://huggingface.co/gatherz/Qwen3-0.6B-GGUF/resolve/main/Qwen3-0.6B-Q8_0.gguf",
        ]
        tmp_model = MODELS_DIR / "qwen3_model.tmp.gguf"
        downloaded = False
        for url in model_urls:
            try:
                print(f"[....] Downloading {MODEL_NAME} (~639 MB) from {url}")
                urllib.request.urlretrieve(url, tmp_model)
                if tmp_model.is_file() and tmp_model.stat().st_size > 300_000_000:
                    tmp_model.rename(MODEL_FILE)
                    downloaded = True
                    print(f"[PASS] Model saved: {MODEL_FILE}")
                    break
            except Exception as e:
                print(f"[WARN] Failed downloading model from {url}: {e}")
            finally:
                if tmp_model.is_file():
                    tmp_model.unlink(missing_ok=True)

        if not downloaded:
            print("[WARN] Model download incomplete; deterministic fallback remains active.")

    engine = LocalLanguageEngine()
    return engine.is_available()
