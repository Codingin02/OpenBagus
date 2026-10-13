"""Indonesian ASR financial normalizer for IDX tickers, ratios, numbers, and vocabulary."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any


KNOWN_IDX_TICKERS = {
    "BBCA", "BBRI", "BMRI", "BBNI", "TLKM", "ASII", "ANTM", "ISAT", "UNTR", "KLBF",
    "ADRO", "PTBA", "ICBP", "INDF", "GOTO", "BUKA", "BRIS", "AMMN", "BREN", "CUAN",
    "HGII", "YOII", "BRRC", "DGWG", "CBDK", "OBAT", "PGAS", "SMGR", "INCO", "MDKA",
}

FINANCIAL_ACRONYMS = {
    "P E R": "PER",
    "PE RATIO": "PER",
    "PRICE EARNING RATIO": "PER",
    "P B V": "PBV",
    "PRICE TO BOOK": "PBV",
    "R O E": "ROE",
    "R O I C": "ROIC",
    "D E R": "DER",
    "DEBT TO EQUITY": "DER",
    "F C F": "FCF",
    "D C F": "DCF",
    "EBITDA": "EBITDA",
    "E BIT DA": "EBITDA",
    "WACC": "WACC",
    "W A C C": "WACC",
    "A R A": "ARA",
    "A R B": "ARB",
    "F C A": "FCA",
    "A D T V": "ADTV",
    "V C P": "VCP",
    "P A M": "PAM",
    "R S I": "RSI",
    "A T R": "ATR",
    "V A R": "VaR",
    "E P S": "EPS",
}

NUMBER_WORDS = {
    "nol": 0, "satu": 1, "dua": 2, "tiga": 3, "empat": 4, "lima": 5,
    "enam": 6, "tujuh": 7, "delapan": 8, "sembilan": 9, "sepuluh": 10,
    "sebelas": 11, "belas": 10, "puluh": 10, "ratus": 100, "ribu": 1000,
    "juta": 1000000, "miliar": 1000000000, "triliun": 1000000000000,
}


def parse_indonesian_number_phrase(phrase: str) -> int | None:
    words = phrase.strip().lower().split()
    values = {
        "nol": 0, "satu": 1, "se": 1, "dua": 2, "tiga": 3, "empat": 4, "lima": 5,
        "enam": 6, "tujuh": 7, "delapan": 8, "sembilan": 9, "sepuluh": 10,
        "sebelas": 11, "seratus": 100, "seribu": 1000,
    }
    units = {
        "belas": 10, "puluh": 10, "ratus": 100,
    }
    scales = {
        "ribu": 1000, "juta": 1000000, "miliar": 1000000000, "milyar": 1000000000, "triliun": 1000000000000,
    }
    valid = set(values.keys()) | set(units.keys()) | set(scales.keys())
    if not words or not all(w in valid for w in words):
        return None

    total = 0
    current_scale_val = 0
    current_val = 0

    for w in words:
        if w in values:
            if w == "seratus":
                current_scale_val += 100
            elif w == "seribu":
                current_scale_val += 1000
            else:
                current_val = values[w]
        elif w == "belas":
            current_scale_val += (current_val + 10)
            current_val = 0
        elif w in ("puluh", "ratus"):
            mult = units[w]
            current_scale_val += (current_val if current_val else 1) * mult
            current_val = 0
        elif w in scales:
            mult = scales[w]
            sub = current_scale_val + current_val
            total += (sub if sub else 1) * mult
            current_scale_val = 0
            current_val = 0
    total += (current_scale_val + current_val)
    return total if total > 0 else None


@dataclass
class NormalizedASRResult:
    raw_transcript: str = ""
    normalized_text: str = ""
    detected_tickers: list[str] = None
    detected_strategy: str | None = None
    detected_horizon: str | None = None
    detected_metrics: list[str] = None
    is_ambiguous: bool = False
    ambiguity_reason: str = ""

    def __init__(
        self,
        raw_transcript: str = "",
        normalized_text: str = "",
        detected_tickers: list[str] | None = None,
        detected_strategy: str | None = None,
        detected_horizon: str | None = None,
        detected_metrics: list[str] | None = None,
        is_ambiguous: bool = False,
        ambiguity_reason: str = "",
        raw_text: str | None = None,
        detected_ratios: list[str] | None = None,
        detected_timeframe: str | None = None,
        **kwargs: Any,
    ) -> None:
        self.raw_transcript = raw_text if raw_text is not None else raw_transcript
        self.normalized_text = normalized_text
        self.detected_tickers = detected_tickers if detected_tickers is not None else []
        self.detected_strategy = detected_strategy
        self.detected_horizon = detected_horizon or detected_timeframe
        self.detected_metrics = detected_metrics if detected_metrics is not None else (detected_ratios or [])
        self.is_ambiguous = is_ambiguous
        self.ambiguity_reason = ambiguity_reason

    @property
    def raw_text(self) -> str:
        return self.raw_transcript

    def to_dict(self) -> dict[str, Any]:
        return {
            "raw_transcript": self.raw_transcript,
            "normalized_text": self.normalized_text,
            "detected_tickers": self.detected_tickers,
            "detected_strategy": self.detected_strategy,
            "detected_horizon": self.detected_horizon,
            "detected_metrics": self.detected_metrics,
            "is_ambiguous": self.is_ambiguous,
            "ambiguity_reason": self.ambiguity_reason,
        }


class ASRFinancialNormalizer:
    """Normalizes raw Whisper speech transcripts into clean, typed financial queries."""

    @classmethod
    def normalize(cls, raw_text: str) -> NormalizedASRResult:
        text = raw_text.strip()
        if not text:
            return NormalizedASRResult(raw_transcript="", normalized_text="", detected_tickers=[], detected_strategy=None, detected_horizon=None, detected_metrics=[])

        norm = text

        # 0. Single letters spaced or hyphenated (e.g. "b b c a", "b-b-r-i", "r s i", "d c f")
        def _repl_4_letters(m: re.Match) -> str:
            w = (m.group(1) + m.group(2) + m.group(3) + m.group(4)).upper()
            return w if w in KNOWN_IDX_TICKERS else m.group(0)

        norm = re.sub(r"\b([A-Za-z])[\s\-]+([A-Za-z])[\s\-]+([A-Za-z])[\s\-]+([A-Za-z])\b", _repl_4_letters, norm)

        def _repl_3_letters(m: re.Match) -> str:
            w = (m.group(1) + m.group(2) + m.group(3)).upper()
            mapping = {"VAR": "VaR"}
            if w in {"RSI", "ATR", "VAR", "DCF", "FCF", "ROE", "DER", "PBV", "PER", "ARA", "ARB", "FCA", "EPS", "CAR", "NIM", "NPL"}:
                return mapping.get(w, w)
            return m.group(0)

        norm = re.sub(r"\b([A-Za-z])[\s\-]+([A-Za-z])[\s\-]+([A-Za-z])\b", _repl_3_letters, norm)

        # 1. Normalize Acronyms (e.g. "p e r" -> "PER", "a r a" -> "ARA")
        for spoken, acr in FINANCIAL_ACRONYMS.items():
            pattern = re.compile(rf"\b{re.escape(spoken)}\b", re.IGNORECASE)
            norm = pattern.sub(acr, norm)

        # 2. Normalize Spoken Phonetic Tickers (e.g. "B B C A" or "be be ce a")
        ticker_phonetics = {
            r"\bbe\s*be\s*ce\s*a\b": "BBCA",
            r"\bbe\s*be\s*er\s*i\b": "BBRI",
            r"\bbe\s*em\s*er\s*i\b": "BMRI",
            r"\bbe\s*be\s*en\s*i\b": "BBNI",
            r"\bte\s*el\s*ka\s*em\b": "TLKM",
            r"\ba\s*es\s*i\s*i\b": "ASII",
            r"\bha\s*ge\s*i\s*i\b": "HGII",
            r"\bi\s*es\s*a\s*te\b": "ISAT",
            r"\ba\s*en\s*te\s*em\b": "ANTM",
        }
        for phon, tick in ticker_phonetics.items():
            norm = re.sub(phon, tick, norm, flags=re.IGNORECASE)

        # 2b. Normalize Spoken Numbers and Currencies
        # Numbers before "rupiah" -> "Rp X"
        def _repl_rp(m: re.Match) -> str:
            phrase = m.group(1)
            val = parse_indonesian_number_phrase(phrase)
            if val is not None:
                return f"Rp {val:,}".replace(",", ".")
            return m.group(0)

        norm = re.sub(r"\b((?:(?:satu|dua|tiga|empat|lima|enam|tujuh|delapan|sembilan|sepuluh|sebelas|belas|puluh|seratus|ratus|seribu|ribu|juta|miliar|triliun)\s*)+)\s+rupiah\b", _repl_rp, norm, flags=re.IGNORECASE)

        # Standalone numbers after "harga" / "level"
        def _repl_num(m: re.Match) -> str:
            prefix = m.group(1)
            phrase = m.group(2)
            val = parse_indonesian_number_phrase(phrase)
            if val is not None:
                return f"{prefix} {val}"
            return m.group(0)

        norm = re.sub(r"\b(harga|level|sebanyak)\s+((?:(?:satu|dua|tiga|empat|lima|enam|tujuh|delapan|sembilan|sepuluh|sebelas|belas|puluh|seratus|ratus|seribu|ribu|juta|miliar|triliun)\s*)+)\b", _repl_num, norm, flags=re.IGNORECASE)

        # 3. Detect known tickers
        found_tickers = []
        for word in re.findall(r"\b[A-Za-z]{4}\b", norm):
            upper_w = word.upper()
            if upper_w in KNOWN_IDX_TICKERS:
                if upper_w not in found_tickers:
                    found_tickers.append(upper_w)
                # Ensure capitalized in output
                norm = re.sub(rf"\b{word}\b", upper_w, norm)

        # 4. Normalize Trading Slang / Colloquialisms
        slang_map = {
            r"\bsuwing\b": "swing",
            r"\bbrekot\b": "breakout",
            r"\bkatlos\b": "cut loss",
            r"\btek profit\b": "take profit",
            r"\blikwid\b": "likuid",
            r"\bspekulatif\b": "spekulatif",
        }
        for sl, repl in slang_map.items():
            norm = re.sub(sl, repl, norm, flags=re.IGNORECASE)

        # 5. Extract Strategy
        strat = None
        lower_norm = norm.lower()
        if any(w in lower_norm for w in ["swing", "breakout", "momentum", "pam", "vcp"]):
            strat = "SWING"
        elif any(w in lower_norm for w in ["investasi", "jangka panjang", "dcf", "fcff", "dividen", "value"]):
            strat = "INVESTMENT"

        # 6. Extract Horizon
        horizon = None
        if re.search(r"\b(?:tiga\s*minggu|3\s*minggu)\b", lower_norm):
            horizon = "3_WEEKS"
        elif re.search(r"\b(?:dua\s*minggu|2\s*minggu)\b", lower_norm):
            horizon = "2_WEEKS"
        elif re.search(r"\b(?:satu\s*minggu|1\s*minggu)\b", lower_norm):
            horizon = "1_WEEK"
        elif re.search(r"\b(?:bulan|tahun|panjang)\b", lower_norm):
            horizon = "LONG_TERM"

        # 7. Extract Financial Metrics
        metrics = []
        for m in ["PER", "PBV", "ROE", "ROIC", "DER", "FCF", "DCF", "EBITDA", "WACC", "ARA", "ARB", "ADTV"]:
            if re.search(rf"\b{m}\b", norm, re.IGNORECASE):
                metrics.append(m)

        # Clean multiple whitespace
        norm = re.sub(r"\s+", " ", norm).strip()

        return NormalizedASRResult(
            raw_transcript=raw_text,
            normalized_text=norm,
            detected_tickers=found_tickers,
            detected_strategy=strat,
            detected_horizon=horizon,
            detected_metrics=metrics,
        )
