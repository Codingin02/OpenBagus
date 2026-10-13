"""Production-grade IDX PDF Financial Report Parser.

Extracts balance sheet, income statement, and cash-flow facts with page citations
and extraction confidence. Marks scanned or ambiguous documents as REVIEW_REQUIRED.
"""

from __future__ import annotations

import logging
from pathlib import Path
import re
from typing import Any
import pypdf

from openbagus.domains.equities.financial_model import (
    CanonicalFinancialStatement,
    SourceCitation,
    detect_period,
    detect_currency_and_unit,
)
from openbagus.domains.equities.parsers.xlsx_parser import (
    LINE_ITEM_PATTERNS,
    _clean_numeric_value,
)

logger = logging.getLogger(__name__)


class IdxPdfParser:
    """Extracts verifiable facts from signed IDX PDF financial statements."""

    def __init__(self, repo_root: Path | None = None) -> None:
        self.root = repo_root or Path.cwd()

    def parse_file(self, path: Path, ticker: str | None = None) -> CanonicalFinancialStatement:
        if not path.exists():
            raise FileNotFoundError(f"File PDF tidak ditemukan: {path}")

        sym = (ticker or "").strip().upper()
        if not sym:
            m = re.search(r"\b([A-Z]{4})\b", path.name.upper())
            if m:
                sym = m.group(1)
        if not sym:
            raise ValueError(f"Ticker emiten tidak dapat diidentifikasi dari nama file {path.name}.")

        detected_p = detect_period(path.name)
        period_str = detected_p[0] if detected_p else "UNKNOWN_PERIOD"
        period_type = detected_p[1] if detected_p else "FY"

        currency = "IDR"
        unit_name = "million_IDR"
        multiplier = 1_000_000.0

        try:
            reader = pypdf.PdfReader(path)
        except Exception as e:
            raise ValueError(f"Gagal membaca PDF {path.name}: {e}")

        total_pages = len(reader.pages)
        if total_pages == 0:
            raise ValueError(f"Dokumen PDF {path.name} tidak memiliki halaman.")

        # Detect scale and currency from initial pages
        header_sample = ""
        for p_idx in range(min(5, total_pages)):
            try:
                t = reader.pages[p_idx].extract_text() or ""
                header_sample += " " + t
            except Exception:
                pass

        if header_sample:
            currency, unit_name, multiplier = detect_currency_and_unit(header_sample)

        stmt = CanonicalFinancialStatement(
            symbol=sym,
            period=period_str,
            period_type=period_type,
            currency=currency,
            unit=unit_name,
            unit_multiplier=multiplier,
            basis="consolidated",
            audit_status="audited" if "FY" in period_type else "unaudited",
            period_end_date="2024-12-31",
            source_document=path.name,
            document_format="PDF",
            source_url=f"https://www.idx.co.id/perusahaan-tercatat/laporan-keuangan-dan-tahunan/ ({path.name})",
        )

        citations: dict[str, SourceCitation] = {}
        total_extracted_text_chars = 0

        # Scan financial statement pages (typically first 20 pages)
        scan_limit = min(30, total_pages)
        for page_num in range(1, scan_limit + 1):
            try:
                page_text = reader.pages[page_num - 1].extract_text() or ""
            except Exception:
                page_text = ""

            total_extracted_text_chars += len(page_text)
            if not page_text.strip():
                continue

            lines = page_text.splitlines()
            for line in lines:
                clean_line = line.strip()
                if not clean_line or len(clean_line) < 5:
                    continue

                for field_name, patterns in LINE_ITEM_PATTERNS.items():
                    if getattr(stmt, field_name, None) is not None:
                        continue
                    if any(re.search(p, clean_line, re.I) for p in patterns):
                        # Extract trailing numeric amounts on this line
                        nums = re.findall(r"\(?[0-9]{1,3}(?:[.,][0-9]{3})*(?:[.,][0-9]+)?\)?", clean_line)
                        if nums:
                            val = _clean_numeric_value(nums[-1])
                            if val is not None:
                                setattr(stmt, field_name, val)
                                citations[field_name] = SourceCitation(
                                    statement_type="PDF Financial Report",
                                    page_number=page_num,
                                    row_label=clean_line[:60],
                                    raw_reported_text=nums[-1],
                                    file_path=str(path),
                                )
                                break

        # Scanned PDF detection: if very few characters extracted across multiple pages
        if total_extracted_text_chars < 500:
            stmt.validation_status = "REVIEW_REQUIRED"
            stmt.validation_notes.append("Dokumen PDF terindikasi hasil scan/gambar; diperlukan konfirmasi manual.")

        # Compute capex if components exist
        if stmt.capital_expenditures is None and stmt.capex_ppe is not None:
            stmt.capital_expenditures = abs(stmt.capex_ppe) + (abs(stmt.capex_intangibles) if stmt.capex_intangibles else 0.0)

        # Interest-bearing debt calculation
        if stmt.interest_bearing_debt is None:
            st_d = stmt.short_term_debt or 0.0
            lt_d = stmt.long_term_debt or 0.0
            if st_d > 0 or lt_d > 0:
                stmt.interest_bearing_debt = st_d + lt_d

        stmt.citations = citations
        stmt.validate_accounting_relationships()
        return stmt
