"""Speech text normalizer converting written analysis into natural spoken Indonesian prose."""

from __future__ import annotations

import re


def int_to_indonesian_words(n: int) -> str:
    """Converts non-negative integer into natural Indonesian words."""
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

        # Standard punctuated numbers: Rp 1.250.000 or Rp1,250,000
        def _repl_num(m: re.Match) -> str:
            raw = m.group(1).replace(".", "").replace(",", "")
            try:
                val = int(raw)
                return int_to_indonesian_words(val) + " rupiah"
            except ValueError:
                return m.group(0)

        text = re.sub(r"\bRp\s*(\d{1,3}(?:[.,]\d{3})+)\b", _repl_num, text)
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
        """Spaces out tickers and acronyms for natural phonetic articulation in TTS."""
        acronyms = ["PER", "PBV", "ROE", "ROIC", "DER", "FCF", "DCF", "EBITDA", "WACC", "ARA", "ARB", "ADTV", "FCA"]
        for acr in acronyms:
            # Add spaces between letters for acronyms: PER -> P E R
            spaced = " ".join(acr)
            text = re.sub(rf"\b{acr}\b", spaced, text)

        # Common 4-letter tickers spelled clearly: BBCA -> B B C A
        common_tickers = ["BBCA", "BBRI", "BMRI", "BBNI", "TLKM", "ASII", "ANTM", "ISAT", "HGII", "YOII"]
        for t in common_tickers:
            spaced = " ".join(t)
            text = re.sub(rf"\b{t}\b", spaced, text)

        # Multiples notation: 15x -> 15 kali
        text = re.sub(r"\b(\d+(?:[.,]\d+)?)[xX]\b", r"\1 kali", text)
        return text

    @classmethod
    def to_spoken_text(cls, written_text: str) -> str:
        """Full pipeline generating clean, articulate spoken Indonesian prose."""
        clean = cls.clean_markdown(written_text)
        clean = cls.normalize_quarters_and_years(clean)
        clean = cls.normalize_currencies(clean)
        clean = cls.normalize_percentages(clean)
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
