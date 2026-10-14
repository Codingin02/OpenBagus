"""Speech text normalizer converting written analysis into natural spoken Indonesian prose.

Handles:
- Indonesian integer and decimal verbalization
- Rupiah currency denominations (ribu, juta, miliar, triliun)
- Percentage pronunciation with sign and decimals
- Financial multipliers and ratios (PER, PBV, ROE, DCF, WACC, etc.)
- 951+ IDX stock ticker phonetic articulation (e.g., BBCA -> B B C A)
- Markdown, LaTeX, and table stripping for TTS fluency
"""

from __future__ import annotations

import re


def int_to_indonesian_words(n: int) -> str:
    """Converts non-negative or negative integer into natural Indonesian words."""
    if n == 0:
        return "nol"
    if n < 0:
        return "minus " + int_to_indonesian_words(-n)

    satuan = ["", "satu", "dua", "tiga", "empat", "lima", "enam", "tujuh", "delapan", "sembilan", "sepuluh", "sebelas"]
    if n < 12:
        return satuan[n]
    if n < 20:
        return satuan[n - 10] + " belas"
    if n < 100:
        return satuan[n // 10] + " puluh" + ("" if n % 10 == 0 else " " + int_to_indonesian_words(n % 10))
    if n < 200:
        return "seratus" + ("" if n % 100 == 0 else " " + int_to_indonesian_words(n % 100))
    if n < 1000:
        return satuan[n // 100] + " ratus" + ("" if n % 100 == 0 else " " + int_to_indonesian_words(n % 100))
    if n < 2000:
        return "seribu" + ("" if n % 1000 == 0 else " " + int_to_indonesian_words(n % 1000))
    if n < 1000000:
        return int_to_indonesian_words(n // 1000) + " ribu" + ("" if n % 1000 == 0 else " " + int_to_indonesian_words(n % 1000))
    if n < 1000000000:
        return int_to_indonesian_words(n // 1000000) + " juta" + ("" if n % 1000000 == 0 else " " + int_to_indonesian_words(n % 1000000))
    if n < 1000000000000:
        return int_to_indonesian_words(n // 1000000000) + " miliar" + ("" if n % 1000000000 == 0 else " " + int_to_indonesian_words(n % 1000000000))
    return int_to_indonesian_words(n // 1000000000000) + " triliun" + ("" if n % 1000000000000 == 0 else " " + int_to_indonesian_words(n % 1000000000000))


# Common non-ticker 4-letter words to preserve as whole words
NON_TICKER_EXCLUSIONS = {
    "DATA", "FAST", "DEEP", "TRUE", "FAIL", "NULL", "STOP", "POST", "FILE", "READ",
    "USER", "TIME", "TEST", "OPEN", "BASE", "CUDA", "ONNX", "AUTO", "HIGH", "LOWS",
    "PEAK", "COST", "RATE", "CASH", "FLOW", "DEBT", "RISK", "CALL", "TERM", "BOND",
    "FREE", "FULL", "HALF", "LONG", "UNIT", "TEXT", "LINE", "VIEW", "SHOW", "INFO",
    "HELP", "CODE", "MODE", "TASK", "WORK", "STEP", "PASS", "NONE", "WARN", "DROP",
    "HOLD", "SELL", "BUY",  "LIVE", "JSON", "HTTP", "REST", "PORT", "HOST", "PATH",
}


class SpeechTextNormalizer:
    """Normalizes written financial output into articulate, natural Indonesian speech."""

    @classmethod
    def clean_markdown(cls, text: str) -> str:
        """Removes code blocks, tables, links, LaTeX, and symbols unsuited for TTS."""
        t = text
        # Remove code blocks
        t = re.sub(r"```[\s\S]*?```", "", t)
        # Remove LaTeX display and inline equations
        t = re.sub(r"\$\$[\s\S]*?\$\$", "", t)
        t = re.sub(r"\\\[[\s\S]*?\\\]", "", t)
        t = re.sub(r"\\\([\s\S]*?\\\)", "", t)
        t = re.sub(r"\$[^\$\n]+?\$", "", t)
        t = t.replace("$", " ")
        # Remove markdown tables (| header | header | ...)
        t = re.sub(r"(?:^|\n)\|.*?\|(?:\n|$)", "\n", t)
        t = re.sub(r"(?:^|\n)\|[-:\s|]+\|(?:\n|$)", "\n", t)
        # Remove markdown links [title](url) -> title
        t = re.sub(r"\[([^\]]+)\]\([^\)]+\)", r"\1", t)
        # Remove markdown formatting bold/italic/headers/quotes
        t = re.sub(r"[*_~`#>]", " ", t)
        # Remove bullet markers (- item or * item)
        t = re.sub(r"(?:^|\n)\s*[-*+]\s+", "\n", t)
        # Clean extra whitespace
        t = re.sub(r"[ \t]+", " ", t)
        return t.strip()

    @classmethod
    def normalize_currencies(cls, text: str) -> str:
        """Converts Rupiah amounts like Rp1.250.000 or Rp 50T to Indonesian words."""
        # Triliun abbreviation: Rp 50T or Rp 50 Triliun
        text = re.sub(r"\bRp\s*(\d+(?:[.,]\d+)?)\s*(?:T|Triliun)\b", r"\1 triliun rupiah", text, flags=re.I)
        # Miliar abbreviation: Rp 100M or Rp 100 Miliar
        text = re.sub(r"\bRp\s*(\d+(?:[.,]\d+)?)\s*(?:M|Miliar|Milyar)\b", r"\1 miliar rupiah", text, flags=re.I)
        # Juta abbreviation: Rp 500 Juta
        text = re.sub(r"\bRp\s*(\d+(?:[.,]\d+)?)\s*(?:Juta)\b", r"\1 juta rupiah", text, flags=re.I)

        # Standard punctuated numbers: Rp 1.250.000 or Rp1,250,000 or Rp9.500
        def _repl_num(m: re.Match) -> str:
            raw = m.group(1).replace(".", "").replace(",", "")
            try:
                val = int(raw)
                return int_to_indonesian_words(val) + " rupiah"
            except ValueError:
                return m.group(0)

        # Match Rp followed by punctuated numbers with thousands separators
        text = re.sub(r"\bRp\s*(\d{1,3}(?:[.,]\d{3})+)\b", _repl_num, text)
        # Also match unpunctuated Rp amounts: Rp 50000 -> lima puluh ribu rupiah
        text = re.sub(r"\bRp\s*(\d{3,})\b", _repl_num, text)
        return text

    @classmethod
    def normalize_percentages(cls, text: str) -> str:
        """Converts percentage figures like 12,5% or -3.4% or 5% into spoken Indonesian words."""
        def _repl_pct(m: re.Match) -> str:
            sign = "minus " if m.group(1) else ""
            int_part = m.group(2)
            dec_part = m.group(3)
            if dec_part:
                dec_words = " koma " + " ".join(int_to_indonesian_words(int(d)) for d in dec_part)
            else:
                dec_words = ""
            return f"{sign}{int_to_indonesian_words(int(int_part))}{dec_words} persen"

        return re.sub(r"(-)?(\d+)(?:[.,](\d+))?%", _repl_pct, text)

    @classmethod
    def normalize_multipliers_and_decimals(cls, text: str) -> str:
        """Converts multiplier notations like 15.5x, 2x, and standalone decimal numbers."""
        # Multipliers: 15.5x or 15x -> lima belas koma lima kali / 15 kali
        def _repl_mult(m: re.Match) -> str:
            sign = "minus " if m.group(1) else ""
            int_p = m.group(2)
            dec_p = m.group(3)
            if dec_p:
                dec_words = " koma " + " ".join(int_to_indonesian_words(int(d)) for d in dec_p)
            else:
                dec_words = ""
            return f"{sign}{int_to_indonesian_words(int(int_p))}{dec_words} kali"

        text = re.sub(r"(-)?(\d+)(?:[.,](\d+))?[xX]\b", _repl_mult, text)
        return text

    @classmethod
    def normalize_quarters_and_years(cls, text: str) -> str:
        """Converts financial period notation: 2024-FY, 2025-Q3, etc."""
        text = re.sub(r"\b(\d{4})-FY\b", r"tahun penuh \1", text, flags=re.I)
        text = re.sub(r"\b(\d{4})-Q1\b", r"kuartal satu \1", text, flags=re.I)
        text = re.sub(r"\b(\d{4})-Q2\b", r"kuartal dua \1", text, flags=re.I)
        text = re.sub(r"\b(\d{4})-Q3\b", r"kuartal tiga \1", text, flags=re.I)
        text = re.sub(r"\b(\d{4})-Q4\b", r"kuartal empat \1", text, flags=re.I)
        return text

    @classmethod
    def normalize_tickers_and_ratios(cls, text: str) -> str:
        """Phonetically spaces out tickers and acronyms for natural articulation in TTS."""
        # Special Indonesian and institutional financial acronyms
        specials = {
            r"\bLQ45\b": "L Q empat puluh lima",
            r"\bIHSG\b": "I H S G",
            r"\bIDX\b": "I D X",
            r"\bBEI\b": "B E I",
            r"\bOJK\b": "O J K",
            r"\bBI\b": "B I",
            r"\bFED\b": "F E D",
            r"\bFOMC\b": "F O M C",
        }
        for pat, repl in specials.items():
            text = re.sub(pat, repl, text, flags=re.I)

        # Standard financial ratios and indicators
        acronyms = [
            "PER", "PBV", "ROE", "ROA", "ROIC", "DER", "EPS", "FCF", "DCF",
            "EBITDA", "WACC", "ARA", "ARB", "ADTV", "FCA", "CAGR", "RSI",
            "MACD", "ATR", "EMA", "SMA", "CAGR", "VaR"
        ]
        for acr in acronyms:
            spaced = " ".join(acr.upper())
            text = re.sub(rf"\b{acr}\b", spaced, text, flags=re.IGNORECASE if len(acr) <= 4 else 0)

        # 4-Letter IDX tickers: spell out letter by letter (e.g. BBCA -> B B C A, GOTO -> G O T O)
        def _repl_ticker(m: re.Match) -> str:
            w = m.group(1)
            if w in NON_TICKER_EXCLUSIONS:
                return w
            return " ".join(w)

        text = re.sub(r"\b([A-Z]{4})\b", _repl_ticker, text)
        return text

    @classmethod
    def to_spoken_text(cls, written_text: str) -> str:
        """Full pipeline generating clean, articulate spoken Indonesian prose."""
        clean = cls.clean_markdown(written_text)
        clean = cls.normalize_quarters_and_years(clean)
        clean = cls.normalize_currencies(clean)
        clean = cls.normalize_percentages(clean)
        clean = cls.normalize_multipliers_and_decimals(clean)
        clean = cls.normalize_tickers_and_ratios(clean)
        # Collapse whitespace and newlines into natural pauses
        clean = re.sub(r"\n+", ". ", clean)
        clean = re.sub(r"\s+", " ", clean).strip()
        return clean

    @classmethod
    def split_sentences(cls, spoken_text: str) -> list[str]:
        """Splits spoken text into coherent sentences for incremental TTS streaming."""
        raw_sentences = re.split(r"(?<=[.!?])\s+", spoken_text)
        sentences = [s.strip() for s in raw_sentences if s.strip() and len(s.strip()) > 1]
        return sentences
