"""IDX Corporate Event Intelligence Engine.

Provides verifiable, time-aware public announcement ingestion, classification across
40+ event taxonomy categories, entity and subsidiary resolution, relative materiality analysis,
and event impact scoring without data fabrication.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone, timedelta
import hashlib
import json
import logging
from pathlib import Path
import re
from typing import Any, Sequence

from openbagus.core.env import get_repo_root

logger = logging.getLogger(__name__)

try:
    from zoneinfo import ZoneInfo
    WIB_TZ = ZoneInfo("Asia/Jakarta")
except Exception:
    WIB_TZ = timezone(timedelta(hours=7), "Asia/Jakarta")


# 40+ Corporate Event Taxonomy Classes
EVENT_TAXONOMY = {
    # Earnings & Financial Performance
    "EARNINGS_RELEASE": ("Laporan Keuangan", "Periodic financial statements release"),
    "EARNINGS_SURPRISE": ("Kejutan Laba", "Material earnings beat/miss relative to prior period"),
    "REVENUE_GROWTH": ("Pertumbuhan Pendapatan", "Material revenue expansion"),
    "PROFIT_TURNAROUND": ("Pembalikan Laba", "Shift from net loss to net profit"),
    "PROFIT_WARNING": ("Peringatan Penurunan Laba", "Disclosure of significant profit drop or impairment"),

    # Capital Allocation & Corporate Actions
    "DIVIDEND_DECLARATION": ("Pembagian Dividen", "Cash/interim dividend declaration"),
    "SPECIAL_DIVIDEND": ("Dividen Spesial", "One-off special dividend declaration"),
    "SHARE_BUYBACK": ("Pembelian Kembali Saham", "Share buyback plan or allocation"),
    "RIGHTS_ISSUE": ("Hak Memesan Efek Terlebih Dahulu (HMETD)", "Pre-emptive rights offering"),
    "PRIVATE_PLACEMENT": ("Penambahan Modal Tanpa HMETD", "Non-preemptive private placement"),
    "STOCK_SPLIT": ("Pemecahan Nilai Nominal Saham", "Stock split ratio announcement"),
    "REVERSE_STOCK_SPLIT": ("Penggabungan Nilai Nominal Saham", "Reverse stock split"),

    # M&A & Business Combinations
    "MERGER": ("Penggabungan Usaha", "Corporate merger"),
    "ACQUISITION": ("Akuisisi Saham/Aset", "Acquisition of entity or major asset"),
    "ASSET_DIVESTMENT": ("Divestasi Aset", "Sale or disposal of material subsidiary/asset"),

    # Commercial & Operational Contracts
    "MATERIAL_CONTRACT": ("Kontrak Material", "Material commercial contract signed"),
    "GOVERNMENT_CONTRACT": ("Kontrak Pemerintah / BUMN", "Public tender or state project award"),
    "NEW_PROJECT": ("Proyek Baru", "Commencement of major commercial project"),
    "CAPACITY_EXPANSION": ("Ekspansi Kapasitas", "Factory or plant capacity increase"),
    "NEW_FACTORY": ("Pabrik Baru / Fasilitas Baru", "New operational facility opening"),
    "RESOURCE_DISCOVERY": ("Penemuan Cadangan / Sumber Daya", "Mineral or hydrocarbon reserve discovery"),
    "PRODUCTION_UPDATE": ("Kinerja Operasional / Produksi", "Operational volume update"),
    "COMMODITY_EXPOSURE": ("Eksposur Komoditas", "Commodity hedging or strategic contract"),

    # Debt & Credit
    "DEBT_RESTRUCTURING": ("Restrukturisasi Utang", "Debt rescheduling or composition agreement"),
    "DEBT_DEFAULT": ("Gagal Bayar Utang (Default)", "Failure to pay interest/principal on notes/loans"),
    "BOND_ISSUANCE": ("Penerbitan Obligasi / Sukuk", "New debt securities issuance"),
    "CREDIT_RATING_CHANGE": ("Perubahan Peringkat Utang", "Credit rating upgrade/downgrade by Pefindo/Fitch"),

    # Governance & Ownership
    "MANAGEMENT_CHANGE": ("Perubahan Direksi / Komisaris", "Board of directors or commissioners reshuffle"),
    "CONTROLLING_SHAREHOLDER_CHANGE": ("Perubahan Pengendali", "Change of ultimate controlling shareholder"),
    "MAJOR_SHAREHOLDER_DISCLOSURE": ("Keterbukaan Pemegang Saham Utama", "Substantial shareholding threshold change (>5%)"),

    # Regulatory & Legal
    "REGULATORY_APPROVAL": ("Persetujuan Regulator", "OJK, ministry, or antitrust approval"),
    "REGULATORY_SANCTION": ("Sanksi Regulasi / Denda", "Administrative fine, reprimand, or permit revocation"),
    "LITIGATION": ("Perkara Hukum / PKPU", "Lawsuit, PKPU filing, or arbitration"),
    "AUDITOR_OPINION": ("Opini Auditor", "Auditor's opinion disclosure (Unqualified, Qualified, Disclaimer)"),

    # Market Microstructure & Trading Status
    "TRADING_SUSPENSION": ("Penghentian Sementara Perdagangan (Suspensi)", "Exchange trading suspension"),
    "TRADING_RESUMPTION": ("Pencabutan Suspensi (Unsuspend)", "Resumption of trading by IDX"),
    "BOARD_TRANSFER": ("Pindah Papan Pencatatan", "Transfer between Main, Development, or Acceleration boards"),
    "SPECIAL_MONITORING_ENTRY": ("Masuk Papan Pemantauan Khusus (FCA)", "Inclusion into periodic call auction watchlist"),
    "SPECIAL_MONITORING_EXIT": ("Keluar Papan Pemantauan Khusus", "Exit from periodic call auction watchlist"),
    "IPO": ("Pencatatan Perdana Saham (IPO)", "Initial public offering listing"),

    # Catch-all
    "CORPORATE_ACTION_OTHER": ("Aksi Korporasi Lainnya", "Other verifiable corporate action"),
    "UNCLASSIFIED_MATERIAL_EVENT": ("Keterbukaan Informasi Lainnya", "Unclassified material disclosure"),
}


VERIFICATION_STATUSES = {
    "CONFIRMED_OFFICIAL",   # Verified against official IDX disclosure / OJK filing / company IR
    "CONFIRMED_SECONDARY",  # Verified against verified secondary financial news wire
    "UNVERIFIED",           # Unconfirmed report or rumor
    "CONTRADICTED",         # Refuted by company clarification
    "SUPERSEDED",           # Replaced by amended disclosure
}

AMENDMENT_STATUSES = {
    "ORIGINAL",
    "AMENDED",
    "CANCELLED",
}


@dataclass
class CorporateEventRecord:
    event_id: str
    ticker: str
    issuer_id: str
    event_type: str
    event_title: str
    published_at: str                         # ISO 8601 UTC or WIB timestamp
    first_publicly_available_at: str          # Earliest time disclosed publicly
    first_observed_at: str                    # When OpenBagus ingested/recorded the item
    retrieved_at: str                         # Timestamp when fetched
    effective_date: str                       # YYYY-MM-DD when the event takes legal effect
    source_provider: str                      # e.g. "IDX_OFFICIAL", "COMPANY_IR", "OJK"
    source_url: str                           # Permitted HTTPS URL
    source_document_id: str                   # Official reference ID / nomor surat
    document_hash: str                        # SHA-256 of raw disclosure content
    disclosure_language: str = "ID"           # "ID" or "EN"
    event_summary: str = ""
    materiality_facts: dict[str, Any] = field(default_factory=dict)
    quantitative_amounts: dict[str, float] = field(default_factory=dict)
    confidence: float = 1.0                   # 0.0 to 1.0 confidence in parsing
    verification_status: str = "CONFIRMED_OFFICIAL"
    amendment_status: str = "ORIGINAL"
    related_events: list[str] = field(default_factory=list)
    impact_score: float = 0.0                 # -100 to +100 score
    sentiment_label: str = "NEUTRAL"          # HIGH_POSITIVE, MODERATE_POSITIVE, NEUTRAL, NEGATIVE_RISK
    relative_materiality_pct: float | None = None # e.g. Contract/Revenue or Buyback/MarketCap

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CorporateEventRecord:
        valid_fields = {f.name for f in cls.__dataclass_fields__.values()}
        filtered = {k: v for k, v in data.items() if k in valid_fields}
        return cls(**filtered)


# Known Entity and Subsidiary Mappings for Indonesian Issuers
# Maps subsidiary/operating business names to parent IDX ticker
KNOWN_SUBSIDIARY_MAP: dict[str, str] = {
    "PT ASTRA SEDAYA FINANCE": "ASII",
    "PT TOYOTA ASTRA MOTOR": "ASII",
    "PT UNITED TRACTORS PANDU ENGINEERING": "UNTR",
    "PT PAMAPERSADA NUSANTARA": "UNTR",
    "PT INDOFOOD MAKMUR": "INDF",
    "PT PINEHILL CORA": "ICBP",
    "PT BANK BCA SYARIAH": "BBCA",
    "PT BANK RAYA INDONESIA": "BBRI",
    "PT PEGADAIAN": "BBRI",
    "PT PERMODALAN NASIONAL MADANI": "BBRI",
    "PT BANK MANDIRI TASPEN": "BMRI",
    "PT TELKOM DATA EKOSISTEM": "TLKM",
    "PT DAYAMITRA TELEKOMUNIKASI TBK": "MTEL",
    "PT MITRATEL": "MTEL",
    "PT BUKIT ASAM KREATIF": "PTBA",
    "PT PERTAMINA GEOTHERMAL ENERGY": "PGEO",
    "PT HERO GLOBAL ENERGI": "HGII",
    "PT HERO HYDRO ENERGI": "HGII",
}


class RelativeMaterialityEngine:
    """Evaluates the relative economic materiality of disclosures against financial baselines."""

    @staticmethod
    def evaluate_contract(
        contract_value_idr: float,
        annual_revenue_idr: float | None,
        total_assets_idr: float | None = None,
        equity_idr: float | None = None,
        duration_months: int | None = 12,
    ) -> dict[str, Any]:
        """Calculates relative contract materiality (Contract/Revenue, Contract/Assets)."""
        if contract_value_idr <= 0:
            return {"materiality": "NEGLIGIBLE", "score": 0.0, "reason": "Nilai kontrak nol atau tidak valid"}

        ratios = {}
        score = 20.0  # Base positive points for signed contract

        if annual_revenue_idr and annual_revenue_idr > 0:
            rev_ratio = contract_value_idr / annual_revenue_idr
            ratios["contract_to_revenue_pct"] = round(rev_ratio * 100.0, 2)
            if rev_ratio >= 0.50:       # >= 50% of annual revenue: Transformational
                score += 50.0
                materiality = "HIGHLY_MATERIAL"
            elif rev_ratio >= 0.20:     # >= 20% of annual revenue (IDX material threshold)
                score += 35.0
                materiality = "MATERIAL"
            elif rev_ratio >= 0.05:     # 5-20% of annual revenue
                score += 15.0
                materiality = "MODERATE"
            else:
                materiality = "LOW_MATERIALITY"
        else:
            materiality = "UNASSESSED_REVENUE_GAP"

        if total_assets_idr and total_assets_idr > 0:
            asset_ratio = contract_value_idr / total_assets_idr
            ratios["contract_to_assets_pct"] = round(asset_ratio * 100.0, 2)

        return {
            "materiality": materiality,
            "score": min(100.0, score),
            "contract_value_idr": contract_value_idr,
            "annual_revenue_idr": annual_revenue_idr,
            "ratios": ratios,
            "duration_months": duration_months,
            "caveat": "Nilai kontrak kotor; realisasi margin laba bersih bergantung pada biaya operasional.",
        }

    @staticmethod
    def evaluate_buyback(
        authorized_amount_idr: float,
        market_cap_idr: float | None,
        authorized_shares: float | None = None,
        outstanding_shares: float | None = None,
    ) -> dict[str, Any]:
        """Calculates buyback materiality (Authorized Amount / Market Capitalization)."""
        if authorized_amount_idr <= 0:
            return {"materiality": "NEGLIGIBLE", "score": 0.0}

        ratios = {}
        score = 25.0
        materiality = "MODERATE"

        if market_cap_idr and market_cap_idr > 0:
            cap_ratio = authorized_amount_idr / market_cap_idr
            ratios["buyback_to_market_cap_pct"] = round(cap_ratio * 100.0, 2)
            if cap_ratio >= 0.10:       # >= 10% of market cap: Strong support
                score += 50.0
                materiality = "HIGHLY_MATERIAL"
            elif cap_ratio >= 0.05:     # >= 5% of market cap
                score += 35.0
                materiality = "MATERIAL"
            elif cap_ratio >= 0.01:
                score += 15.0
                materiality = "MODERATE"
        else:
            materiality = "UNASSESSED_MCAP_GAP"

        if authorized_shares and outstanding_shares and outstanding_shares > 0:
            shares_ratio = authorized_shares / outstanding_shares
            ratios["buyback_shares_pct"] = round(shares_ratio * 100.0, 2)

        return {
            "materiality": materiality,
            "score": min(100.0, score),
            "authorized_amount_idr": authorized_amount_idr,
            "market_cap_idr": market_cap_idr,
            "ratios": ratios,
            "caveat": "Anggaran buyback adalah batas maksimal; realisasi eksekusi bergantung pada likuiditas pasar.",
        }

    @staticmethod
    def evaluate_rights_issue(
        new_shares: float,
        existing_shares: float,
        issue_price: float | None = None,
        last_price: float | None = None,
        use_of_proceeds: str = "",
    ) -> dict[str, Any]:
        """Calculates rights issue dilution and discount."""
        if existing_shares <= 0 or new_shares <= 0:
            return {"materiality": "UNKNOWN", "score": 0.0}

        dilution_pct = (new_shares / (existing_shares + new_shares)) * 100.0
        ratios = {"dilution_pct": round(dilution_pct, 2)}
        score = 0.0

        if issue_price and last_price and last_price > 0:
            discount_pct = ((last_price - issue_price) / last_price) * 100.0
            ratios["price_discount_pct"] = round(discount_pct, 2)
            if discount_pct > 20.0:
                score -= 30.0  # Significant dilution discount risk
            elif discount_pct < 0:
                score += 10.0  # Issued at premium

        # Debt repayment vs productive growth capex
        is_growth = bool(re.search(r"ekspansi|investasi|modal kerja|akuisisi", use_of_proceeds, re.I))
        is_debt = bool(re.search(r"bayar utang|utang|kewajiban", use_of_proceeds, re.I))

        if is_growth:
            score += 15.0
        elif is_debt:
            score -= 10.0

        materiality = "HIGH_DILUTION" if dilution_pct >= 25.0 else "MODERATE_DILUTION"

        return {
            "materiality": materiality,
            "score": score,
            "dilution_pct": round(dilution_pct, 2),
            "ratios": ratios,
            "use_of_proceeds": use_of_proceeds,
            "caveat": f"Potensi dilusi kepemilikan sebesar {dilution_pct:.1f}% jika pemegang saham tidak mengeksekusi hak.",
        }

    @staticmethod
    def evaluate_earnings_turnaround(
        current_net_income: float,
        prior_net_income: float,
        current_revenue: float | None = None,
        prior_revenue: float | None = None,
    ) -> dict[str, Any]:
        """Evaluates operational turnaround from net loss to net profit."""
        is_turnaround = prior_net_income < 0 and current_net_income > 0
        ratios = {}
        score = 0.0

        if is_turnaround:
            score = 65.0
            materiality = "PROFIT_TURNAROUND"
            ratios["absolute_swing_idr"] = current_net_income - prior_net_income
        elif current_net_income > 0 and prior_net_income > 0:
            growth_pct = ((current_net_income - prior_net_income) / prior_net_income) * 100.0
            ratios["net_income_growth_pct"] = round(growth_pct, 2)
            if growth_pct >= 50.0:
                score = 50.0
                materiality = "HIGH_GROWTH"
            elif growth_pct >= 20.0:
                score = 30.0
                materiality = "MODERATE_GROWTH"
            else:
                score = 10.0
                materiality = "STABLE"
        elif current_net_income < 0:
            score = -50.0
            materiality = "NET_LOSS"
        else:
            materiality = "FLAT"

        if current_revenue and prior_revenue and prior_revenue > 0:
            rev_growth = ((current_revenue - prior_revenue) / prior_revenue) * 100.0
            ratios["revenue_growth_pct"] = round(rev_growth, 2)

        return {
            "materiality": materiality,
            "score": score,
            "ratios": ratios,
            "is_turnaround": is_turnaround,
        }


class CorporateEventManager:
    """Manages the full lifecycle of corporate disclosures, extraction, and querying."""

    def __init__(self, root: Path | None = None) -> None:
        self.root = root or get_repo_root()
        self.events_dir = self.root / "data" / "events"
        self.events_file = self.events_dir / "events.json"
        self._events: dict[str, CorporateEventRecord] = {}
        self._load()

    def _load(self) -> None:
        self.events_dir.mkdir(parents=True, exist_ok=True)
        if self.events_file.exists():
            try:
                raw = json.loads(self.events_file.read_text(encoding="utf-8"))
                for item in raw:
                    ev = CorporateEventRecord.from_dict(item)
                    self._events[ev.event_id] = ev
            except Exception as e:
                logger.warning("Failed to load existing events: %s", e)

    def save(self) -> None:
        self.events_dir.mkdir(parents=True, exist_ok=True)
        data = [ev.to_dict() for ev in self._events.values()]
        self.events_file.write_text(json.dumps(data, indent=2), encoding="utf-8")

    def register_event(self, event: CorporateEventRecord) -> None:
        """Stores or updates an event record with calculated score and sentiment."""
        self._events[event.event_id] = event
        self.save()

    def create_event(
        self,
        ticker: str,
        event_type: str,
        event_title: str,
        published_at: str,
        source_url: str,
        source_document_id: str,
        raw_text: str,
        effective_date: str | None = None,
        source_provider: str = "IDX_OFFICIAL",
        verification_status: str = "CONFIRMED_OFFICIAL",
        materiality_facts: dict[str, Any] | None = None,
        quantitative_amounts: dict[str, float] | None = None,
        annual_revenue_baseline: float | None = None,
        market_cap_baseline: float | None = None,
    ) -> CorporateEventRecord:
        """Constructs, validates, hashes, and scores an official corporate event."""
        clean_ticker = ticker.strip().upper()
        if event_type not in EVENT_TAXONOMY:
            event_type = "UNCLASSIFIED_MATERIAL_EVENT"

        # Generate deterministic document hash
        doc_hash = hashlib.sha256(raw_text.encode("utf-8")).hexdigest()
        event_id = f"{clean_ticker}_{doc_hash[:12]}"

        # Timestamps
        now_iso = datetime.now(timezone.utc).isoformat()
        eff_date = effective_date or published_at[:10]

        q_amounts = quantitative_amounts or {}
        facts = materiality_facts or {}

        # Calculate relative materiality & score
        score = 0.0
        sentiment = "NEUTRAL"
        rel_pct = None

        if event_type in ("MATERIAL_CONTRACT", "GOVERNMENT_CONTRACT"):
            c_val = q_amounts.get("contract_value", 0.0)
            res = RelativeMaterialityEngine.evaluate_contract(c_val, annual_revenue_baseline)
            score = res["score"]
            sentiment = "HIGH_POSITIVE" if score >= 60.0 else "MODERATE_POSITIVE"
            rel_pct = res.get("ratios", {}).get("contract_to_revenue_pct")
            facts["relative_materiality"] = res

        elif event_type == "SHARE_BUYBACK":
            b_val = q_amounts.get("buyback_amount", 0.0)
            res = RelativeMaterialityEngine.evaluate_buyback(b_val, market_cap_baseline)
            score = res["score"]
            sentiment = "HIGH_POSITIVE" if score >= 60.0 else "MODERATE_POSITIVE"
            rel_pct = res.get("ratios", {}).get("buyback_to_market_cap_pct")
            facts["relative_materiality"] = res

        elif event_type == "RIGHTS_ISSUE":
            n_shares = q_amounts.get("new_shares", 0.0)
            e_shares = q_amounts.get("existing_shares", 1.0)
            p_issue = q_amounts.get("issue_price")
            p_last = q_amounts.get("last_price")
            res = RelativeMaterialityEngine.evaluate_rights_issue(n_shares, e_shares, p_issue, p_last)
            score = res["score"]
            sentiment = "NEGATIVE_RISK" if score < 0 else "MODERATE_POSITIVE"
            rel_pct = res.get("dilution_pct")
            facts["relative_materiality"] = res

        elif event_type == "PROFIT_TURNAROUND":
            curr_ni = q_amounts.get("current_net_income", 1.0)
            prior_ni = q_amounts.get("prior_net_income", -1.0)
            res = RelativeMaterialityEngine.evaluate_earnings_turnaround(curr_ni, prior_ni)
            score = res["score"]
            sentiment = "HIGH_POSITIVE" if score >= 50.0 else "MODERATE_POSITIVE"
            facts["relative_materiality"] = res

        elif event_type in ("PROFIT_WARNING", "DEBT_DEFAULT", "TRADING_SUSPENSION", "SPECIAL_MONITORING_ENTRY", "REGULATORY_SANCTION"):
            score = -75.0
            sentiment = "NEGATIVE_RISK"

        elif event_type in ("DIVIDEND_DECLARATION", "SPECIAL_DIVIDEND", "TRADING_RESUMPTION", "SPECIAL_MONITORING_EXIT"):
            score = 40.0
            sentiment = "MODERATE_POSITIVE"

        rec = CorporateEventRecord(
            event_id=event_id,
            ticker=clean_ticker,
            issuer_id=f"IDX:{clean_ticker}",
            event_type=event_type,
            event_title=event_title,
            published_at=published_at,
            first_publicly_available_at=published_at,
            first_observed_at=now_iso,
            retrieved_at=now_iso,
            effective_date=eff_date,
            source_provider=source_provider,
            source_url=source_url,
            source_document_id=source_document_id,
            document_hash=doc_hash,
            disclosure_language="ID",
            event_summary=raw_text[:300].strip(),
            materiality_facts=facts,
            quantitative_amounts=q_amounts,
            confidence=1.0,
            verification_status=verification_status,
            impact_score=score,
            sentiment_label=sentiment,
            relative_materiality_pct=rel_pct,
        )

        self.register_event(rec)
        return rec

    def resolve_issuer_from_text(self, text: str) -> str | None:
        """Resolves ticker from company name, subsidiary, or direct ticker mention."""
        # 1. Direct ticker pattern: (KODE: TICK) or (TICK.JK)
        m = re.search(r"\b([A-Z]{4})\b(?:\.JK)?", text)
        if m:
            candidate = m.group(1).upper()
            return candidate

        # 2. Subsidiary mapping
        text_upper = text.upper()
        for sub_name, parent_ticker in KNOWN_SUBSIDIARY_MAP.items():
            if sub_name in text_upper:
                return parent_ticker
        return None

    def get_events_for_ticker(self, ticker: str) -> list[CorporateEventRecord]:
        """Returns chronological events for ticker."""
        clean = ticker.strip().upper()
        matched = [ev for ev in self._events.values() if ev.ticker == clean]
        matched.sort(key=lambda x: x.published_at, reverse=True)
        return matched

    def get_latest_events(
        self,
        event_type: str | None = None,
        sentiment: str | None = None,
        since_date: str | None = None,
        limit: int = 50,
    ) -> list[CorporateEventRecord]:
        """Queries events with multi-criteria filtering."""
        results = list(self._events.values())
        if event_type:
            results = [ev for ev in results if ev.event_type == event_type]
        if sentiment:
            results = [ev for ev in results if ev.sentiment_label == sentiment]
        if since_date:
            results = [ev for ev in results if ev.effective_date >= since_date]

        results.sort(key=lambda x: x.published_at, reverse=True)
        return results[:limit]

    def get_events_summary(self) -> dict[str, Any]:
        """Summary metrics across all registered disclosures."""
        types: dict[str, int] = {}
        sentiments: dict[str, int] = {}
        tickers = set()

        for ev in self._events.values():
            types[ev.event_type] = types.get(ev.event_type, 0) + 1
            sentiments[ev.sentiment_label] = sentiments.get(ev.sentiment_label, 0) + 1
            tickers.add(ev.ticker)

        return {
            "total_events": len(self._events),
            "unique_issuers": len(tickers),
            "by_type": types,
            "by_sentiment": sentiments,
        }
