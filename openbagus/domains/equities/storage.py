"""Multi-period Financial Statement Storage and Provenance Index.

Persists versioned, audited, and reviewed issuer financial disclosures
under data/equities/financials/{SYMBOL}/{period}.json, preventing overwrite
of historical periods and enabling time-series fundamental analysis.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
import re
import tempfile
from typing import Any

from openbagus.domains.equities.financial_model import (
    CanonicalFinancialStatement,
    SourceCitation,
)

logger = logging.getLogger(__name__)


def _period_sort_key(period: str) -> tuple[int, int]:
    """Sorts periods chronologically: 2023-Q1 < 2023-H1 < 2023-9M < 2023-FY < 2024-Q1."""
    m = re.match(r"(\d{4})[-_]?([A-Z0-9]+)?", period.upper())
    if not m:
        return (0, 0)
    year = int(m.group(1))
    sub = m.group(2) or "FY"
    sub_order = {
        "Q1": 1,
        "Q2": 2,
        "H1": 2,
        "9M": 3,
        "Q3": 3,
        "Q4": 4,
        "FY": 4,
        "TTM": 5,
    }.get(sub, 0)
    return (year, sub_order)


class FinancialStatementStorage:
    """Manages persistent multi-period financial filings and their retrieval."""

    def __init__(self, root: Path | None = None) -> None:
        self.root = root or Path.cwd()
        self.base_dir = self.root / "data" / "equities" / "financials"
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def _get_symbol_dir(self, symbol: str) -> Path:
        clean_sym = symbol.strip().upper()
        if not re.fullmatch(r"[A-Z][A-Z0-9-]{1,14}", clean_sym):
            raise ValueError(f"Ticker symbol tidak valid: {symbol}")
        sym_dir = self.base_dir / clean_sym
        sym_dir.mkdir(parents=True, exist_ok=True)
        return sym_dir

    def store_statement(self, statement: CanonicalFinancialStatement | dict[str, Any]) -> Path:
        """Stores a financial statement under data/equities/financials/{SYMBOL}/{period}.json."""
        if isinstance(statement, CanonicalFinancialStatement):
            data = statement.to_legacy_dict()
            sym = statement.symbol.upper()
            period = statement.period
        elif isinstance(statement, dict):
            data = statement
            sym = (statement.get("symbol") or "").upper()
            period = statement.get("period", "UNKNOWN_PERIOD")
            if not sym and "source" in statement:
                m = re.search(r"\b([A-Z]{4})\b", statement["source"].upper())
                if m:
                    sym = m.group(1)
        else:
            raise TypeError("Statement harus bertipe CanonicalFinancialStatement atau dict.")

        if not sym or not re.fullmatch(r"[A-Z][A-Z0-9-]{1,14}", sym):
            raise ValueError("Statement tidak memiliki ticker symbol yang valid.")
        if not period or period == "UNKNOWN_PERIOD":
            raise ValueError("Statement tidak memiliki periode fiskal yang valid.")

        clean_period = re.sub(r"[^A-Za-z0-9_-]", "", period)
        sym_dir = self._get_symbol_dir(sym)
        target_path = sym_dir / f"{clean_period}.json"

        # Ensure symbol is explicitly in data
        data["symbol"] = sym

        # Atomic write
        temp_file = None
        try:
            with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=sym_dir, delete=False) as f:
                temp_file = Path(f.name)
                json.dump(data, f, indent=2, ensure_ascii=False)
            os.replace(temp_file, target_path)
            logger.info("Laporan keuangan tersimpan: %s", target_path)
            return target_path
        finally:
            if temp_file is not None and temp_file.exists():
                temp_file.unlink(missing_ok=True)

    def get_statement(self, symbol: str, period: str | None = None) -> dict[str, Any] | None:
        """Retrieves statement for symbol. If period is None, returns the latest period."""
        clean_sym = symbol.strip().upper()
        sym_dir = self.base_dir / clean_sym
        if not sym_dir.exists():
            return None

        if period:
            clean_period = re.sub(r"[^A-Za-z0-9_-]", "", period.strip())
            file_path = sym_dir / f"{clean_period}.json"
            if file_path.exists():
                try:
                    return json.loads(file_path.read_text(encoding="utf-8"))
                except Exception as e:
                    logger.warning("Gagal membaca statement %s: %e", file_path, e)
            return None

        # Return latest period
        periods = self.list_periods(clean_sym)
        if not periods:
            return None
        latest_period = periods[-1]
        return self.get_statement(clean_sym, latest_period)

    def list_periods(self, symbol: str) -> list[str]:
        """Lists available periods for symbol in chronological order."""
        clean_sym = symbol.strip().upper()
        sym_dir = self.base_dir / clean_sym
        if not sym_dir.exists():
            return []

        periods = []
        for p in sym_dir.glob("*.json"):
            if p.stem.lower() != "index":
                periods.append(p.stem)

        periods.sort(key=_period_sort_key)
        return periods

    def get_history(self, symbol: str, max_periods: int = 8) -> list[dict[str, Any]]:
        """Retrieves list of statements in chronological order up to max_periods."""
        periods = self.list_periods(symbol)
        selected_periods = periods[-max_periods:] if len(periods) > max_periods else periods
        results = []
        for p in selected_periods:
            stmt = self.get_statement(symbol, p)
            if stmt:
                results.append(stmt)
        return results

    def get_coverage_summary(self) -> dict[str, Any]:
        """Summarizes available statements coverage across all issuers."""
        if not self.base_dir.exists():
            return {"total_symbols": 0, "total_statements": 0, "symbols": {}}

        total_stmts = 0
        symbols_map: dict[str, list[str]] = {}
        for d in self.base_dir.iterdir():
            if d.is_dir():
                sym = d.name.upper()
                periods = self.list_periods(sym)
                if periods:
                    symbols_map[sym] = periods
                    total_stmts += len(periods)

        return {
            "total_symbols": len(symbols_map),
            "total_statements": total_stmts,
            "symbols": symbols_map,
        }

    def compute_ttm_statement(self, symbol: str) -> dict[str, Any] | None:
        """Computes Trailing Twelve Month (TTM) financial statement from available periods.

        Supports:
        1. Latest FY if no newer interim filings exist.
        2. Four consecutive quarters summation (Q_t + Q_{t-1} + Q_{t-2} + Q_{t-3}).
        3. Interim YTD adjustment (TTM = Interim_curr + (FY_prior - Interim_prior)).
        Flow items are aggregated; balance sheet items are retained from the latest point-in-time filing.
        """
        periods = self.list_periods(symbol)
        if not periods:
            return None

        statements = [self.get_statement(symbol, p) for p in periods if self.get_statement(symbol, p)]
        if not statements:
            return None

        flow_keys = {
            "revenue",
            "cost_of_revenue",
            "gross_profit",
            "operating_expenses",
            "operating_income",
            "finance_costs",
            "interest_expense",
            "profit_before_tax",
            "tax_expense",
            "net_income_total",
            "net_income_attributable",
            "net_income_non_controlling",
            "net_income",
            "operating_cash_flow",
            "capital_expenditure",
            "capital_expenditures",
            "investing_cash_flow",
            "financing_cash_flow",
            "dividends_paid",
            "free_cash_flow",
        }

        latest = statements[-1]
        p_type = (latest.get("period_type") or "").upper()
        p_str = (latest.get("period") or "").upper()

        # Case 1: Latest is full year
        if p_type == "FY" or p_str.endswith("FY"):
            ttm = dict(latest)
            ttm["period"] = f"{latest.get('period', 'FY')}-TTM"
            ttm["period_type"] = "TTM"
            ttm["ttm_method"] = "LATEST_FULL_YEAR"
            return ttm

        # Case 2: Interim YTD adjustment with prior FY (e.g., 2024-9M + 2023-FY - 2023-9M)
        m = re.match(r"(\d{4})[-_]?([A-Z0-9]+)", p_str)
        if m:
            curr_year = int(m.group(1))
            interim_sub = m.group(2)
            prior_year = curr_year - 1
            prior_fy_key = f"{prior_year}-FY"
            prior_interim_key = f"{prior_year}-{interim_sub}"

            stmt_prior_fy = next((s for s in statements if (s.get("period") or "").upper().replace("_", "-") == prior_fy_key), None)
            stmt_prior_interim = next((s for s in statements if (s.get("period") or "").upper().replace("_", "-") == prior_interim_key), None)

            if stmt_prior_fy and stmt_prior_interim:
                ttm_vals = dict(latest.get("values", {}))
                curr_vals = latest.get("values", {})
                pfy_vals = stmt_prior_fy.get("values", {})
                pinterim_vals = stmt_prior_interim.get("values", {})

                for k in flow_keys:
                    c_v = curr_vals.get(k)
                    pfy_v = pfy_vals.get(k)
                    pi_v = pinterim_vals.get(k)
                    if c_v is not None and pfy_v is not None and pi_v is not None:
                        ttm_vals[k] = c_v + (pfy_v - pi_v)

                ttm_stmt = dict(latest)
                ttm_stmt["period"] = f"{latest.get('period')}-TTM"
                ttm_stmt["period_type"] = "TTM"
                ttm_stmt["ttm_method"] = "INTERIM_YTD_PLUS_PRIOR_FY_ADJUSTED"
                ttm_stmt["values"] = ttm_vals
                return ttm_stmt

        # Case 3: Sum of last 4 quarters if available
        quarterly_stmts = [s for s in statements if (s.get("period_type") or "").upper() in {"Q1", "Q2", "Q3", "Q4", "QUARTER"}]
        if len(quarterly_stmts) >= 4:
            last_4 = quarterly_stmts[-4:]
            ttm_vals = dict(last_4[-1].get("values", {}))
            for k in flow_keys:
                vals = [s.get("values", {}).get(k) for s in last_4]
                if all(v is not None for v in vals):
                    ttm_vals[k] = sum(vals)

            ttm_stmt = dict(last_4[-1])
            ttm_stmt["period"] = f"{last_4[-1].get('period')}-TTM"
            ttm_stmt["period_type"] = "TTM"
            ttm_stmt["ttm_method"] = "FOUR_CONSECUTIVE_QUARTERS"
            ttm_stmt["values"] = ttm_vals
            return ttm_stmt

        # Fallback to latest statement with TTM designation note
        ttm_fallback = dict(latest)
        ttm_fallback["period"] = f"{latest.get('period')}-TTM"
        ttm_fallback["period_type"] = "TTM"
        ttm_fallback["ttm_method"] = "LATEST_AVAILABLE_FALLBACK"
        return ttm_fallback

    def get_ttm_statement(self, symbol: str) -> dict[str, Any] | None:
        """Returns TTM statement for symbol, computing it if not stored directly."""
        clean_sym = symbol.strip().upper()
        # Check if stored directly
        direct = self.get_statement(clean_sym, f"{clean_sym}_TTM") or self.get_statement(clean_sym, "TTM")
        if direct:
            return direct
        return self.compute_ttm_statement(clean_sym)

