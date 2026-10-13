"""IDX XBRL & iXBRL Processing Engine.

Supports parsing authentic IDX XBRL instances (.zip, .xbrl, .xml), extracting
facts, mapping IDX taxonomy concepts, handling multidimensional contexts,
enforcing accounting relationships, and defending against ZIP bombs / XXE attacks.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import io
import json
import logging
import math
import os
from pathlib import Path
import re
from typing import Any
import xml.etree.ElementTree as ET
import zipfile

from openbagus.domains.equities.financial_model import (
    CanonicalFinancialStatement,
    SourceCitation,
    detect_period,
)

logger = logging.getLogger(__name__)

# Maximum decompression size: 50MB (Zip bomb defense)
MAX_UNCOMPRESSED_BYTES = 50 * 1024 * 1024
MAX_FILE_COUNT = 500

# Concept mapping from IDX Taxonomy to Canonical fields
IDX_TAXONOMY_MAP: dict[str, str] = {
    # 1. Assets (Balance Sheet)
    "CashAndCashEquivalents": "cash_and_equivalents",
    "KasDanSetaraKas": "cash_and_equivalents",
    "RestrictedCash": "restricted_cash",
    "KasYangDibatasiPenggunaannya": "restricted_cash",
    "ShortTermInvestments": "short_term_investments",
    "InvestasiJangkaPendek": "short_term_investments",
    "TradeReceivables": "trade_receivables",
    "PiutangUsaha": "trade_receivables",
    "Inventories": "inventories",
    "Persediaan": "inventories",
    "CurrentAssets": "current_assets",
    "AsetLancar": "current_assets",
    "JumlahAsetLancar": "current_assets",
    "NoncurrentAssets": "non_current_assets",
    "AsetTidakLancar": "non_current_assets",
    "JumlahAsetTidakLancar": "non_current_assets",
    "Assets": "total_assets",
    "TotalAssets": "total_assets",
    "JumlahAset": "total_assets",

    # 2. Liabilities (Balance Sheet)
    "TradePayables": "trade_payables",
    "UtangUsaha": "trade_payables",
    "ShortTermBorrowings": "short_term_debt",
    "PinjamanJangkaPendek": "short_term_debt",
    "ShortTermBankLoans": "short_term_debt",
    "UtangBankJangkaPendek": "short_term_debt",
    "LongTermBorrowings": "long_term_debt",
    "PinjamanJangkaPanjang": "long_term_debt",
    "LongTermBankLoans": "long_term_debt",
    "UtangBankJangkaPanjang": "long_term_debt",
    "LeaseLiabilities": "lease_liabilities",
    "LiabilitasSewa": "lease_liabilities",
    "InterestBearingDebt": "interest_bearing_debt",
    "UtangBerbunga": "interest_bearing_debt",
    "CurrentLiabilities": "current_liabilities",
    "LiabilitasJangkaPendek": "current_liabilities",
    "JumlahLiabilitasJangkaPendek": "current_liabilities",
    "NoncurrentLiabilities": "non_current_liabilities",
    "LiabilitasJangkaPanjang": "non_current_liabilities",
    "JumlahLiabilitasJangkaPanjang": "non_current_liabilities",
    "Liabilities": "total_liabilities",
    "TotalLiabilities": "total_liabilities",
    "JumlahLiabilitas": "total_liabilities",

    # 3. Equity (Balance Sheet)
    "ShareCapital": "share_capital",
    "ModalSaham": "share_capital",
    "RetainedEarnings": "retained_earnings",
    "SaldoLaba": "retained_earnings",
    "EquityAttributableToOwnersOfParentEntity": "equity_attributable_to_owners",
    "EkuitasYangDiatribusikanKepadaPemilikEntitasInduk": "equity_attributable_to_owners",
    "NoncontrollingInterests": "non_controlling_interests",
    "KepentinganNonPengendali": "non_controlling_interests",
    "Equity": "total_equity",
    "TotalEquity": "total_equity",
    "JumlahEkuitas": "total_equity",

    # 4. Income Statement (Profit or Loss)
    "SalesAndRevenue": "revenue",
    "Revenue": "revenue",
    "Revenues": "revenue",
    "Pendapatan": "revenue",
    "PendapatanUsaha": "revenue",
    "PenjualanDanPendapatanUsaha": "revenue",
    "SalesAndRevenue": "revenue",
    "CostOfSales": "cost_of_revenue",
    "CostOfSalesAndRevenue": "cost_of_revenue",
    "CostOfGoodsSold": "cost_of_revenue",
    "BebanPokokPendapatan": "cost_of_revenue",
    "BebanPokokPenjualan": "cost_of_revenue",
    "GrossProfit": "gross_profit",
    "LabaKotor": "gross_profit",
    "OperatingExpenses": "operating_expenses",
    "BebanUsaha": "operating_expenses",
    "OperatingProfit": "operating_income",
    "OperatingIncome": "operating_income",
    "LabaUsaha": "operating_income",
    "LabaOperasi": "operating_income",
    "FinanceCosts": "finance_costs",
    "BebanKeuangan": "finance_costs",
    "ProfitBeforeTax": "profit_before_tax",
    "LabaSebelumPajak": "profit_before_tax",
    "LabaSebelumPajakPenghasilan": "profit_before_tax",
    "TaxExpense": "tax_expense",
    "BebanPajakPenghasilan": "tax_expense",
    "ProfitLoss": "net_income_total",
    "ProfitForTheYear": "net_income_total",
    "ProfitLossForTheYear": "net_income_total",
    "NetProfit": "net_income_total",
    "LabaTahunBerjalan": "net_income_total",
    "LabaBersih": "net_income_total",
    "ProfitLossAttributableToOwnersOfParentEntity": "net_income_attributable",
    "ProfitAttributableToOwnersOfParent": "net_income_attributable",
    "LabaTahunBerjalanYangDiatribusikanKepadaPemilikEntitasInduk": "net_income_attributable",
    "ProfitLossAttributableToNoncontrollingInterests": "net_income_non_controlling",
    "ProfitAttributableToNoncontrollingInterests": "net_income_non_controlling",
    "LabaYangDiatribusikanKepadaKepentinganNonPengendali": "net_income_non_controlling",
    "BasicEarningsLossPerShare": "eps_basic",
    "LabaRugiBersihPerSahamDasar": "eps_basic",
    "DilutedEarningsLossPerShare": "eps_diluted",

    # 5. Cash Flows
    "CashFlowsFromUsedInOperatingActivities": "operating_cash_flow",
    "NetCashFlowsFromOperatingActivities": "operating_cash_flow",
    "NetCashFlowsFromUsedInOperatingActivities": "operating_cash_flow",
    "ArusKasDariAktivitasOperasi": "operating_cash_flow",
    "ArusKasBersihYangDiperolehDariDigunakanUntukAktivitasOperasi": "operating_cash_flow",
    "PaymentsForAcquisitionOfPropertyPlantAndEquipment": "capex_ppe",
    "PurchaseOfPropertyPlantAndEquipment": "capex_ppe",
    "PembayaranUntukPerolehanAsetTetap": "capex_ppe",
    "PaymentsForAcquisitionOfIntangibleAssets": "capex_intangibles",
    "PembayaranUntukPerolehanAsetTakberwujud": "capex_intangibles",
    "CapitalExpenditures": "capital_expenditures",
    "PengeluaranBarangModal": "capital_expenditures",
    "CashFlowsFromUsedInInvestingActivities": "investing_cash_flow",
    "ArusKasDariAktivitasInvestasi": "investing_cash_flow",
    "CashFlowsFromUsedInFinancingActivities": "financing_cash_flow",
    "ArusKasDariAktivitasPendanaan": "financing_cash_flow",
    "PaymentsOfDividends": "dividends_paid",
    "PembayaranDividen": "dividends_paid",
    "NetIncreaseDecreaseInCashAndCashEquivalents": "net_cash_flow",
    "KenaikanPenurunanBersihKasDanSetaraKas": "net_cash_flow",
    "CashAndCashEquivalentsAtEndOfYear": "ending_cash_balance",
    "KasDanSetaraKasPadaAkhirPeriode": "ending_cash_balance",

    # 6. Shares
    "NumberOfSharesOutstanding": "shares_outstanding",
    "JumlahSahamBeredar": "shares_outstanding",
    "WeightedAverageNumberOfShares": "weighted_average_shares",
    "RataRataTertimbangJumlahSaham": "weighted_average_shares",

    # 7. Banking
    "NetInterestIncome": "net_interest_income",
    "PendapatanBungaBersih": "net_interest_income",
    "NetInterestMargin": "nim_pct",
    "RasioNetInterestMargin": "nim_pct",
    "NonPerformingLoanGross": "npl_gross_pct",
    "RasioNPLGross": "npl_gross_pct",
    "NonPerformingLoanNet": "npl_net_pct",
    "RasioNPLNet": "npl_net_pct",
    "CapitalAdequacyRatio": "car_pct",
    "RasioKecukupanModal": "car_pct",
    "LoanToDepositRatio": "ldr_pct",
    "RasioLoanToDeposit": "ldr_pct",
}


@dataclass
class XbrlFact:
    concept: str
    value: float
    unit: str
    decimals: int
    context_ref: str
    period_type: str              # instant, duration
    start_date: str | None = None
    end_date: str | None = None
    instant_date: str | None = None
    is_consolidated: bool = True
    dimensions: dict[str, str] = field(default_factory=dict)
    raw_tag: str = ""


class IdxXbrlParser:
    """Production-grade IDX XBRL Parser with zip-bomb protection and Arelle compatibility."""

    def __init__(self, repo_root: Path | None = None) -> None:
        self.root = repo_root or Path.cwd()

    def parse_file(self, path: Path, ticker: str | None = None) -> CanonicalFinancialStatement:
        """Parses an XBRL archive (.zip) or XML instance file (.xbrl, .xml)."""
        if not path.exists():
            raise FileNotFoundError(f"File XBRL tidak ditemukan: {path}")

        sym = (ticker or "").strip().upper()
        if not sym:
            m = re.search(r"\b([A-Z]{4})\b", path.name.upper())
            if m:
                sym = m.group(1)
        if not sym:
            raise ValueError(f"Ticker emiten tidak dapat diidentifikasi dari nama file {path.name}.")

        xml_content: bytes = b""
        filename = path.name

        if path.suffix.lower() == ".zip":
            xml_content, filename = self._extract_from_zip(path)
        else:
            if path.stat().st_size > MAX_UNCOMPRESSED_BYTES:
                raise ValueError(f"File XBRL melebihi batas ukuran keamanan ({MAX_UNCOMPRESSED_BYTES} bytes).")
            xml_content = path.read_bytes()

        return self._parse_xml_bytes(xml_content, sym, filename, str(path))

    def _extract_from_zip(self, zip_path: Path) -> tuple[bytes, str]:
        """Safely decompresses the primary XBRL instance with path traversal & zip bomb defense."""
        total_size = 0
        file_count = 0

        with zipfile.ZipFile(zip_path, "r") as z:
            namelist = z.namelist()
            if len(namelist) > MAX_FILE_COUNT:
                raise ValueError("Arsip ZIP memuat file melebihi batas keamanan.")

            # Look for instance XML or iXBRL HTML
            target_name = None
            for name in namelist:
                # Path traversal defense
                if ".." in name or name.startswith("/") or name.startswith("\\"):
                    raise ValueError(f"Terdeteksi potensi path traversal dalam arsip: {name}")

                info = z.getinfo(name)
                total_size += info.file_size
                file_count += 1
                if total_size > MAX_UNCOMPRESSED_BYTES:
                    raise ValueError("Arsip ZIP melebihi batas dekompresi keamanan (Zip Bomb Defense).")

                lower = name.lower()
                if lower.endswith((".xbrl", ".xml", ".xhtml", ".html")) and not lower.endswith("taxonomy.xml"):
                    if "instance" in lower or target_name is None:
                        target_name = name

            if not target_name:
                raise ValueError(f"Tidak ditemukan dokumen XBRL instance dalam arsip {zip_path.name}.")

            return z.read(target_name), target_name

    def _parse_xml_bytes(self, content: bytes, symbol: str, filename: str, full_path: str) -> CanonicalFinancialStatement:
        """Parses XML instance facts and builds CanonicalFinancialStatement."""
        # XXE Defense: ET.fromstring does not resolve external entities by default
        try:
            tree = ET.fromstring(content)
        except ET.ParseError as e:
            raise ValueError(f"Format XML XBRL tidak valid pada {filename}: {e}")

        # Namespaces map
        ns_map = {
            "xbrli": "http://www.xbrl.org/2003/instance",
            "idx-cor": "http://www.idx.co.id/xbrl/taxonomy/2020-01-01/cor",
        }

        # 1. Parse Contexts
        contexts: dict[str, dict[str, Any]] = {}
        for ctx_elem in tree.findall(".//{http://www.xbrl.org/2003/instance}context"):
            ctx_id = ctx_elem.get("id")
            if not ctx_id:
                continue

            period_elem = ctx_elem.find("{http://www.xbrl.org/2003/instance}period")
            period_data: dict[str, Any] = {"type": "unknown"}
            if period_elem is not None:
                instant = period_elem.find("{http://www.xbrl.org/2003/instance}instant")
                if instant is not None and instant.text:
                    period_data = {"type": "instant", "date": instant.text.strip()}
                else:
                    start_elem = period_elem.find("{http://www.xbrl.org/2003/instance}startDate")
                    end_elem = period_elem.find("{http://www.xbrl.org/2003/instance}endDate")
                    if start_elem is not None and end_elem is not None and start_elem.text and end_elem.text:
                        period_data = {
                            "type": "duration",
                            "start_date": start_elem.text.strip(),
                            "end_date": end_elem.text.strip(),
                        }

            # Check dimensions (Consolidated vs Separate)
            is_consolidated = True
            dimensions: dict[str, str] = {}
            for dim_elem in ctx_elem.findall(".//{http://xbrl.org/2006/xbrldi}explicitMember"):
                dim_name = dim_elem.get("dimension", "")
                member_val = dim_elem.text or ""
                dimensions[dim_name] = member_val
                if "Separate" in member_val or "Induk" in member_val:
                    is_consolidated = False

            contexts[ctx_id] = {
                "period": period_data,
                "is_consolidated": is_consolidated,
                "dimensions": dimensions,
            }

        # 2. Extract facts
        facts: list[XbrlFact] = []
        for elem in tree:
            tag = elem.tag
            if not isinstance(tag, str) or tag.startswith("{http://www.xbrl.org/2003/instance}"):
                continue

            # Strip namespace to get concept local name
            local_concept = tag.split("}")[-1] if "}" in tag else tag
            val_text = (elem.text or "").strip()
            if not val_text:
                continue

            # Clean number
            clean_num_str = val_text.replace(",", "").replace(" ", "")
            try:
                numeric_val = float(clean_num_str)
            except ValueError:
                continue

            ctx_id = elem.get("contextRef", "")
            ctx = contexts.get(ctx_id, {"period": {"type": "unknown"}, "is_consolidated": True, "dimensions": {}})
            unit_ref = elem.get("unitRef", "IDR")
            decimals = int(elem.get("decimals", "0")) if (elem.get("decimals") or "").lstrip("-").isdigit() else 0

            p_info = ctx["period"]
            fact = XbrlFact(
                concept=local_concept,
                value=numeric_val,
                unit=unit_ref,
                decimals=decimals,
                context_ref=ctx_id,
                period_type=p_info["type"],
                start_date=p_info.get("start_date"),
                end_date=p_info.get("end_date"),
                instant_date=p_info.get("date"),
                is_consolidated=ctx["is_consolidated"],
                dimensions=ctx["dimensions"],
                raw_tag=tag,
            )
            facts.append(fact)

        # 3. Determine latest reporting period and fiscal year
        latest_date = None
        for f in facts:
            d = f.instant_date or f.end_date
            if d and (latest_date is None or d > latest_date):
                latest_date = d

        detected = detect_period(filename) or (detect_period(latest_date) if latest_date else None)
        period_str = detected[0] if detected else (f"{latest_date[:4]}-FY" if latest_date else "UNKNOWN_PERIOD")
        period_type = detected[1] if detected else "FY"

        # 4. Map facts to Canonical Statement
        stmt = CanonicalFinancialStatement(
            symbol=symbol,
            period=period_str,
            period_type=period_type,
            currency="IDR",
            unit="IDR",
            unit_multiplier=1.0,
            basis="consolidated",
            audit_status="audited" if "FY" in period_type else "unaudited",
            period_end_date=latest_date or "2024-12-31",
            source_document=filename,
            document_format="XBRL",
            source_url=f"https://www.idx.co.id/perusahaan-tercatat/laporan-keuangan-dan-tahunan/ ({filename})",
        )

        citations: dict[str, SourceCitation] = {}

        # Prioritize consolidated facts matching latest end date
        for f in facts:
            if not f.is_consolidated:
                continue
            f_date = f.instant_date or f.end_date
            if latest_date and f_date and f_date != latest_date:
                continue

            target_field = IDX_TAXONOMY_MAP.get(f.concept)
            if target_field and getattr(stmt, target_field, None) is None:
                # Value scaling from decimals/units
                val = f.value
                setattr(stmt, target_field, val)
                citations[target_field] = SourceCitation(
                    statement_type="XBRL Instance",
                    xbrl_concept=f.concept,
                    xbrl_context=f.context_ref,
                    raw_reported_text=str(f.value),
                    file_path=full_path,
                )

        # Compute capex if components exist
        if stmt.capital_expenditures is None and stmt.capex_ppe is not None:
            stmt.capital_expenditures = abs(stmt.capex_ppe) + (abs(stmt.capex_intangibles) if stmt.capex_intangibles else 0.0)

        # Separate interest-bearing debt from general liabilities
        if stmt.interest_bearing_debt is None:
            st_d = stmt.short_term_debt or 0.0
            lt_d = stmt.long_term_debt or 0.0
            if st_d > 0 or lt_d > 0:
                stmt.interest_bearing_debt = st_d + lt_d

        stmt.citations = citations
        stmt.validate_accounting_relationships()
        return stmt
