"""OpenBagus Natural-Language Intent Router.

Converts user text into structured quantitative research requests using a fast
deterministic keyword/pattern parser first, with optional fallback to a tiny local
instruct model when configured.
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from openbagus.core.env import get_repo_root
from openbagus.domains.crypto.catalog import CryptoAssetCatalog


@dataclass
class IntentRequest:
    intent: str  # "analyze", "setup", "risk", "structure", "compare", "discover", "unknown"
    asset: str | None = None
    target_assets: list[str] = field(default_factory=list)
    focus: str = "general"  # "general", "setup", "risk", "structure", "trend", "compare"
    horizon: str | None = None
    raw_query: str = ""
    is_ambiguous: bool = False
    candidates: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class IntentRouter:
    """Routes natural language queries to structured crypto research requests."""

    def __init__(self, catalog: CryptoAssetCatalog | None = None, repo_root: Path | None = None) -> None:
        self.root = repo_root or get_repo_root()
        self.catalog = catalog or CryptoAssetCatalog(self.root)
        self.models_dir = self.root / "runtime/models"

    def parse(self, text: str) -> IntentRequest:
        cleaned = text.strip()
        if not cleaned:
            return IntentRequest(intent="unknown", raw_query=text)

        # 1. Deterministic Fast Path First
        req = self._parse_deterministic(cleaned)
        if req and req.intent != "unknown" and (req.asset or req.target_assets):
            return req

        # 2. Ambiguity resolution on candidates
        if req and req.is_ambiguous:
            return req

        # 3. Optional Local LLM Fallback (only if model installed and deterministic is ambiguous)
        if self._has_local_model():
            llm_req = self._parse_with_local_llm(cleaned)
            if llm_req and llm_req.intent != "unknown":
                return llm_req

        # 4. Fallback: treat any unparsed word matching a coin as analyze
        stop_words = {
            "what", "do", "you", "think", "about", "analyse", "analyze", "review",
            "open", "position", "setup", "enter", "entry", "is", "attractive", "now",
            "support", "resistance", "and", "the", "for", "of", "risk", "trend",
            "on", "view", "how", "looks", "levels", "structure", "in", "a", "not",
            "command", "to", "at", "it", "or", "by", "from", "help",
        }
        words = re.findall(r"\b[A-Za-z0-9]+\b", cleaned)
        for w in words:
            if len(w) < 2 or w.lower() in stop_words:
                continue
            asset, amb = self.catalog.resolve_asset(w)
            if asset:
                return IntentRequest(
                    intent="analyze",
                    asset=asset.symbol,
                    target_assets=[asset.symbol],
                    focus="general",
                    raw_query=text,
                )
            if amb:
                return IntentRequest(
                    intent="analyze",
                    is_ambiguous=True,
                    candidates=[a.symbol for a in amb],
                    raw_query=text,
                )

        return IntentRequest(intent="unknown", raw_query=text)

    def _parse_deterministic(self, text: str) -> IntentRequest | None:
        lower = text.lower().strip()

        # Check for comparison: "BTC vs ETH", "compare BTC and ETH"
        vs_match = re.search(r"\b([a-zA-Z0-9]+)\s+(?:vs|versus|and|with)\s+([a-zA-Z0-9]+)\b", text, re.IGNORECASE)
        if vs_match or "compare" in lower:
            coins = []
            if vs_match:
                c1, c2 = vs_match.group(1), vs_match.group(2)
                for c in (c1, c2):
                    a, _ = self.catalog.resolve_asset(c)
                    if a:
                        coins.append(a.symbol)
            if len(coins) >= 2:
                return IntentRequest(
                    intent="compare",
                    asset=coins[0],
                    target_assets=coins[:2],
                    focus="compare",
                    raw_query=text,
                )

        # Detect intent and focus keywords
        intent = "analyze"
        focus = "general"

        if re.search(r"\b(open\s+position|setup|enter|entry|trade|trade\s+setup|attractive|buy\s+zone)\b", lower):
            intent = "setup"
            focus = "setup"
        elif re.search(r"\b(risk|drawdown|var|volatility|liquidation|downside)\b", lower):
            intent = "risk"
            focus = "risk"
        elif re.search(r"\b(support|resistance|structure|levels|pivot|orderbook)\b", lower):
            intent = "structure"
            focus = "structure"
        elif re.search(r"\b(trend|momentum|direction|bullish|bearish)\b", lower):
            intent = "analyze"
            focus = "trend"
        elif re.search(r"\b(analyse|analyze|review|opinion|think\s+about|view\s+on)\b", lower):
            intent = "analyze"
            focus = "general"

        # Extract coin symbol/name
        # Remove known action words to isolate asset
        stop_words = {
            "what", "do", "you", "think", "about", "analyse", "analyze", "review",
            "open", "position", "setup", "enter", "entry", "is", "attractive", "now",
            "support", "resistance", "and", "the", "for", "of", "risk", "trend",
            "on", "view", "how", "looks", "levels", "structure", "in", "a",
        }
        tokens = [w for w in re.findall(r"\b[A-Za-z0-9]+\b", text) if w.lower() not in stop_words]

        # Try to resolve token as asset
        for t in tokens:
            asset, amb = self.catalog.resolve_asset(t)
            if asset:
                return IntentRequest(
                    intent=intent,
                    asset=asset.symbol,
                    target_assets=[asset.symbol],
                    focus=focus,
                    raw_query=text,
                )
            if amb:
                return IntentRequest(
                    intent=intent,
                    is_ambiguous=True,
                    candidates=[a.symbol for a in amb],
                    focus=focus,
                    raw_query=text,
                )

        # Check full text as potential symbol/name
        asset, amb = self.catalog.resolve_asset(text)
        if asset:
            return IntentRequest(
                intent="analyze",
                asset=asset.symbol,
                target_assets=[asset.symbol],
                focus="general",
                raw_query=text,
            )
        if amb:
            return IntentRequest(
                intent="analyze",
                is_ambiguous=True,
                candidates=[a.symbol for a in amb],
                raw_query=text,
            )

        return None

    def _has_local_model(self) -> bool:
        if not self.models_dir.exists():
            return False
        for f in self.models_dir.glob("*.gguf"):
            return True
        return False

    def _parse_with_local_llm(self, text: str) -> IntentRequest | None:
        """Optional local LLM inference via llama.cpp or llama-cpp-python if installed."""
        try:
            # Check for llama-cpp-python
            import llama_cpp  # type: ignore

            model_files = list(self.models_dir.glob("*.gguf"))
            if not model_files:
                return None

            model_path = str(model_files[0])
            llm = llama_cpp.Llama(model_path=model_path, n_ctx=256, verbose=False)
            prompt = (
                f"<|im_start|>system\nYou extract crypto asset and intent into JSON with keys: "
                f"intent (analyze, setup, risk, structure, compare), asset (symbol).<|im_end|>\n"
                f"<|im_start|>user\n{text}<|im_end|>\n"
                f"<|im_start|>assistant\n{{"
            )
            output = llm(prompt, max_tokens=64, stop=["<|im_end|>", "\n\n"])
            raw_json = "{" + output["choices"][0]["text"].strip()
            data = json.loads(raw_json)
            asset_sym = data.get("asset")
            if asset_sym:
                asset_obj, _ = self.catalog.resolve_asset(asset_sym)
                sym = asset_obj.symbol if asset_obj else asset_sym.upper()
                return IntentRequest(
                    intent=data.get("intent", "analyze"),
                    asset=sym,
                    target_assets=[sym],
                    focus=data.get("intent", "general"),
                    raw_query=text,
                )
        except Exception:
            return None
        return None
