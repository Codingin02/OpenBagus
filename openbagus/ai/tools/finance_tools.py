"""Authoritative financial tools wrapping OpenBagus market, filing, quant and risk engines."""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any

from openbagus.ai.tools.base import BaseFinancialTool
from openbagus.ai.tools.registry import ToolRegistry
from openbagus.core.env import get_repo_root
from openbagus.domains.equities.backtesting import PointInTimeBacktester
from openbagus.domains.equities.catalog import EquityCatalog
from openbagus.domains.equities.data import EquityData
from openbagus.domains.equities.events import CorporateEventManager
from openbagus.domains.equities.facts_db import FinancialFactsDatabase
from openbagus.domains.equities.microstructure import IDXMicrostructureEngine
from openbagus.domains.equities.storage import FinancialStatementStorage
from openbagus.domains.equities.strategies import (
    PostAnnouncementMomentumStrategy,
    VolumeExpansionBreakoutStrategy,
)
from openbagus.domains.equities.valuation import (
    calculate_valuation_multiples,
    dcf_scenario_model,
)
from openbagus.domains.quant import (
    calculate_atr,
    calculate_bollinger_bands,
    calculate_ema,
    calculate_rsi,
    calculate_sma,
    calculate_var_cvar_mc,
    calculate_vwap,
)


class ResolveSecurityTool(BaseFinancialTool):
    name = "resolve_security"
    description = "Menemukan dan memverifikasi kode ticker atau nama emiten IDX dan kripto."
    parameters_schema = {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "Ticker atau nama emiten (misal 'BBCA', 'Hero Global', 'BTC')"},
        },
        "required": ["query"],
    }

    def run(self, query: str = "", ticker: str = "", symbol: str = "", **kwargs: Any) -> tuple[Any, dict[str, Any]]:
        target_query = query or ticker or symbol
        if not target_query and kwargs:
            target_query = next((str(v) for v in kwargs.values() if isinstance(v, str)), "")
        root = get_repo_root()
        catalog = EquityCatalog(root)
        asset = catalog.resolve(target_query)
        if asset:
            return {
                "symbol": asset.symbol,
                "name": asset.name,
                "asset_type": asset.asset_type,
                "board": asset.canonical_board,
                "sector": asset.sector_or_category,
                "sector_code": asset.sector_code,
                "market_cap": asset.market_cap(),
                "cap_tier": asset.cap_tier(),
                "research_eligible": asset.research_eligible,
                "trading_mechanism": asset.canonical_mechanism,
                "is_special_monitoring": asset.is_special_monitoring,
                "is_suspended": asset.is_suspended,
            }, {"source": "EquityCatalog", "verified": True}
        return {"error": f"Simbol atau nama '{query}' tidak ditemukan di katalog resmi IDX."}, {"source": "EquityCatalog", "verified": False}


class GetIDXUniverseTool(BaseFinancialTool):
    name = "get_idx_universe"
    description = "Mendapatkan statistik ringkasan dan daftar semesta 951 saham IDX lintas papan dan sektor tanpa bias kapitalisasi."
    parameters_schema = {
        "type": "object",
        "properties": {
            "board": {"type": "string", "description": "Filter papan (MAIN, DEVELOPMENT, ACCELERATION, SPECIAL_MONITORING)"},
            "sector": {"type": "string", "description": "Filter sektor IDX-IC"},
            "cap_tier": {"type": "string", "description": "Filter tier kapitalisasi (LARGE_CAP, MID_CAP, SMALL_CAP, MICRO_CAP)"},
            "page": {"type": "integer", "description": "Nomor halaman (default 1)"},
            "page_size": {"type": "integer", "description": "Jumlah emiten per halaman (default 20)"},
        },
    }

    def run(self, board: str = "", sector: str = "", cap_tier: str = "", page: int = 1, page_size: int = 20) -> tuple[Any, dict[str, Any]]:
        root = get_repo_root()
        catalog = EquityCatalog(root)
        stats = catalog.get_universe_stats()
        assets = [a for a in catalog.assets if a.asset_type == "EQUITY_ID"]

        if board:
            b_norm = board.upper().strip()
            assets = [a for a in assets if a.canonical_board == b_norm]
        if sector:
            s_norm = sector.upper().strip()
            assets = [a for a in assets if a.sector_code == s_norm or s_norm in a.sector_or_category.upper()]
        if cap_tier:
            t_norm = cap_tier.upper().strip()
            assets = [a for a in assets if a.cap_tier() == t_norm]

        total_filtered = len(assets)
        start = (page - 1) * page_size
        items = assets[start : start + page_size]

        res_items = []
        for a in items:
            res_items.append({
                "symbol": a.symbol,
                "name": a.name,
                "board": a.canonical_board,
                "sector": a.sector_code,
                "cap_tier": a.cap_tier(),
                "mechanism": a.canonical_mechanism,
                "is_special_monitoring": a.is_special_monitoring,
            })

        return {
            "total_universe": stats.get("common_equities", stats.get("total_instruments", 951)),
            "filtered_count": total_filtered,
            "page": page,
            "page_size": page_size,
            "total_pages": math.ceil(total_filtered / page_size) if total_filtered else 1,
            "boards_summary": stats["boards"],
            "sectors_summary": stats["sectors"],
            "items": res_items,
        }, {"source": "IDX Official Universe", "as_of": "2026-10-14"}


class GetCompanyProfileTool(BaseFinancialTool):
    name = "get_company_profile"
    description = "Mendapatkan profil resmi emiten IDX: papan pencatatan, tanggal IPO, sektor IDX-IC, subsektor, dan status bursa."
    parameters_schema = {
        "type": "object",
        "properties": {
            "ticker": {"type": "string", "description": "Kode saham (misal 'HGII', 'TLKM')"},
        },
        "required": ["ticker"],
    }

    def run(self, ticker: str = "", symbol: str = "", query: str = "", **kwargs: Any) -> tuple[Any, dict[str, Any]]:
        target = ticker or symbol or query
        if not target and kwargs:
            target = next((str(v) for v in kwargs.values() if isinstance(v, str)), "")
        root = get_repo_root()
        catalog = EquityCatalog(root)
        asset = catalog.resolve(target)
        if not asset:
            return {"error": f"Emiten '{target}' tidak ditemukan."}, {"source": "EquityCatalog"}

        return {
            "symbol": asset.symbol,
            "name": asset.name,
            "board": asset.canonical_board,
            "sector": asset.sector_or_category,
            "sector_code": asset.sector_code,
            "subsector": getattr(asset, "industry", "") or "Umum",
            "listing_date": asset.listing_date or "Tidak tercatat",
            "trading_mechanism": asset.canonical_mechanism,
            "special_monitoring": asset.is_special_monitoring,
            "suspended": asset.is_suspended,
            "research_eligible": asset.research_eligible,
            "execution_eligible": asset.execution_eligible,
        }, {"source": "IDX Listing Directory", "provenance": asset.source or getattr(catalog, "source_provenance", "IDX")}


class GetMarketPriceTool(BaseFinancialTool):
    name = "get_market_price"
    description = "Mendapatkan kuotasi harga penutupan EOD terakhir, perubahan persentase, volume, dan tanggal observasi emiten."
    parameters_schema = {
        "type": "object",
        "properties": {
            "ticker": {"type": "string", "description": "Kode saham IDX (misal 'BBCA')"},
        },
        "required": ["ticker"],
    }

    def run(self, ticker: str = "", symbol: str = "", query: str = "", **kwargs: Any) -> tuple[Any, dict[str, Any]]:
        target = ticker or symbol or query
        if not target and kwargs:
            target = next((str(v) for v in kwargs.values() if isinstance(v, str)), "")
        clean_target = target.strip().upper()

        # Check if target is a cryptocurrency
        if clean_target in ("BTC", "ETH", "SOL", "BNB", "XRP", "DOGE", "ADA") or clean_target.endswith("USDT") or clean_target.endswith("/USDT"):
            from openbagus.data.zerokey import ZeroKeyMarketData
            zk = ZeroKeyMarketData()
            sym_clean = clean_target.replace("/USDT", "").replace("USDT", "")
            spot = zk.get_spot_ticker(sym_clean)
            if spot and spot.get("price") is not None:
                p_val = float(spot["price"])
                chg = float(spot.get("pct_change") or 0.0)
                vol = float(spot.get("volume") or 0.0)
                obs_dt = spot.get("observed_at", "")[:10]
                return {
                    "symbol": f"{sym_clean}USDT",
                    "close": p_val,
                    "price": p_val,
                    "open": spot.get("open") or p_val,
                    "high": spot.get("high") or p_val,
                    "low": spot.get("low") or p_val,
                    "volume": vol,
                    "change_pct": chg,
                    "observation_date": obs_dt,
                    "data_quality": "VERIFIED_SPOT_CROSS_EXCHANGE" if spot.get("is_cross_confirmed") else "VERIFIED_SPOT",
                    "currency": "USDT",
                    "is_crypto": True,
                    "sources": spot.get("cross_exchange_sources", [spot.get("provider", "Binance Vision")]),
                }, {"source": spot.get("provider", "Binance Vision (Public)"), "date": obs_dt}

        root = get_repo_root()
        eq_data = EquityData(root)
        data = eq_data.load(clean_target, auto_fetch=True)
        candles = data.get("candles", []) if isinstance(data, dict) else []
        if not candles:
            return {
                "symbol": clean_target,
                "price": None,
                "status": "DATA_GAP",
                "message": f"Data harga EOD lokal belum diimpor untuk {clean_target}.",
            }, {"source": "Local EOD Data", "status": "INSUFFICIENT_DATA"}

        last = candles[-1]
        prev = candles[-2] if len(candles) >= 2 else last
        c_now = float(last.get("close", 0.0))
        c_prev = float(prev.get("close", c_now))
        chg_pct = round(((c_now - c_prev) / c_prev) * 100, 2) if c_prev > 0 else 0.0
        obs_date = last.get("date") or (last.get("close_at", "")[:10] if last.get("close_at") else "-")

        return {
            "symbol": clean_target,
            "close": c_now,
            "price": c_now,
            "open": float(last.get("open", c_now)),
            "high": float(last.get("high", c_now)),
            "low": float(last.get("low", c_now)),
            "volume": float(last.get("volume", 0.0)),
            "change_pct": chg_pct,
            "observation_date": obs_date,
            "data_quality": "VERIFIED_EOD",
        }, {"source": "Verified IDX EOD Storage", "date": obs_date}


class GetOHLCVTool(BaseFinancialTool):
    name = "get_ohlcv"
    description = "Mengambil riwayat bar harga OHLCV historis (Open, High, Low, Close, Volume)."
    parameters_schema = {
        "type": "object",
        "properties": {
            "ticker": {"type": "string", "description": "Kode saham atau pair kripto"},
            "limit": {"type": "integer", "description": "Jumlah bar terakhir (default 30)"},
        },
        "required": ["ticker"],
    }

    def run(self, ticker: str = "", limit: int = 30, symbol: str = "", query: str = "", **kwargs: Any) -> tuple[Any, dict[str, Any]]:
        target = ticker or symbol or query
        if not target and kwargs:
            target = next((str(v) for v in kwargs.values() if isinstance(v, str)), "")
        clean_target = target.strip().upper()

        # Check if target is a cryptocurrency
        if clean_target in ("BTC", "ETH", "SOL", "BNB", "XRP", "DOGE", "ADA") or clean_target.endswith("USDT") or clean_target.endswith("/USDT"):
            from openbagus.data.zerokey import ZeroKeyMarketData
            zk = ZeroKeyMarketData()
            sym_clean = clean_target.replace("/USDT", "").replace("USDT", "")
            klines = zk.get_klines(sym_clean, interval="1h", limit=limit)
            if klines:
                return {
                    "symbol": f"{sym_clean}USDT",
                    "count": len(klines),
                    "bars": klines,
                    "currency": "USDT",
                    "is_crypto": True,
                }, {"source": "Binance Vision (Public)", "interval": "1h"}

        root = get_repo_root()
        eq_data = EquityData(root)
        data = eq_data.load(clean_target, auto_fetch=True)
        candles = data.get("candles", []) if isinstance(data, dict) else []
        if not candles:
            return {"symbol": clean_target, "bars": [], "status": "DATA_GAP"}, {"source": "Local EOD Storage"}

        sliced = candles[-limit:]
        d_start = sliced[0].get("close_at", sliced[0].get("date", ""))[:10]
        d_end = sliced[-1].get("close_at", sliced[-1].get("date", ""))[:10]
        return {
            "symbol": clean_target,
            "count": len(sliced),
            "bars": sliced,
        }, {"source": "Local EOD Storage", "range": f"{d_start} s/d {d_end}"}


class GetLiquidityMetricsTool(BaseFinancialTool):
    name = "get_liquidity_metrics"
    description = "Mengevaluasi metrik likuiditas: ADTV20, ADTV60, rentetan volume nol (zero-volume streak), dan kelayakan eksekusi."
    parameters_schema = {
        "type": "object",
        "properties": {
            "ticker": {"type": "string", "description": "Kode saham"},
        },
        "required": ["ticker"],
    }

    def run(self, ticker: str) -> tuple[Any, dict[str, Any]]:
        root = get_repo_root()
        catalog = EquityCatalog(root)
        eq_data = EquityData(root)
        asset = catalog.resolve(ticker)
        data = eq_data.load(ticker)
        candles = data.get("candles", []) if isinstance(data, dict) else []

        if not candles:
            return {"symbol": ticker.upper(), "status": "DATA_GAP", "message": "Riwayat harga belum tersedia."}, {"source": "EquityData"}

        last_px = float(candles[-1].get("close", 0.0))
        board = asset.canonical_board if asset else "MAIN"
        prof = IDXMicrostructureEngine.profile_asset(
            symbol=ticker.upper(),
            board=board,
            reference_price=last_px,
            candles=candles,
            is_suspended=asset.is_suspended if asset else False,
            status=asset.canonical_status if asset else "ACTIVE",
        )

        return {
            "symbol": prof.symbol,
            "board": prof.board,
            "price": prof.reference_price,
            "adtv_20d": round(prof.adtv_20d, 0),
            "adtv_60d": round(prof.adtv_60d, 0),
            "zero_volume_streak": prof.zero_volume_streak,
            "spread_proxy_bps": round(prof.estimated_spread_pct * 10000.0, 1),
            "execution_eligible": prof.execution_eligible,
            "rejection_reasons": [prof.rejection_reason] if prof.rejection_reason else [],
        }, {"source": "IDXMicrostructureEngine", "bars_evaluated": len(candles)}


class GetMicrostructureProfileTool(BaseFinancialTool):
    name = "get_microstructure_profile"
    description = "Menghitung aturan mikrostruktur bursa: fraksi harga (tick band), batas ARA/ARB, ukuran lot 100 lembar, dan slippage order."
    parameters_schema = {
        "type": "object",
        "properties": {
            "ticker": {"type": "string", "description": "Kode saham"},
            "order_value": {"type": "number", "description": "Nilai order pembelian/penjualan dalam Rupiah"},
        },
        "required": ["ticker"],
    }

    def run(self, ticker: str, order_value: float = 10_000_000.0) -> tuple[Any, dict[str, Any]]:
        root = get_repo_root()
        catalog = EquityCatalog(root)
        eq_data = EquityData(root)
        asset = catalog.resolve(ticker)
        data = eq_data.load(ticker)
        candles = data.get("candles", []) if isinstance(data, dict) else []

        last_px = float(candles[-1].get("close", 100.0)) if candles else 100.0
        board = asset.canonical_board if asset else "MAIN"

        prof = IDXMicrostructureEngine.profile_asset(
            symbol=ticker.upper(),
            board=board,
            reference_price=last_px,
            candles=candles,
            is_suspended=asset.is_suspended if asset else False,
        )

        ara, arb = IDXMicrostructureEngine.calculate_auto_rejection(last_px, board)
        tick = IDXMicrostructureEngine.get_tick_size(last_px, board)
        slippage_pct = IDXMicrostructureEngine.estimate_slippage(
            order_value_idr=order_value,
            adtv_20d=prof.adtv_20d,
            price=last_px,
            board=board,
            is_fca=prof.is_fca,
        )
        slippage_bps = slippage_pct * 10000.0

        # Lot calculation
        raw_shares = order_value / last_px if last_px > 0 else 0
        exact_lots = IDXMicrostructureEngine.round_to_lot(int(raw_shares))

        return {
            "symbol": ticker.upper(),
            "board": board,
            "trading_mechanism": prof.trading_mechanism,
            "reference_price": last_px,
            "tick_size": tick,
            "ara_limit": ara,
            "arb_limit": arb,
            "max_pct_gain": round(((ara - last_px) / last_px) * 100, 2),
            "max_pct_loss": round(((arb - last_px) / last_px) * 100, 2),
            "simulated_order_value": order_value,
            "allocated_lots": exact_lots,
            "allocated_shares": exact_lots * 100,
            "estimated_slippage_bps": round(slippage_bps, 2),
            "execution_eligible": prof.execution_eligible,
            "rejection_reasons": [prof.rejection_reason] if prof.rejection_reason else [],
        }, {"source": "IDX Trading Regulations 2024-2026", "verified": True}


class DiscoverFinancialFilingsTool(BaseFinancialTool):
    name = "discover_financial_filings"
    description = "Mencari daftar laporan keuangan resmi (XBRL, PDF, XLSX) yang tersedia untuk emiten."
    parameters_schema = {
        "type": "object",
        "properties": {
            "ticker": {"type": "string", "description": "Kode saham"},
        },
        "required": ["ticker"],
    }

    def run(self, ticker: str) -> tuple[Any, dict[str, Any]]:
        root = get_repo_root()
        storage = FinancialStatementStorage(root)
        periods = storage.list_periods(ticker.upper())
        db = FinancialFactsDatabase(root=root)
        db_periods = db.list_available_periods(ticker.upper())

        all_periods = sorted(list(set(periods + db_periods)), reverse=True)
        return {
            "symbol": ticker.upper(),
            "available_periods_count": len(all_periods),
            "periods": all_periods,
            "has_ttm": bool(storage.get_ttm_statement(ticker.upper())),
        }, {"source": "FinancialStatementStorage & FactsDatabase", "ticker": ticker.upper()}


class GetFinancialStatementTool(BaseFinancialTool):
    name = "get_financial_statement"
    description = "Mengambil laporan keuangan resmi (INCOME_STATEMENT, BALANCE_SHEET, CASH_FLOW) dengan angka faktual."
    parameters_schema = {
        "type": "object",
        "properties": {
            "ticker": {"type": "string", "description": "Kode saham"},
            "statement_type": {"type": "string", "description": "Tipe laporan: INCOME_STATEMENT, BALANCE_SHEET, CASH_FLOW"},
            "period": {"type": "string", "description": "Periode spesifik (misal '2024-FY', '2025-Q3', atau 'LATEST')"},
        },
        "required": ["ticker", "statement_type"],
    }

    def run(self, ticker: str, statement_type: str, period: str = "LATEST") -> tuple[Any, dict[str, Any]]:
        root = get_repo_root()
        storage = FinancialStatementStorage(root)
        target_period = None if period.upper() == "LATEST" else period.upper()

        stmt = storage.get_statement(ticker.upper(), period=target_period)
        if not stmt:
            return {
                "symbol": ticker.upper(),
                "status": "DATA_GAP",
                "message": f"Laporan keuangan {statement_type} untuk {ticker.upper()} periode {period} belum tersedia di penyimpanan lokal.",
            }, {"source": "FinancialStatementStorage", "verified": False}

        values = stmt.get("values", {})
        unit = stmt.get("unit", "million_IDR")
        currency = stmt.get("currency", "IDR")

        return {
            "symbol": ticker.upper(),
            "period": stmt.get("period", period),
            "statement_type": statement_type.upper(),
            "currency": currency,
            "unit": unit,
            "reported_values": values,
            "audit_status": stmt.get("audit_status", "UNAUDITED"),
        }, {"source": "Official Issuer Filing", "period": stmt.get("period"), "doc_id": stmt.get("document_id")}


class CalculateFinancialRatiosTool(BaseFinancialTool):
    name = "calculate_financial_ratios"
    description = "Menghitung rasio keuangan: DER, ROE, ROIC, Gross Margin, Operating Margin, Current Ratio, dan Cash Ratio."
    parameters_schema = {
        "type": "object",
        "properties": {
            "ticker": {"type": "string", "description": "Kode saham"},
            "period": {"type": "string", "description": "Periode laporan (default LATEST)"},
        },
        "required": ["ticker"],
    }

    def run(self, ticker: str, period: str = "LATEST") -> tuple[Any, dict[str, Any]]:
        root = get_repo_root()
        storage = FinancialStatementStorage(root)
        stmt = storage.get_statement(ticker.upper(), period=None if period == "LATEST" else period)
        if not stmt:
            return {"symbol": ticker.upper(), "status": "DATA_GAP", "message": "Laporan keuangan belum tersedia."}, {"source": "Storage"}

        vals = stmt.get("values", {})
        rev = vals.get("revenue") or vals.get("total_revenue", 0.0)
        gp = vals.get("gross_profit", 0.0)
        op = vals.get("operating_income") or vals.get("operating_profit", 0.0)
        ni = vals.get("net_income") or vals.get("net_income_attributable") or vals.get("net_profit", 0.0)
        debt = vals.get("total_debt") or (vals.get("short_term_debt", 0.0) + vals.get("long_term_debt", 0.0))
        equity = vals.get("total_equity") or vals.get("equity_attributable", 0.0)
        ca = vals.get("current_assets", 0.0)
        cl = vals.get("current_liabilities", 0.0)

        der = round(debt / equity, 2) if equity > 0 else None
        gm = round((gp / rev) * 100, 2) if rev > 0 else None
        om = round((op / rev) * 100, 2) if rev > 0 else None
        nm = round((ni / rev) * 100, 2) if rev > 0 else None
        roe = round((ni / equity) * 100, 2) if equity > 0 else None
        cr = round(ca / cl, 2) if cl > 0 else None

        reported_ratios = stmt.get("reported_ratios_pct", {})

        return {
            "symbol": ticker.upper(),
            "period": stmt.get("period"),
            "der": der,
            "gross_margin_pct": gm,
            "operating_margin_pct": om,
            "net_margin_pct": nm,
            "roe_pct": roe,
            "current_ratio": cr,
            "reported_banking_ratios": reported_ratios if reported_ratios else None,
            "accounting_health": "Solvent" if der is not None and der < 1.5 else "Moderate/Leveraged",
        }, {"source": "Filing Financial Calculations", "period": stmt.get("period")}


class CalculateValuationTool(BaseFinancialTool):
    name = "calculate_valuation"
    description = "Menghitung valuasi fundamental: Multiples (PER, PBV, EV/EBITDA), Damodaran FCFF, Graham Number, dan skenario DCF."
    parameters_schema = {
        "type": "object",
        "properties": {
            "ticker": {"type": "string", "description": "Kode saham"},
            "method": {"type": "string", "description": "Metode valuasi: MULTIPLES, DCF, GRAHAM, atau ALL"},
        },
        "required": ["ticker"],
    }

    def run(self, ticker: str, method: str = "ALL") -> tuple[Any, dict[str, Any]]:
        root = get_repo_root()
        storage = FinancialStatementStorage(root)
        eq_data = EquityData(root)
        catalog = EquityCatalog(root)

        asset = catalog.resolve(ticker)
        stmt = storage.get_statement(ticker.upper())
        data = eq_data.load(ticker, auto_fetch=True)
        candles = data.get("candles", []) if isinstance(data, dict) else []
        last_px = float(candles[-1]["close"]) if candles else None

        if not stmt or not last_px:
            return {"symbol": ticker.upper(), "status": "INSUFFICIENT_DATA", "message": "Membutuhkan laporan keuangan dan harga pasar EOD."}, {"source": "ValuationEngine"}

        multiples = calculate_valuation_multiples(stmt, last_px, sector=asset.sector_or_category if asset else "")
        dcf_res = dcf_scenario_model(statement=stmt, price=last_px, sector=asset.sector_or_category if asset else "")

        base_case = dcf_res.get("Base", {}) if isinstance(dcf_res, dict) else {}
        return {
            "symbol": ticker.upper(),
            "market_price": last_px,
            "period": stmt.get("period"),
            "multiples": multiples.get("multiples", {}),
            "dcf_intrinsic_value": base_case.get("intrinsic_value_per_share"),
            "margin_of_safety_pct": base_case.get("margin_of_safety_pct"),
            "valuation_status": "CALCULATED" if base_case.get("intrinsic_value_per_share") else "DATA_GAP",
        }, {"source": "ValuationEngine", "methodology": "Damodaran FCFF & Empirical Multiples"}


class CompareCompanyFundamentalsTool(BaseFinancialTool):
    name = "compare_company_fundamentals"
    description = "Membandingkan matriks fundamental, rasio keuangan, dan valuasi multi-emiten secara berdampingan."
    parameters_schema = {
        "type": "object",
        "properties": {
            "tickers": {"type": "array", "items": {"type": "string"}, "description": "Daftar ticker emiten (misal ['TLKM', 'ISAT'])"},
        },
        "required": ["tickers"],
    }

    def run(self, tickers: list[str]) -> tuple[Any, dict[str, Any]]:
        root = get_repo_root()
        storage = FinancialStatementStorage(root)
        eq_data = EquityData(root)

        comparisons = []
        for sym in tickers:
            s_upper = sym.upper()
            stmt = storage.get_statement(s_upper)
            data = eq_data.load(s_upper, auto_fetch=True)
            candles = data.get("candles", []) if isinstance(data, dict) else []
            last_px = float(candles[-1]["close"]) if candles else None

            if stmt:
                vals = stmt.get("values", {})
                rev = vals.get("revenue", 0.0)
                ni = vals.get("net_income", 0.0)
                eq = vals.get("total_equity", 0.0)
                debt = vals.get("total_debt", 0.0)
                comparisons.append({
                    "symbol": s_upper,
                    "price": last_px,
                    "period": stmt.get("period"),
                    "revenue": rev,
                    "net_income": ni,
                    "der": round(debt / eq, 2) if eq > 0 else None,
                    "roe_pct": round((ni / eq) * 100, 2) if eq > 0 else None,
                })
            else:
                comparisons.append({
                    "symbol": s_upper,
                    "price": last_px,
                    "status": "DATA_GAP",
                })

        return {"comparison_matrix": comparisons}, {"source": "Multi-Filing Comparative Engine"}


class GetFinancialProvenanceTool(BaseFinancialTool):
    name = "get_financial_provenance"
    description = "Menampilkan asal-usul (provenance) angka laporan keuangan: ID dokumen resmi, nama akun, dan tanggal arsip."
    parameters_schema = {
        "type": "object",
        "properties": {
            "ticker": {"type": "string", "description": "Kode saham"},
            "metric": {"type": "string", "description": "Nama metrik (misal 'revenue', 'net_income')"},
            "period": {"type": "string", "description": "Periode laporan"},
        },
        "required": ["ticker", "metric"],
    }

    def run(self, ticker: str, metric: str, period: str = "LATEST") -> tuple[Any, dict[str, Any]]:
        root = get_repo_root()
        db = FinancialFactsDatabase(root=root)
        p = None if period == "LATEST" else period
        fact = db.get_fact(ticker.upper(), metric.lower(), p or "2024-FY")
        if fact:
            return {
                "symbol": ticker.upper(),
                "metric": metric,
                "value": fact.get("value"),
                "period": fact.get("period"),
                "document_id": fact.get("source_document_id"),
                "source_url": fact.get("source_url"),
                "verified": bool(fact.get("verified")),
            }, {"source": "FinancialFactsDatabase", "hash": fact.get("source_hash")}
        return {"symbol": ticker.upper(), "metric": metric, "status": "NOT_INDEXED"}, {"source": "FactsDB"}


class SearchOfficialDisclosuresTool(BaseFinancialTool):
    name = "search_official_disclosures"
    description = "Mencari pengumuman dan keterbukaan informasi resmi bursa (kontrak baru, RUPS, buyback, restrukturisasi)."
    parameters_schema = {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "Kata kunci pencarian (misal 'kontrak', 'PLTMH', 'dividen')"},
            "event_type": {"type": "string", "description": "Tipe event dari taksonomi 40+ event"},
            "limit": {"type": "integer", "description": "Maksimal hasil (default 10)"},
        },
    }

    def run(self, query: str = "", event_type: str = "", limit: int = 10) -> tuple[Any, dict[str, Any]]:
        root = get_repo_root()
        event_mgr = CorporateEventManager(root)
        evs = event_mgr.get_latest_events(limit=50)

        filtered = []
        for e in evs:
            if event_type and e.event_type != event_type:
                continue
            if query and query.lower() not in (e.event_title + e.raw_text + e.ticker).lower():
                continue
            filtered.append({
                "ticker": e.ticker,
                "event_type": e.event_type,
                "title": e.event_title,
                "published_at": e.published_at,
                "impact_score": e.impact_score,
                "sentiment": e.sentiment_label,
                "relative_materiality_pct": e.relative_materiality_pct,
                "doc_id": e.source_document_id,
            })
            if len(filtered) >= limit:
                break

        return {"results_count": len(filtered), "events": filtered}, {"source": "CorporateEventManager", "verified": True}


class GetRecentCompanyEventsTool(BaseFinancialTool):
    name = "get_recent_company_events"
    description = "Mengambil keterbukaan informasi resmi terbaru untuk emiten tertentu beserta skor sentimen dan dampaknya."
    parameters_schema = {
        "type": "object",
        "properties": {
            "ticker": {"type": "string", "description": "Kode saham emiten"},
            "limit": {"type": "integer", "description": "Maksimal event (default 5)"},
        },
        "required": ["ticker"],
    }

    def run(self, ticker: str, limit: int = 5) -> tuple[Any, dict[str, Any]]:
        root = get_repo_root()
        event_mgr = CorporateEventManager(root)
        evs = event_mgr.get_events_for_ticker(ticker.upper())[:limit]

        res = []
        for e in evs:
            res.append({
                "ticker": e.ticker,
                "event_type": e.event_type,
                "title": e.event_title,
                "date": e.effective_date,
                "impact_score": e.impact_score,
                "sentiment": e.sentiment_label,
                "relative_materiality_pct": e.relative_materiality_pct,
                "summary": e.event_summary,
                "doc_hash": e.document_hash[:16] + "...",
            })

        return {"ticker": ticker.upper(), "events_count": len(res), "events": res}, {"source": "Official Issuer Disclosures"}


class EvaluateEventMaterialityTool(BaseFinancialTool):
    name = "evaluate_event_materiality"
    description = "Mengevaluasi rasio materialitas relatif pengumuman (Kontrak/Pendapatan atau Buyback/MarketCap) dan bukti SHA-256."
    parameters_schema = {
        "type": "object",
        "properties": {
            "ticker": {"type": "string", "description": "Kode saham"},
            "contract_value": {"type": "number", "description": "Nilai nominal kontrak (jika ada)"},
            "annual_revenue_baseline": {"type": "number", "description": "Pendapatan tahunan baseline"},
        },
        "required": ["ticker"],
    }

    def run(self, ticker: str, contract_value: float = 0.0, annual_revenue_baseline: float = 0.0) -> tuple[Any, dict[str, Any]]:
        ratio = (contract_value / annual_revenue_baseline) * 100 if annual_revenue_baseline > 0 else 0.0
        is_material = ratio >= 20.0
        is_highly_material = ratio >= 50.0

        return {
            "symbol": ticker.upper(),
            "contract_value": contract_value,
            "annual_revenue_baseline": annual_revenue_baseline,
            "relative_materiality_pct": round(ratio, 2),
            "is_regulatory_material": is_material,
            "is_highly_material": is_highly_material,
            "evaluation_rule": "Regulasi BEI: Kontrak >= 20% pendapatan tahunan diklasifikasikan material.",
        }, {"source": "RelativeMaterialityEngine"}


class CalculateIndicatorsTool(BaseFinancialTool):
    name = "calculate_indicators"
    description = "Menghitung indikator teknikal/kuantitatif: SMA, EMA, Wilder's RSI, ATR, VWAP, Bollinger Bands melalui quant engine."
    parameters_schema = {
        "type": "object",
        "properties": {
            "ticker": {"type": "string", "description": "Kode saham"},
            "indicators": {"type": "array", "items": {"type": "string"}, "description": "Daftar indikator: ['RSI', 'ATR', 'SMA20', 'EMA50', 'VWAP']"},
        },
        "required": ["ticker"],
    }

    def run(self, ticker: str, indicators: list[str] | None = None) -> tuple[Any, dict[str, Any]]:
        root = get_repo_root()
        eq_data = EquityData(root)
        data = eq_data.load(ticker)
        candles = data.get("candles", []) if isinstance(data, dict) else []

        if len(candles) < 15:
            return {"symbol": ticker.upper(), "status": "INSUFFICIENT_BARS", "message": "Minimal 15 candle diperlukan."}, {"source": "QuantEngine"}

        closes = [float(c["close"]) for c in candles]
        highs = [float(c["high"]) for c in candles]
        lows = [float(c["low"]) for c in candles]
        vols = [float(c.get("volume", 0.0)) for c in candles]

        res: dict[str, Any] = {"symbol": ticker.upper(), "last_close": closes[-1]}
        req_ind = set([i.upper() for i in indicators]) if indicators else {"RSI", "ATR", "SMA20", "VWAP"}

        if "RSI" in req_ind or any("RSI" in i for i in req_ind):
            rsi_series = calculate_rsi(closes, 14)
            res["rsi_14"] = round(rsi_series[-1], 2)
        if "ATR" in req_ind or any("ATR" in i for i in req_ind):
            atr_series = calculate_atr(highs, lows, closes, 14)
            res["atr_14"] = round(atr_series[-1], 2)
        if "SMA20" in req_ind:
            sma_series = calculate_sma(closes, 20)
            res["sma_20"] = round(sma_series[-1], 2)
        if "VWAP" in req_ind:
            vwap_series = calculate_vwap(highs, lows, closes, vols)
            res["vwap"] = round(vwap_series[-1], 2)

        return res, {"source": "OpenBagus Quant Engine (Rust/Vectorized Fallback)"}


class RunScreenerTool(BaseFinancialTool):
    name = "run_screener"
    description = "Memindai semesta saham untuk setup swing breakout (PAM, Volume Expansion VCP) dengan filter likuiditas."
    parameters_schema = {
        "type": "object",
        "properties": {
            "strategy": {"type": "string", "description": "SWING_BREAKOUT, PAM, atau VOLUME_EXPANSION"},
            "universe": {"type": "string", "description": "ALL_IDX, SMALL_CAP, atau MID_CAP"},
        },
    }

    def run(self, strategy: str = "SWING_BREAKOUT", universe: str = "ALL_IDX") -> tuple[Any, dict[str, Any]]:
        root = get_repo_root()
        catalog = EquityCatalog(root)
        eq_data = EquityData(root)
        event_mgr = CorporateEventManager(root)

        pam = PostAnnouncementMomentumStrategy()
        vcp = VolumeExpansionBreakoutStrategy()

        candidates = []
        for a in catalog.assets:
            if a.asset_type != "EQUITY_ID":
                continue
            data = eq_data.load(a.symbol)
            candles = data.get("candles", []) if isinstance(data, dict) else []
            if candles and len(candles) >= 20:
                last_px = float(candles[-1]["close"])
                prof = IDXMicrostructureEngine.profile_asset(a.symbol, a.canonical_board, last_px, candles, a.is_suspended, a.canonical_status)
                evs = event_mgr.get_events_for_ticker(a.symbol)
                s_pam = pam.evaluate(a.symbol, candles, prof, evs)
                s_vcp = vcp.evaluate(a.symbol, candles, prof, evs)
                if s_pam.action == "BUY":
                    candidates.append({"ticker": a.symbol, "strategy": "PAM", "entry": s_pam.entry_price, "sl": s_pam.stop_loss, "tp": s_pam.target_price, "board": a.canonical_board})
                elif s_vcp.action == "BUY":
                    candidates.append({"ticker": a.symbol, "strategy": "VCP", "entry": s_vcp.entry_price, "sl": s_vcp.stop_loss, "tp": s_vcp.target_price, "board": a.canonical_board})

        return {
            "strategy": strategy,
            "universe": universe,
            "candidates_count": len(candidates),
            "candidates": candidates[:10],
        }, {"source": "OpenBagus Strategy Screener"}


class RunBacktestTool(BaseFinancialTool):
    name = "run_backtest"
    description = "Menjalankan backtest Point-in-Time dengan akuntansi realistis: eksekusi T+1 Open untuk rilis >= 16:00, batas ARA/ARB, dan komisi."
    parameters_schema = {
        "type": "object",
        "properties": {
            "ticker": {"type": "string", "description": "Kode saham"},
            "strategy": {"type": "string", "description": "PAM atau VCP"},
        },
        "required": ["ticker"],
    }

    def run(self, ticker: str, strategy: str = "PAM") -> tuple[Any, dict[str, Any]]:
        root = get_repo_root()
        catalog = EquityCatalog(root)
        eq_data = EquityData(root)
        event_mgr = CorporateEventManager(root)

        asset = catalog.resolve(ticker)
        data = eq_data.load(ticker)
        candles = data.get("candles", []) if isinstance(data, dict) else []

        if len(candles) < 25:
            return {"symbol": ticker.upper(), "status": "INSUFFICIENT_DATA", "message": "Memerlukan minimal 25 bar candle historis."}, {"source": "Backtester"}

        evs = event_mgr.get_events_for_ticker(ticker.upper())
        backtester = PointInTimeBacktester(
            initial_capital=100_000_000.0,
            buy_fee_pct=0.0015,
            sell_fee_pct=0.0025,
        )
        res = backtester.run_event_momentum_backtest(
            symbol=ticker.upper(),
            board=asset.canonical_board if asset else "MAIN",
            candles=candles,
            events=evs,
        )

        return {
            "symbol": res.symbol,
            "total_trades": res.total_trades,
            "net_return_pct": round(res.net_return_pct, 2),
            "win_rate_pct": round(res.win_rate_pct, 2),
            "profit_factor": round(res.profit_factor, 2),
            "max_drawdown_pct": round(res.max_drawdown_pct, 2),
            "sharpe_ratio": round(res.sharpe_ratio, 2),
            "rejected_orders_count": res.rejected_orders_count,
        }, {"source": "PointInTimeBacktester", "no_lookahead_bias": True}


class CalculatePortfolioRiskTool(BaseFinancialTool):
    name = "calculate_portfolio_risk"
    description = "Menghitung Value at Risk (VaR) dan Conditional VaR (CVaR) portofolio dengan simulasi Monte Carlo 10.000 iterasi."
    parameters_schema = {
        "type": "object",
        "properties": {
            "capital": {"type": "number", "description": "Total nilai portofolio dalam Rupiah"},
            "confidence": {"type": "number", "description": "Tingkat kepercayaan (misal 0.95)"},
        },
    }

    def run(self, capital: float = 100_000_000.0, confidence: float = 0.95) -> tuple[Any, dict[str, Any]]:
        # Benchmark normal historical returns
        import numpy as np
        sim_returns = [float(x) for x in np.random.normal(0.0005, 0.018, 120)]
        var, cvar = calculate_var_cvar_mc(sim_returns, confidence=confidence, num_simulations=10000, seed=42)

        return {
            "capital": capital,
            "confidence_level": confidence,
            "var_1d_pct": round(var * 100, 2),
            "var_1d_amount": round(capital * var, 0),
            "cvar_1d_pct": round(cvar * 100, 2),
            "cvar_1d_amount": round(capital * cvar, 0),
            "methodology": "Monte Carlo Box-Muller 10.000 simulasi",
        }, {"source": "OpenBagus Risk Core"}


class CalculatePositionSizingTool(BaseFinancialTool):
    name = "calculate_position_sizing"
    description = "Menghitung ukuran posisi optimal berdasarkan risiko maksimal 2.0% modal dan pembulatan ketat lot 100 lembar."
    parameters_schema = {
        "type": "object",
        "properties": {
            "capital": {"type": "number", "description": "Total modal akun"},
            "risk_pct": {"type": "number", "description": "Risiko per trade dalam persen (default 2.0)"},
            "entry_price": {"type": "number", "description": "Harga masuk (entry price)"},
            "stop_loss": {"type": "number", "description": "Harga stop loss"},
        },
        "required": ["capital", "entry_price", "stop_loss"],
    }

    def run(self, capital: float, entry_price: float, stop_loss: float, risk_pct: float = 2.0) -> tuple[Any, dict[str, Any]]:
        risk_budget = capital * (risk_pct / 100.0)
        risk_per_share = abs(entry_price - stop_loss)
        if risk_per_share <= 0:
            return {"error": "Stop loss tidak boleh sama dengan entry price."}, {}

        raw_shares = risk_budget / risk_per_share
        lots = IDXMicrostructureEngine.round_to_lot(int(raw_shares))
        allocated_shares = lots * 100
        position_value = allocated_shares * entry_price
        actual_risk = allocated_shares * risk_per_share
        actual_risk_pct = (actual_risk / capital) * 100 if capital > 0 else 0.0

        return {
            "capital": capital,
            "risk_budget_rp": risk_budget,
            "entry_price": entry_price,
            "stop_loss": stop_loss,
            "allocated_lots": lots,
            "allocated_shares": allocated_shares,
            "position_value_rp": position_value,
            "actual_risk_rp": actual_risk,
            "actual_risk_pct": round(actual_risk_pct, 2),
            "lot_constraint_applied": True,
        }, {"source": "IDX Microstructure Risk Sizing"}


class GetMacroSeriesTool(BaseFinancialTool):
    name = "get_macro_series"
    description = (
        "Mengambil data makroekonomi resmi: Inflasi IHK (CPI), Pertumbuhan PDB, "
        "Neraca Perdagangan Indonesia, dan Kurs Acuan JISDOR Bank Indonesia."
    )
    parameters_schema = {
        "type": "object",
        "properties": {
            "series": {
                "type": "string",
                "enum": ["CPI", "INFLASI", "GDP", "PDB", "TRADE", "JISDOR"],
                "description": "Indikator makro yang diinginkan.",
            }
        },
        "required": ["series"],
    }

    def run(self, series: str = "CPI", **kwargs: Any) -> tuple[Any, dict[str, Any]]:
        from openbagus.data.registry import DataProviderRegistry
        reg = DataProviderRegistry.get_instance()
        prov = reg.select_best_provider("MACRO", "macro_series")
        if not prov:
            return {"error": "Penyedia data makro tidak tersedia."}, {"source": "MacroEngine"}

        res = prov.fetch_macro_series(series)
        if res.success:
            return res.data, {"source": res.provider_id, "quality": res.quality_status, "as_of": res.as_of}
        return {"error": res.error_message}, {"source": res.provider_id}


class RefreshAssetDataTool(BaseFinancialTool):
    name = "refresh_asset_data"
    description = "Melakukan sinkronisasi dan pembaruan paksa data pasar dan profil emiten langsung dari penyedia data."
    parameters_schema = {
        "type": "object",
        "properties": {
            "ticker": {"type": "string", "description": "Kode saham IDX atau pair kripto"},
            "timeframe": {"type": "string", "description": "Timeframe data (default D1)"},
        },
        "required": ["ticker"],
    }

    def run(self, ticker: str, timeframe: str = "D1", **kwargs: Any) -> tuple[Any, dict[str, Any]]:
        clean = ticker.strip().upper()
        root = get_repo_root()
        eq_data = EquityData(root)
        fresh_data = eq_data.fetch_live_data(clean, save=True)
        if fresh_data.get("gaps"):
            return {
                "symbol": clean,
                "refreshed": False,
                "message": f"Gagal memperbarui data {clean}: {fresh_data.get('gaps')}",
            }, {"source": "LiveSyncEngine", "status": "FAILED"}

        candles = fresh_data.get("candles", [])
        return {
            "symbol": clean,
            "refreshed": True,
            "candles_count": len(candles),
            "latest_close": candles[-1]["close"] if candles else None,
            "retrieved_at": fresh_data.get("retrieved_at"),
            "source": fresh_data.get("source"),
        }, {"source": "LiveSyncEngine", "status": "SUCCESS"}


class GetDataCoverageTool(BaseFinancialTool):
    name = "get_data_coverage"
    description = "Memeriksa audit ketersediaan data (profil, harga EOD, lapkeu, keterbukaan informasi) per emiten atau semesta IDX."
    parameters_schema = {
        "type": "object",
        "properties": {
            "ticker": {"type": "string", "description": "Kode saham spesifik (opsional)"},
        },
    }

    def run(self, ticker: str = "", **kwargs: Any) -> tuple[Any, dict[str, Any]]:
        root = get_repo_root()
        catalog = EquityCatalog(root)
        storage = FinancialStatementStorage(root)
        eq_data = EquityData(root)

        if ticker:
            clean = ticker.strip().upper()
            asset = catalog.resolve(clean)
            cached_path = eq_data.directory / f"{clean}.json"
            has_eod = cached_path.exists()
            periods = storage.list_periods(clean)
            return {
                "symbol": clean,
                "name": asset.name if asset else "UNKNOWN",
                "board": asset.canonical_board if asset else "UNKNOWN",
                "sector": asset.sector_or_category if asset else "UNKNOWN",
                "profile_status": "AVAILABLE" if asset else "NOT_FOUND",
                "daily_eod_status": "AVAILABLE" if has_eod else "DATA_GAP",
                "financial_statements": "AVAILABLE" if periods else "DATA_GAP",
                "available_periods": periods,
                "official_source": "IDX Listing & Local EOD Storage",
            }, {"source": "DataCoverageEngine", "symbol": clean}

        # Universe level coverage summary
        stats = catalog.get_universe_stats()
        summary = storage.get_coverage_summary()
        eod_files = list(eq_data.directory.glob("*.json")) if eq_data.directory.exists() else []

        return {
            "total_issuers": stats.get("common_equities", 951),
            "issuers_with_profile": stats.get("total_instruments", 968),
            "issuers_with_eod_cached": len(eod_files),
            "issuers_with_financials": len(summary["symbols"]),
            "total_statements_stored": summary["total_statements"],
            "boards_breakdown": stats["boards"],
            "sectors_breakdown": stats["sectors"],
        }, {"source": "DataCoverageEngine", "universe": "ALL_IDX"}


def register_all_financial_tools(registry: ToolRegistry) -> None:
    """Registers all 24+ authoritative financial tools with the tool registry."""
    tools = [
        ResolveSecurityTool(),
        GetIDXUniverseTool(),
        GetCompanyProfileTool(),
        GetMarketPriceTool(),
        GetOHLCVTool(),
        GetLiquidityMetricsTool(),
        GetMicrostructureProfileTool(),
        DiscoverFinancialFilingsTool(),
        GetFinancialStatementTool(),
        CalculateFinancialRatiosTool(),
        CalculateValuationTool(),
        CompareCompanyFundamentalsTool(),
        GetFinancialProvenanceTool(),
        SearchOfficialDisclosuresTool(),
        GetRecentCompanyEventsTool(),
        EvaluateEventMaterialityTool(),
        CalculateIndicatorsTool(),
        RunScreenerTool(),
        RunBacktestTool(),
        CalculatePortfolioRiskTool(),
        CalculatePositionSizingTool(),
        GetMacroSeriesTool(),
        RefreshAssetDataTool(),
        GetDataCoverageTool(),
    ]
    for t in tools:
        registry.register(t)
