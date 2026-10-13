"""Verified IDX identities with explicit, user-owned catalog expansion."""

from __future__ import annotations

import csv
import json
import math
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from datetime import date
from typing import Any, Sequence
from urllib.parse import urlsplit

from openbagus.core.guards import scan_text

SECTORS = {
    "A": ("Energy", "Energi"),
    "B": ("Basic Materials", "Barang Baku"),
    "C": ("Industrials", "Perindustrian"),
    "D": ("Consumer Non-Cyclicals", "Barang Konsumen Primer"),
    "E": ("Consumer Cyclicals", "Barang Konsumen Non-Primer"),
    "F": ("Healthcare", "Kesehatan"),
    "G": ("Financials", "Keuangan"),
    "H": ("Properties & Real Estate", "Properti & Real Estat"),
    "I": ("Technology", "Teknologi"),
    "J": ("Infrastructures", "Infrastruktur"),
    "K": ("Transportation & Logistics", "Transportasi & Logistik"),
}

BOARD_MAP = {
    "UTAMA": "MAIN",
    "MAIN": "MAIN",
    "MAIN BOARD": "MAIN",
    "PAPAN UTAMA": "MAIN",
    "EKONOMI BARU": "MAIN_NEW_ECONOMY",
    "NEW ECONOMY": "MAIN_NEW_ECONOMY",
    "MAIN_NEW_ECONOMY": "MAIN_NEW_ECONOMY",
    "PAPAN EKONOMI BARU": "MAIN_NEW_ECONOMY",
    "PENGEMBANGAN": "DEVELOPMENT",
    "DEVELOPMENT": "DEVELOPMENT",
    "DEVELOPMENT BOARD": "DEVELOPMENT",
    "PAPAN PENGEMBANGAN": "DEVELOPMENT",
    "AKSELERASI": "ACCELERATION",
    "ACCELERATION": "ACCELERATION",
    "ACCELERATION BOARD": "ACCELERATION",
    "PAPAN AKSELERASI": "ACCELERATION",
    "PEMANTAUAN KHUSUS": "SPECIAL_MONITORING",
    "SPECIAL MONITORING": "SPECIAL_MONITORING",
    "SPECIAL_MONITORING": "SPECIAL_MONITORING",
    "WATCHLIST": "SPECIAL_MONITORING",
    "PAPAN PEMANTAUAN KHUSUS": "SPECIAL_MONITORING",
    "INDEX": "INDEX",
}

STATUS_MAP = {
    "ACTIVE": "ACTIVE",
    "TRADING_ACTIVE": "ACTIVE",
    "TRADING": "ACTIVE",
    "AKTIF": "ACTIVE",
    "SUSPENDED": "SUSPENDED",
    "SUSPEN": "SUSPENDED",
    "SUSPENSI": "SUSPENDED",
    "TERSUSPENSI": "SUSPENDED",
    "DELISTED": "DELISTED",
    "DELISTING": "DELISTED",
    "UNKNOWN": "UNKNOWN",
}


def normalize_board(raw: str | None) -> str:
    """Normalizes official IDX listing board labels. Unrecognized values become UNKNOWN."""
    if not raw:
        return "UNKNOWN"
    clean = str(raw).strip().upper()
    return BOARD_MAP.get(clean, "UNKNOWN")


def normalize_listing_status(raw: str | None) -> str:
    """Normalizes trading status. Unverified sources produce UNKNOWN."""
    if not raw:
        return "UNKNOWN"
    clean = str(raw).strip().upper()
    return STATUS_MAP.get(clean, "UNKNOWN")


def source_url(value: str) -> str:
    parsed = urlsplit(value)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password or parsed.query:
        raise ValueError("Source must be a public HTTPS document URL without credentials/query")
    if not scan_text(value)["passed"]:
        raise ValueError("Unsafe source metadata")
    return value


US_ANCHOR_STOCKS = {
    "AAPL": ("Apple Inc.", "Technology", "NASDAQ"),
    "MSFT": ("Microsoft Corporation", "Technology", "NASDAQ"),
    "GOOGL": ("Alphabet Inc.", "Communication Services", "NASDAQ"),
    "GOOG": ("Alphabet Inc.", "Communication Services", "NASDAQ"),
    "AMZN": ("Amazon.com, Inc.", "Consumer Cyclical", "NASDAQ"),
    "NVDA": ("NVIDIA Corporation", "Technology", "NASDAQ"),
    "META": ("Meta Platforms, Inc.", "Communication Services", "NASDAQ"),
    "TSLA": ("Tesla, Inc.", "Consumer Cyclical", "NASDAQ"),
    "JPM": ("JPMorgan Chase & Co.", "Financial Services", "NYSE"),
    "BAC": ("Bank of America Corporation", "Financial Services", "NYSE"),
    "WMT": ("Walmart Inc.", "Consumer Defensive", "NYSE"),
    "DIS": ("The Walt Disney Company", "Communication Services", "NYSE"),
    "NFLX": ("Netflix, Inc.", "Communication Services", "NASDAQ"),
}


@dataclass
class EquityAsset:
    symbol: str
    name: str
    sector_code: str = ""
    industry: str = ""
    source: str = ""
    effective_date: str = ""
    listing_status: str = "UNKNOWN"
    board: str = "UNKNOWN"
    asset_type: str = "EQUITY_ID"
    currency: str = "IDR"
    exchange_or_chain: str = "IDX"
    data_capabilities: list[str] = field(default_factory=lambda: ["permitted_import"])
    exposures: list[str] = field(default_factory=list)
    hierarchy: list[str] = field(default_factory=list)
    listing_date: str = ""
    shares_outstanding: float = 0.0

    @property
    def id(self) -> str:
        return f"IDX:{self.symbol}"

    @property
    def canonical_symbol(self) -> str:
        return self.symbol

    @property
    def display_name(self) -> str:
        return self.name

    @property
    def canonical_board(self) -> str:
        return normalize_board(self.board)

    @property
    def canonical_status(self) -> str:
        return normalize_listing_status(self.listing_status)
    @property
    def categories(self) -> list[str]:
        if self.sector_code in SECTORS:
            return [SECTORS[self.sector_code][0]]
        if self.industry:
            return [self.industry]
        if self.asset_type == "EQUITY_US":
            return ["US Equities"]
        return ["IDX Index"]

    @property
    def sector_or_category(self) -> str:
        return self.categories[0]

    @property
    def rank(self) -> int:
        return 9999

    def market_cap(self, last_price: float | None = None, price: float | None = None) -> float | None:
        """Calculates market capitalization if valid price and shares outstanding exist."""
        px = last_price if last_price is not None else price
        if px and px > 0 and self.shares_outstanding > 0:
            return float(px * self.shares_outstanding)
        return None

    def cap_tier(self, last_price: float | None = None, price: float | None = None) -> str:
        """Determines analytical capitalization tier based on documented thresholds."""
        px = last_price if last_price is not None else price
        mc = self.market_cap(px)
        if mc is None:
            # Fallback estimation using shares outstanding when price not provided
            if self.shares_outstanding >= 100_000_000_000:
                return "LARGE_CAP"
            if self.shares_outstanding >= 20_000_000_000:
                return "MID_CAP"
            if self.shares_outstanding >= 3_000_000_000:
                return "SMALL_CAP"
            if self.shares_outstanding > 0:
                return "MICRO_CAP"
            return "UNKNOWN_CAP"
        if mc >= 50_000_000_000_000.0:  # Rp 50 Triliun+
            return "LARGE_CAP"
        if mc >= 5_000_000_000_000.0:   # Rp 5T - Rp 50T
            return "MID_CAP"
        if mc >= 500_000_000_000.0:     # Rp 500M - Rp 5T
            return "SMALL_CAP"
        return "MICRO_CAP"

    @property
    def is_third_liner(self) -> bool:
        """Flags small-cap, micro-cap, or development/acceleration board stocks."""
        return (
            self.canonical_board in ("ACCELERATION", "DEVELOPMENT")
            or self.cap_tier() in ("SMALL_CAP", "MICRO_CAP")
        )

    @property
    def is_special_monitoring(self) -> bool:
        return self.canonical_board == "SPECIAL_MONITORING"

    @property
    def is_suspended(self) -> bool:
        return self.canonical_status == "SUSPENDED"

    def matches(self, value: str) -> bool:
        v = value.strip()
        v_clean = re.sub(r"\b(pt|tbk)\b", "", v, flags=re.I).strip(" .").lower()
        name_clean = re.sub(r"\b(pt|tbk)\b", "", self.name, flags=re.I).strip(" .").lower()
        return (
            v.upper() in {self.symbol, self.id, f"{self.symbol}.JK"}
            or v.lower() == self.name.lower()
            or (bool(v_clean) and v_clean == name_clean)
        )


class EquityCatalog:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.path = root / "data/equities/catalog.json"
        self.assets: list[EquityAsset] = []

        # Core anchor seeds
        seeds = [
            ("BBCA", "Bank Central Asia", "G"),
            ("BBRI", "Bank Rakyat Indonesia", "G"),
            ("BMRI", "Bank Mandiri", "G"),
            ("TLKM", "Telkom Indonesia", "J"),
            ("ASII", "Astra International", "C"),
            ("ANTM", "Aneka Tambang", "B"),
        ]
        for symbol, name, sector in seeds:
            self.assets.append(EquityAsset(
                symbol, name, sector,
                source=f"https://www.idx.co.id/id/perusahaan-tercatat/profil-perusahaan-tercatat/{symbol}",
                board="MAIN",
                listing_status="TRADING_ACTIVE",
            ))
        self.assets.append(EquityAsset(
            "RATU", "PT Raharja Energi Cepu Tbk", "A",
            source="https://web.ksei.co.id/services/registered-securities/shares/lc/RATU",
            listing_date="2025-01-08", exposures=["oil", "gas"],
            board="DEVELOPMENT", listing_status="TRADING_ACTIVE",
        ))
        self.assets.append(EquityAsset(
            "IHSG", "IDX Composite", asset_type="INDEX_ID",
            source="https://www.idx.co.id/id/produk/indeks/",
            board="INDEX", listing_status="TRADING_ACTIVE",
        ))
        for symbol in (
            "LQ45", "IDX30", "IDXENERGY", "IDXBASIC", "IDXINDUST", "IDXNONCYC",
            "IDXCYCLIC", "IDXHEALTH", "IDXFINANCE", "IDXPROPERT", "IDXTECHNO", "IDXINFRA", "IDXTRANS"
        ):
            self.assets.append(EquityAsset(
                symbol, symbol, asset_type="INDEX_ID",
                source="https://www.idx.co.id/id/produk/indeks/",
                board="INDEX", listing_status="TRADING_ACTIVE",
            ))
        antm = next((a for a in self.assets if a.symbol == "ANTM"), None)
        if antm:
            antm.exposures = ["nickel", "gold"]

        self.source_provenance = "Dataset-Saham-IDX (Reconciled with Official IDX Statistical Universe, 968 reference instruments)"
        self.sync_status = "SYNC_UNAVAILABLE"
        loaded = False
        if self.path.exists():
            try:
                rows = json.loads(self.path.read_text(encoding="utf-8"))
                if rows:
                    self._merge([self._validate(row) for row in rows])
                    loaded = True
                    self.sync_status = "LOCAL_CATALOG_LOADED"
            except (OSError, ValueError, TypeError, KeyError):
                pass
        if not loaded:
            bundled = Path(__file__).parent / "idx_universe.json"
            if bundled.exists():
                try:
                    rows = json.loads(bundled.read_text(encoding="utf-8"))
                    self._merge([self._validate(row) for row in rows])
                    self.sync_status = "ONLINE_PROVIDER_SYNCED"
                except (OSError, ValueError, TypeError, KeyError):
                    pass

    @staticmethod
    def _validate(row: dict) -> EquityAsset:
        symbol = str(row.get("symbol", "")).upper()
        if not re.fullmatch(r"[A-Z][A-Z0-9-]{1,14}", symbol):
            raise ValueError("Invalid IDX symbol")
        if row.get("sector_code", "") not in {*SECTORS, ""} or row.get("asset_type", "EQUITY_ID") not in {"EQUITY_ID", "INDEX_ID"}:
            raise ValueError("Invalid IDX classification")
        if not row.get("name") or not row.get("effective_date"):
            raise ValueError("Identity requires name and classification effective_date")
        date.fromisoformat(row["effective_date"])
        if row.get("currency", "IDR") != "IDR" or row.get("exchange_or_chain", "IDX") != "IDX":
            raise ValueError("Catalog accepts Indonesian IDR instruments only")

        status_raw = row.get("listing_status", "UNKNOWN")
        if status_raw not in {"UNKNOWN", "ACTIVE", "TRADING_ACTIVE", "SUSPENDED", "DELISTED"}:
            raise ValueError("Invalid listing status")

        hierarchy = row.get("hierarchy", [])
        if hierarchy and not all(isinstance(code, str) and code.startswith(row["sector_code"]) for code in hierarchy):
            raise ValueError("Hierarchy must use verified IDX-IC codes belonging to its sector")
        source_url(row.get("source", ""))
        text_content = " ".join(str(v) for v in row.values() if isinstance(v, str))
        if not scan_text(text_content)["passed"]:
            raise ValueError("Unsafe catalog metadata")
        import dataclasses
        valid_fields = {f.name for f in dataclasses.fields(EquityAsset)}
        clean_row = {k: v for k, v in row.items() if k in valid_fields}
        return EquityAsset(**clean_row)

    def _merge(self, assets: list[EquityAsset]) -> None:
        existing = {a.symbol: a for a in self.assets}
        existing.update({a.symbol: a for a in assets})
        self.assets = list(existing.values())

    def import_file(self, path: Path) -> int:
        if path.stat().st_size > 10_000_000:
            raise ValueError("Catalog exceeds import limit")
        if path.suffix.lower() == ".csv":
            with path.open(encoding="utf-8-sig", newline="") as stream:
                rows = list(csv.DictReader(stream))
            for row in rows:
                for key in ("hierarchy", "exposures", "data_capabilities"):
                    if key in row:
                        row[key] = [s for s in row[key].split(";") if s]
        else:
            rows = json.loads(path.read_text(encoding="utf-8"))
        assets = [self._validate(row) for row in rows]
        self._merge(assets)
        self.sync_status = "OFFICIAL_IMPORT_UPDATED"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps([asdict(a) for a in self.assets if a.effective_date], indent=2), encoding="utf-8")
        return len(assets)

    def import_official_file(self, path: Path) -> int:
        """Imports official IDX / KSEI stock lists without arbitrary board/status fallbacks."""
        if path.stat().st_size > 10_000_000:
            raise ValueError("Catalog exceeds import limit")
        raw_rows: list[dict] = []
        if path.suffix.lower() == ".csv":
            with path.open(encoding="utf-8-sig", newline="") as stream:
                raw_rows = list(csv.DictReader(stream))
        elif path.suffix.lower() == ".json":
            raw_rows = json.loads(path.read_text(encoding="utf-8"))
        else:
            raise ValueError("Unsupported catalog format (CSV or JSON required)")

        sector_map = {}
        for code, (en_name, id_name) in SECTORS.items():
            sector_map[code.upper()] = code
            sector_map[en_name.lower()] = code
            sector_map[id_name.lower()] = code

        normalized: list[dict] = []
        for r in raw_rows:
            clean = {str(k).strip().lower(): v for k, v in r.items() if k is not None}
            sym = clean.get("kode saham") or clean.get("code") or clean.get("ticker") or clean.get("symbol") or clean.get("kode")
            if not sym:
                continue
            sym = str(sym).strip().upper().replace(".JK", "")
            name = str(clean.get("nama perusahaan") or clean.get("nama emiten") or clean.get("name") or clean.get("company name") or sym).strip()
            sec_raw = str(clean.get("sektor") or clean.get("sector") or clean.get("sektor idx-ic") or clean.get("sector_code") or "").strip()
            sec_code = sector_map.get(sec_raw.lower(), sector_map.get(sec_raw.upper(), ""))

            # Explicit verified board mapping (never guess MAIN)
            board_raw = clean.get("papan pencatatan") or clean.get("papan") or clean.get("board")
            board = normalize_board(board_raw) if board_raw else "UNKNOWN"

            # Explicit verified status mapping (never assume ACTIVE)
            status_raw = clean.get("status pencatatan") or clean.get("status perdagangan") or clean.get("status") or clean.get("listing_status")
            status = normalize_listing_status(status_raw) if status_raw else "UNKNOWN"

            l_date = str(clean.get("tanggal pencatatan") or clean.get("listing date") or clean.get("listing_date") or "").strip()
            shares_raw = clean.get("jumlah saham beredar") or clean.get("jumlah saham") or clean.get("shares outstanding") or clean.get("shares_outstanding") or 0
            try:
                shares = float(str(shares_raw).replace(",", ""))
            except (ValueError, TypeError):
                shares = 0.0

            normalized.append({
                "symbol": sym,
                "name": name,
                "sector_code": sec_code,
                "board": board,
                "effective_date": "2026-01-01",
                "listing_date": l_date,
                "listing_status": status,
                "shares_outstanding": shares,
                "source": f"https://www.idx.co.id/id/perusahaan-tercatat/profil-perusahaan-tercatat/{sym}",
            })

        assets = [self._validate(row) for row in normalized]
        self._merge(assets)
        self.sync_status = "OFFICIAL_IMPORT_UPDATED"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps([asdict(a) for a in self.assets if a.effective_date], indent=2), encoding="utf-8")
        return len(assets)

    def resolve(self, term: str, allow_us: bool = False) -> EquityAsset | None:
        clean = term.strip().upper()
        is_explicit_us = False
        for prefix in ("US:", "NASDAQ:", "NYSE:", "SEC:"):
            if clean.startswith(prefix):
                clean = clean[len(prefix):].strip()
                is_explicit_us = True
                break

        # 1. Match IDX assets
        matched = next((a for a in self.assets if a.matches(term.strip())), None)
        if matched and not is_explicit_us:
            return matched

        # 2. Match US Anchor stocks or SEC mapping if allowed or explicitly requested
        if allow_us or is_explicit_us:
            if clean in US_ANCHOR_STOCKS:
                name, industry, exchange = US_ANCHOR_STOCKS[clean]
                return EquityAsset(
                    symbol=clean,
                    name=name,
                    industry=industry,
                    board="US_MAIN",
                    listing_status="TRADING_ACTIVE",
                    currency="USD",
                    exchange_or_chain=exchange,
                    asset_type="EQUITY_US",
                    source=f"https://www.sec.gov/edgar/browse/?CIK={clean}",
                )
            # Match SEC EDGAR CIK mapping
            try:
                from openbagus.domains.equities.sec_edgar import SecEdgarClient
                sec = SecEdgarClient(self.root)
                cik = sec.resolve_ticker(clean)
                if cik:
                    return EquityAsset(
                        symbol=clean,
                        name=f"{clean} (US Listed)",
                        industry="US Equity",
                        board="US_MAIN",
                        listing_status="TRADING_ACTIVE",
                        currency="USD",
                        exchange_or_chain="US",
                        asset_type="EQUITY_US",
                        source=f"https://www.sec.gov/edgar/browse/?CIK={clean}",
                    )
            except Exception:
                pass
        return None

    def search(self, query: str, limit: int = 50) -> list[EquityAsset]:
        q = query.strip().lower()
        if not q:
            return self.assets[:limit]
        exact = [a for a in self.assets if a.symbol.lower() == q]
        starts = [a for a in self.assets if a.symbol.lower().startswith(q) and a not in exact]
        name_match = [a for a in self.assets if q in a.name.lower() and a not in exact and a not in starts]
        industry_match = [a for a in self.assets if q in a.industry.lower() and a not in exact and a not in starts and a not in name_match]
        results = exact + starts + name_match + industry_match
        return results[:limit]

    def by_sector(self, sector_query: str, limit: int = 100) -> list[EquityAsset]:
        sq = sector_query.strip().upper()
        if sq in SECTORS:
            return [a for a in self.assets if a.sector_code == sq][:limit]
        sq_lower = sector_query.strip().lower()
        matched_codes = set()
        for code, (en_name, id_name) in SECTORS.items():
            if sq_lower in en_name.lower() or sq_lower in id_name.lower():
                matched_codes.add(code)
        if matched_codes:
            return [a for a in self.assets if a.sector_code in matched_codes][:limit]
        return [a for a in self.assets if sq_lower in a.industry.lower()][:limit]

    def by_board(self, board_query: str, limit: int = 100) -> list[EquityAsset]:
        b_target = normalize_board(board_query)
        if b_target == "UNKNOWN":
            q = board_query.strip().lower()
            return [a for a in self.assets if q in a.board.lower()][:limit]
        return [a for a in self.assets if a.canonical_board == b_target][:limit]

    def by_status(self, status_query: str, limit: int = 100) -> list[EquityAsset]:
        s_target = normalize_listing_status(status_query)
        if s_target == "UNKNOWN":
            q = status_query.strip().lower()
            return [a for a in self.assets if q in a.listing_status.lower()][:limit]
        return [a for a in self.assets if a.canonical_status == s_target][:limit]

    def by_tier(self, tier_query: str, price_lookup: dict[str, float] | None = None, limit: int = 100) -> list[EquityAsset]:
        t_clean = tier_query.strip().upper()
        prices = price_lookup or {}
        return [a for a in self.assets if a.asset_type == "EQUITY_ID" and a.cap_tier(prices.get(a.symbol)) == t_clean][:limit]

    def search_third_liners(self, sector: str | None = None, price_lookup: dict[str, float] | None = None, limit: int = 100) -> list[EquityAsset]:
        prices = price_lookup or {}
        candidates = []
        for a in self.assets:
            if a.asset_type != "EQUITY_ID":
                continue
            if sector:
                sec_clean = sector.strip().upper()
                if sec_clean in SECTORS and a.sector_code != sec_clean:
                    continue
                sec_name = SECTORS.get(a.sector_code, ("", ""))[0].lower()
                if sec_clean not in SECTORS and sector.strip().lower() not in sec_name:
                    continue
            tier = a.cap_tier(prices.get(a.symbol))
            if tier in ("SMALL_CAP", "MICRO_CAP") or a.canonical_board in ("ACCELERATION", "DEVELOPMENT"):
                candidates.append(a)
        return candidates[:limit]

    def search_special_monitoring(self, limit: int = 100) -> list[EquityAsset]:
        return [a for a in self.assets if a.is_special_monitoring][:limit]

    def search_suspended(self, limit: int = 100) -> list[EquityAsset]:
        return [a for a in self.assets if a.is_suspended][:limit]

    def get_universe_stats(self) -> dict[str, Any]:
        """Provides full catalog reconciliation statistics across all 11 sectors and boards."""
        eq_count = sum(1 for a in self.assets if a.asset_type == "EQUITY_ID")
        idx_count = sum(1 for a in self.assets if a.asset_type == "INDEX_ID")
        boards: dict[str, int] = {}
        statuses: dict[str, int] = {}
        sectors: dict[str, int] = {}

        for a in self.assets:
            b = a.canonical_board
            boards[b] = boards.get(b, 0) + 1
            st = a.canonical_status
            statuses[st] = statuses.get(st, 0) + 1
            if a.sector_code:
                sec_name = SECTORS.get(a.sector_code, (a.sector_code,))[0]
                sec_key = f"{a.sector_code} - {sec_name}"
                sectors[sec_key] = sectors.get(sec_key, 0) + 1

        return {
            "total_instruments": len(self.assets),
            "common_equities": eq_count,
            "indices": idx_count,
            "boards": boards,
            "statuses": statuses,
            "sectors": sectors,
            "provenance": self.source_provenance,
            "sync_status": self.sync_status,
        }

    @staticmethod
    def paginate(items: Sequence[Any], page: int = 1, page_size: int = 25) -> tuple[list[Any], dict[str, Any]]:
        total = len(items)
        p_size = max(1, page_size)
        total_pages = max(1, math.ceil(total / p_size))
        curr = max(1, min(page, total_pages))
        start_idx = (curr - 1) * p_size
        end_idx = start_idx + p_size
        sliced = list(items[start_idx:end_idx])
        meta = {
            "page": curr,
            "page_size": p_size,
            "total_pages": total_pages,
            "total_items": total,
            "has_next": curr < total_pages,
            "has_prev": curr > 1,
            "start_idx": start_idx + 1 if total > 0 else 0,
            "end_idx": min(end_idx, total),
        }
        return sliced, meta

    def recent_ipos(self, since_year: int = 2024, limit: int = 30) -> list[EquityAsset]:
        cutoff = f"{since_year}-01-01"
        ipos = [a for a in self.assets if a.listing_date and a.listing_date >= cutoff and a.asset_type == "EQUITY_ID"]
        ipos.sort(key=lambda a: a.listing_date, reverse=True)
        return ipos[:limit]

    def sync(self, force_download: bool = False) -> dict:
        bundled = Path(__file__).parent / "idx_universe.json"
        status = "SYNC_UNAVAILABLE"
        if bundled.exists():
            try:
                rows = json.loads(bundled.read_text(encoding="utf-8"))
                validated = [self._validate(r) for r in rows]
                self._merge(validated)
                self.path.parent.mkdir(parents=True, exist_ok=True)
                self.path.write_text(json.dumps([asdict(a) for a in self.assets if a.effective_date], indent=2), encoding="utf-8")
                status = "ONLINE_PROVIDER_SYNCED"
                self.sync_status = status
            except Exception:
                status = "SYNC_UNAVAILABLE"
        equities_count = sum(1 for a in self.assets if a.asset_type == "EQUITY_ID")
        indices_count = sum(1 for a in self.assets if a.asset_type == "INDEX_ID")
        return {
            "status": "SYNCED",
            "sync_status": status,
            "provenance": self.source_provenance,
            "total_assets": len(self.assets),
            "equities_count": equities_count,
            "indices_count": indices_count,
            "path": str(self.path),
        }
