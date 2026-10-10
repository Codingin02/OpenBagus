"""Normalized shareholder ownership intelligence for Indonesian equities.

Conforms to official IDX and KSEI disclosure standards:
- Shareholders >= 5% (and >= 1% where reported)
- Domestic vs Foreign investor categorization
- Institutional vs Individual distribution
- Explicit denominator clarification (shares outstanding vs registered holdings)
- Reconciled residual public float (<5%) without fabricating beneficial owners.
"""

from __future__ import annotations

import csv
import json
import math
import re
from dataclasses import asdict, dataclass, field
from datetime import date
from pathlib import Path

from openbagus.core.guards import scan_text
from openbagus.domains.equities.catalog import source_url

DENOMINATOR_SHARES_OUTSTANDING = "shares_outstanding"
DENOMINATOR_REGISTERED_HOLDINGS = "registered_holdings"

INVESTOR_TYPES = {
    "ID_INSTITUTION": "Domestic Institution",
    "FO_INSTITUTION": "Foreign Institution",
    "ID_INDIVIDUAL": "Domestic Individual",
    "FO_INDIVIDUAL": "Foreign Individual",
    "MUTUAL_FUND": "Mutual Fund (Reksadana)",
    "PENSION_FUND": "Pension Fund (Dana Pensiun)",
    "INSURANCE": "Insurance (Asuransi)",
    "BANK": "Bank",
    "FOUNDATION": "Foundation (Yayasan)",
    "CONTROLLER": "Controlling Shareholder / Parent",
    "GOVERNMENT": "Government of Indonesia",
    "OTHERS": "Other Public / Retail",
}


@dataclass
class ShareholderRecord:
    issuer: str
    ticker: str
    reporting_date: str
    publication_date: str
    shareholder: str
    investor_type: str
    shares_held: float
    percentage: float
    denominator_type: str = DENOMINATOR_SHARES_OUTSTANDING
    source: str = ""
    verification_status: str = "VERIFIED"

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class OwnershipStructure:
    ticker: str
    issuer: str
    reporting_date: str
    publication_date: str
    source: str
    shares_outstanding: float
    denominator_type: str
    top_shareholders: list[ShareholderRecord] = field(default_factory=list)
    public_shareholders_pct: float = 0.0
    domestic_pct: float | None = None
    foreign_pct: float | None = None
    investor_type_breakdown: dict[str, float] = field(default_factory=dict)
    reconciled: bool = True
    reconciliation_notes: str = ""
    denominator_explanation: str = ""
    verification_status: str = "UNVERIFIED"
    regulatory_free_float_pct: float | None = None

    def to_dict(self) -> dict:
        return {
            "ticker": self.ticker,
            "issuer": self.issuer,
            "reporting_date": self.reporting_date,
            "publication_date": self.publication_date,
            "source": self.source,
            "shares_outstanding": self.shares_outstanding,
            "denominator_type": self.denominator_type,
            "top_shareholders": [s.to_dict() for s in self.top_shareholders],
            "public_shareholders_pct": round(self.public_shareholders_pct, 4) if self.public_shareholders_pct is not None else 0.0,
            "domestic_pct": round(self.domestic_pct, 4) if self.domestic_pct is not None else None,
            "foreign_pct": round(self.foreign_pct, 4) if self.foreign_pct is not None else None,
            "investor_type_breakdown": {k: round(v, 4) for k, v in self.investor_type_breakdown.items()},
            "reconciled": self.reconciled,
            "reconciliation_notes": self.reconciliation_notes,
            "denominator_explanation": self.denominator_explanation,
            "verification_status": self.verification_status,
            "regulatory_free_float_pct": self.regulatory_free_float_pct,
        }


# Synthetic test fixtures for automated testing ONLY. Never loaded as production fallback.
SYNTHETIC_OWNERSHIP_TEST_FIXTURES: dict[str, dict] = {
    "BBCA": {
        "issuer": "PT Bank Central Asia Tbk",
        "ticker": "BBCA",
        "reporting_date": "2026-06-30",
        "publication_date": "2026-07-10",
        "source": "https://www.idx.co.id/id/perusahaan-tercatat/data-kepemilikan-saham/",
        "shares_outstanding": 123275050000.0,
        "denominator_type": DENOMINATOR_SHARES_OUTSTANDING,
        "top_shareholders": [
            {
                "shareholder": "PT Dwimuria Investama Andalan",
                "investor_type": "Domestic Institution",
                "shares_held": 67729950000.0,
                "percentage": 54.94,
            },
            {
                "shareholder": "Direksi & Komisaris (Management)",
                "investor_type": "Domestic Individual",
                "shares_held": 3058980000.0,
                "percentage": 2.48,
            },
        ],
        "domestic_pct": 69.12,
        "foreign_pct": 30.88,
        "investor_type_breakdown": {
            "Controlling Institution": 54.94,
            "Management / Insiders": 2.48,
            "Domestic Institutional": 7.82,
            "Domestic Retail": 3.88,
            "Foreign Institutional": 28.52,
            "Foreign Retail": 2.36,
        },
    },
    "BBRI": {
        "issuer": "PT Bank Rakyat Indonesia (Persero) Tbk",
        "ticker": "BBRI",
        "reporting_date": "2026-06-30",
        "publication_date": "2026-07-10",
        "source": "https://www.idx.co.id/id/perusahaan-tercatat/data-kepemilikan-saham/",
        "shares_outstanding": 151559000000.0,
        "denominator_type": DENOMINATOR_SHARES_OUTSTANDING,
        "top_shareholders": [
            {
                "shareholder": "Negara Republik Indonesia (Government A & B Shares)",
                "investor_type": "Government of Indonesia",
                "shares_held": 80610400000.0,
                "percentage": 53.19,
            },
        ],
        "domestic_pct": 68.45,
        "foreign_pct": 31.55,
        "investor_type_breakdown": {
            "Government of Indonesia": 53.19,
            "Domestic Institutional": 9.42,
            "Domestic Retail": 5.84,
            "Foreign Institutional": 29.11,
            "Foreign Retail": 2.44,
        },
    },
    "BMRI": {
        "issuer": "PT Bank Mandiri (Persero) Tbk",
        "ticker": "BMRI",
        "reporting_date": "2026-06-30",
        "publication_date": "2026-07-10",
        "source": "https://www.idx.co.id/id/perusahaan-tercatat/data-kepemilikan-saham/",
        "shares_outstanding": 93333333333.0,
        "denominator_type": DENOMINATOR_SHARES_OUTSTANDING,
        "top_shareholders": [
            {
                "shareholder": "Negara Republik Indonesia",
                "investor_type": "Government of Indonesia",
                "shares_held": 48533333333.0,
                "percentage": 52.00,
            },
        ],
        "domestic_pct": 69.80,
        "foreign_pct": 30.20,
        "investor_type_breakdown": {
            "Government of Indonesia": 52.00,
            "Domestic Institutional": 10.60,
            "Domestic Retail": 7.20,
            "Foreign Institutional": 28.10,
            "Foreign Retail": 2.10,
        },
    },
    "TLKM": {
        "issuer": "PT Telkom Indonesia (Persero) Tbk",
        "ticker": "TLKM",
        "reporting_date": "2026-06-30",
        "publication_date": "2026-07-10",
        "source": "https://www.idx.co.id/id/perusahaan-tercatat/data-kepemilikan-saham/",
        "shares_outstanding": 99062216600.0,
        "denominator_type": DENOMINATOR_SHARES_OUTSTANDING,
        "top_shareholders": [
            {
                "shareholder": "Negara Republik Indonesia",
                "investor_type": "Government of Indonesia",
                "shares_held": 51602353000.0,
                "percentage": 52.09,
            },
        ],
        "domestic_pct": 67.25,
        "foreign_pct": 32.75,
        "investor_type_breakdown": {
            "Government of Indonesia": 52.09,
            "Domestic Institutional": 9.12,
            "Domestic Retail": 6.04,
            "Foreign Institutional": 30.20,
            "Foreign Retail": 2.55,
        },
    },
    "ASII": {
        "issuer": "PT Astra International Tbk",
        "ticker": "ASII",
        "reporting_date": "2026-06-30",
        "publication_date": "2026-07-10",
        "source": "https://www.idx.co.id/id/perusahaan-tercatat/data-kepemilikan-saham/",
        "shares_outstanding": 40483553140.0,
        "denominator_type": DENOMINATOR_SHARES_OUTSTANDING,
        "top_shareholders": [
            {
                "shareholder": "Jardine Cycle & Carriage Ltd",
                "investor_type": "Foreign Institution",
                "shares_held": 20288255040.0,
                "percentage": 50.11,
            },
        ],
        "domestic_pct": 27.60,
        "foreign_pct": 72.40,
        "investor_type_breakdown": {
            "Controlling Foreign Institution": 50.11,
            "Domestic Institutional": 15.30,
            "Domestic Retail": 12.30,
            "Other Foreign Institutional": 20.15,
            "Other Foreign Retail": 2.14,
        },
    },
    "ANTM": {
        "issuer": "PT Aneka Tambang Tbk",
        "ticker": "ANTM",
        "reporting_date": "2026-06-30",
        "publication_date": "2026-07-10",
        "source": "https://www.idx.co.id/id/perusahaan-tercatat/data-kepemilikan-saham/",
        "shares_outstanding": 24030764725.0,
        "denominator_type": DENOMINATOR_SHARES_OUTSTANDING,
        "top_shareholders": [
            {
                "shareholder": "PT Mineral Industri Indonesia (Persero) / MIND ID",
                "investor_type": "Government of Indonesia",
                "shares_held": 15619999999.0,
                "percentage": 65.00,
            },
        ],
        "domestic_pct": 82.50,
        "foreign_pct": 17.50,
        "investor_type_breakdown": {
            "MIND ID (Holding BUMN Tambang)": 65.00,
            "Domestic Institutional": 7.80,
            "Domestic Retail": 9.70,
            "Foreign Institutional": 15.20,
            "Foreign Retail": 2.30,
        },
    },
}


def get_synthetic_test_ownership(symbol: str) -> OwnershipStructure | None:
    """Returns a synthetic test ownership structure for test suites only. Never called in production."""
    sym = symbol.strip().upper()
    if sym in SYNTHETIC_OWNERSHIP_TEST_FIXTURES:
        seed = SYNTHETIC_OWNERSHIP_TEST_FIXTURES[sym]
        return reconcile_ownership(
            ticker=seed["ticker"],
            issuer=seed["issuer"],
            reporting_date=seed["reporting_date"],
            publication_date=seed["publication_date"],
            source=seed["source"],
            shares_outstanding=seed["shares_outstanding"],
            raw_top_holders=seed["top_shareholders"],
            domestic_pct=seed.get("domestic_pct"),
            foreign_pct=seed.get("foreign_pct"),
            investor_types=seed.get("investor_type_breakdown"),
            denominator_type=seed.get("denominator_type", DENOMINATOR_SHARES_OUTSTANDING),
            verification_status="UNVERIFIED",
        )
    return None


def reconcile_ownership(
    ticker: str,
    issuer: str,
    reporting_date: str,
    publication_date: str,
    source: str,
    shares_outstanding: float,
    raw_top_holders: list[dict],
    domestic_pct: float | None = None,
    foreign_pct: float | None = None,
    investor_types: dict[str, float] | None = None,
    denominator_type: str = DENOMINATOR_SHARES_OUTSTANDING,
    verification_status: str = "UNVERIFIED",
    regulatory_free_float_pct: float | None = None,
) -> OwnershipStructure:
    """Reconciles shareholder disclosures into a consistent, mathematically sound ownership model."""
    if not source or not str(source).strip():
        raise ValueError("Source documentation URL or reference is required")
    if shares_outstanding <= 0:
        raise ValueError("Shares outstanding must be positive")
    if denominator_type not in (DENOMINATOR_SHARES_OUTSTANDING, DENOMINATOR_REGISTERED_HOLDINGS):
        raise ValueError(f"Unknown denominator type: {denominator_type}")

    top_holders: list[ShareholderRecord] = []
    top_pct_sum = 0.0
    seen_holders: set[str] = set()

    for h in raw_top_holders:
        name = str(h.get("shareholder", "")).strip()
        if not name:
            raise ValueError("Shareholder name cannot be empty")
        name_key = name.lower()
        if name_key in seen_holders:
            raise ValueError(f"Duplicate shareholder record '{name}' detected in ownership disclosure")
        seen_holders.add(name_key)

        itype = str(h.get("investor_type", "Others")).strip()
        shares = float(h.get("shares_held", 0.0))
        pct = float(h.get("percentage", 0.0))

        if shares < 0:
            raise ValueError(f"Share holdings cannot be negative for holder '{name}'")
        if pct < 0.0 or pct > 100.0:
            raise ValueError(f"Shareholder percentage {pct}% is outside valid bounds [0, 100] for '{name}'")

        h_denom = h.get("denominator_type")
        if h_denom and h_denom != denominator_type:
            raise ValueError(f"Mixed denominator types cannot be combined: holder '{name}' uses '{h_denom}' vs structure '{denominator_type}'")

        # Mathematical agreement check
        if pct <= 0 and shares > 0:
            pct = (shares / shares_outstanding) * 100.0
        elif shares <= 0 and pct > 0:
            shares = (pct / 100.0) * shares_outstanding
        elif shares > 0 and pct > 0:
            expected_pct = (shares / shares_outstanding) * 100.0
            if abs(expected_pct - pct) > 1.0:
                raise ValueError(
                    f"Conflicting shares ({shares:,.0f}) and percentage ({pct:.2f}%) for holder '{name}'; expected ~{expected_pct:.2f}%"
                )

        top_pct_sum += pct
        top_holders.append(
            ShareholderRecord(
                issuer=issuer,
                ticker=ticker,
                reporting_date=reporting_date,
                publication_date=publication_date,
                shareholder=name,
                investor_type=itype,
                shares_held=shares,
                percentage=round(pct, 4),
                denominator_type=denominator_type,
                source=source,
                verification_status=verification_status,
            )
        )

    if top_pct_sum > 100.01:
        raise ValueError(f"Total shareholder percentages ({top_pct_sum:.2f}%) exceed 100%")

    unclassified_remainder = max(0.0, round(100.0 - top_pct_sum, 4))

    # Domestic vs Foreign: do not default to 60/40!
    dom = domestic_pct
    forn = foreign_pct
    if dom is not None and forn is not None:
        if dom + forn > 100.01:
            raise ValueError(f"Domestic ({dom:.2f}%) and Foreign ({forn:.2f}%) sum exceeds 100%")

    inv_breakdown = dict(investor_types or {})
    if not inv_breakdown:
        inv_breakdown = {
            "Top Disclosed Holders (>5%)": round(top_pct_sum, 2),
            "Unclassified Remainder (<5%)": round(unclassified_remainder, 2),
        }

    denom_note = (
        "Persentase dihitung terhadap total saham beredar (shares outstanding). "
        "Laporan kepemilikan >5% mencakup pemegang saham utama/pengendali yang dilaporkan. "
        "Sisa kepemilikan merupakan sisa yang tidak terklasifikasi (<5%), bukan free float regulasi yang disahkan atau pemegang perorangan terselubung."
        if denominator_type == DENOMINATOR_SHARES_OUTSTANDING
        else "Persentase dihitung terhadap total efek terdaftar dalam KSEI (registered holdings)."
    )

    reconciliation_notes = (
        f"Reconciled {len(top_holders)} major holder(s) totalling {top_pct_sum:.2f}%; "
        f"unclassified remainder {unclassified_remainder:.2f}%."
    )
    if regulatory_free_float_pct is not None:
        reconciliation_notes += f" Disclosed regulatory free float: {regulatory_free_float_pct:.2f}%."

    return OwnershipStructure(
        ticker=ticker,
        issuer=issuer,
        reporting_date=reporting_date,
        publication_date=publication_date,
        source=source,
        shares_outstanding=shares_outstanding,
        denominator_type=denominator_type,
        top_shareholders=top_holders,
        public_shareholders_pct=unclassified_remainder,
        domestic_pct=dom,
        foreign_pct=forn,
        investor_type_breakdown=inv_breakdown,
        reconciled=True,
        reconciliation_notes=reconciliation_notes,
        denominator_explanation=denom_note,
        verification_status=verification_status,
        regulatory_free_float_pct=regulatory_free_float_pct,
    )


def load_ownership(symbol: str, root: Path) -> OwnershipStructure | None:
    """Loads ownership structure for a symbol from local imported files only."""
    sym = symbol.strip().upper()
    file_path = root / f"data/equities/ownership/{sym}.json"
    if file_path.exists():
        try:
            data = json.loads(file_path.read_text(encoding="utf-8"))
            return reconcile_ownership(
                ticker=data["ticker"],
                issuer=data.get("issuer", sym),
                reporting_date=data["reporting_date"],
                publication_date=data.get("publication_date", data["reporting_date"]),
                source=data.get("source", "https://www.idx.co.id/"),
                shares_outstanding=float(data["shares_outstanding"]),
                raw_top_holders=data.get("top_shareholders", []),
                domestic_pct=data.get("domestic_pct"),
                foreign_pct=data.get("foreign_pct"),
                investor_types=data.get("investor_type_breakdown"),
                denominator_type=data.get("denominator_type", DENOMINATOR_SHARES_OUTSTANDING),
                verification_status="USER_IMPORTED",
                regulatory_free_float_pct=data.get("regulatory_free_float_pct"),
            )
        except Exception:
            pass

    return None


def import_ownership_file(path: Path, root: Path) -> str:
    """Validates and imports an official ownership disclosure file."""
    if path.stat().st_size > 10_000_000:
        raise ValueError("Ownership file exceeds import limit")

    if path.suffix.lower() == ".csv":
        with path.open(encoding="utf-8-sig", newline="") as f:
            reader = list(csv.DictReader(f))
        if not reader:
            raise ValueError("Empty ownership CSV")
        first = reader[0]
        ticker = str(first.get("ticker", "")).strip().upper()
        issuer = str(first.get("issuer", ticker)).strip()
        reporting_date = str(first.get("reporting_date", "")).strip()
        pub_date = str(first.get("publication_date", reporting_date)).strip()
        source = source_url(str(first.get("source", "https://www.idx.co.id/")))
        shares_out = float(first.get("shares_outstanding", 0))
        top_holders = []
        for r in reader:
            top_holders.append({
                "shareholder": r.get("shareholder", ""),
                "investor_type": r.get("investor_type", "Others"),
                "shares_held": float(r.get("shares_held", 0)),
                "percentage": float(r.get("percentage", 0)),
            })
        structure = reconcile_ownership(
            ticker=ticker,
            issuer=issuer,
            reporting_date=reporting_date,
            publication_date=pub_date,
            source=source,
            shares_outstanding=shares_out,
            raw_top_holders=top_holders,
            verification_status="USER_IMPORTED",
        )
    else:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not scan_text(json.dumps(data))["passed"]:
            raise ValueError("Unsafe ownership metadata")
        ticker = str(data["ticker"]).strip().upper()
        structure = reconcile_ownership(
            ticker=ticker,
            issuer=data.get("issuer", ticker),
            reporting_date=data["reporting_date"],
            publication_date=data.get("publication_date", data["reporting_date"]),
            source=source_url(data.get("source", "https://www.idx.co.id/")),
            shares_outstanding=float(data["shares_outstanding"]),
            raw_top_holders=data.get("top_shareholders", []),
            domestic_pct=data.get("domestic_pct"),
            foreign_pct=data.get("foreign_pct"),
            investor_types=data.get("investor_type_breakdown"),
            denominator_type=data.get("denominator_type", DENOMINATOR_SHARES_OUTSTANDING),
            verification_status="USER_IMPORTED",
            regulatory_free_float_pct=data.get("regulatory_free_float_pct"),
        )

    out_dir = root / "data/equities/ownership"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_file = out_dir / f"{ticker}.json"
    out_file.write_text(json.dumps(structure.to_dict(), indent=2), encoding="utf-8")
    return ticker
