"""SEC EDGAR Provider for US-listed Financial Statements and Filings.

Provides zero-key access to official SEC EDGAR financial disclosures:
- https://www.sec.gov/files/company_tickers.json
- https://data.sec.gov/submissions/CIK##########.json
- https://data.sec.gov/api/xbrl/companyfacts/CIK##########.json

Adheres strictly to SEC Fair Access guidelines (<= 10 req/s, compliant User-Agent,
exponential backoff, local caching, and provenance tracking).
"""

from __future__ import annotations

import json
import logging
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from openbagus.domains.equities.financial_model import (
    CanonicalFinancialStatement,
    SourceCitation,
)

logger = logging.getLogger(__name__)

# SEC Fair Access requires user-agent in format: "Sample Company Name AdminContact@<sample company domain>.com"
SEC_DEFAULT_USER_AGENT = os.environ.get(
    "OPENBAGUS_SEC_USER_AGENT",
    "OpenBagus-FinancialResearch/1.0 (openbagus-dev@openbagus.org)",
)
SEC_RATE_LIMIT_INTERVAL = 0.2  # Max 5 requests/sec, safely below SEC's 10 req/sec limit


class SecRateLimiter:
    """Thread-safe rate limiter ensuring compliance with SEC's 10 req/sec limit."""

    def __init__(self, min_interval: float = SEC_RATE_LIMIT_INTERVAL) -> None:
        self.min_interval = min_interval
        self._last_call: float = 0.0

    def wait(self) -> None:
        now = time.monotonic()
        elapsed = now - self._last_call
        if elapsed < self.min_interval:
            time.sleep(self.min_interval - elapsed)
        self._last_call = time.monotonic()


_SEC_LIMITER = SecRateLimiter()


# US-GAAP Taxonomy Concept Mappings
US_GAAP_INCOME_CONCEPTS = {
    "revenue": [
        "RevenueFromContractWithCustomerExcludingAssessedTax",
        "Revenues",
        "SalesRevenueNet",
        "SalesRevenueGoodsNet",
        "RevenueFromContractWithCustomerIncludingAssessedTax",
    ],
    "cost_of_revenue": [
        "CostOfGoodsAndServicesSold",
        "CostOfGoodsSold",
        "CostOfRevenue",
    ],
    "gross_profit": [
        "GrossProfit",
    ],
    "operating_expenses": [
        "OperatingExpenses",
        "OperatingCostsAndExpenses",
    ],
    "research_and_development": [
        "ResearchAndDevelopmentExpense",
    ],
    "selling_general_administrative": [
        "SellingGeneralAndAdministrativeExpense",
        "GeneralAndAdministrativeExpense",
    ],
    "operating_income": [
        "OperatingIncomeLoss",
    ],
    "interest_expense": [
        "InterestExpense",
        "InterestAndDebtExpense",
    ],
    "profit_before_tax": [
        "IncomeLossFromContinuingOperationsBeforeIncomeTaxesMinorityInterestAndIncomeLossFromEquityMethodInvestments",
        "IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest",
    ],
    "tax_expense": [
        "IncomeTaxExpenseBenefit",
    ],
    "net_income_total": [
        "ProfitLoss",
        "NetIncomeLoss",
    ],
    "net_income_attributable": [
        "NetIncomeLoss",
        "NetIncomeLossAvailableToCommonStockholdersBasic",
    ],
    "eps_basic": [
        "EarningsPerShareBasic",
    ],
    "eps_diluted": [
        "EarningsPerShareDiluted",
    ],
}

US_GAAP_BALANCE_CONCEPTS = {
    "cash_and_equivalents": [
        "CashAndCashEquivalentsAtCarryingValue",
        "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents",
    ],
    "short_term_investments": [
        "MarketableSecuritiesCurrent",
        "AvailableForSaleSecuritiesCurrent",
        "ShortTermInvestments",
    ],
    "trade_receivables": [
        "AccountsReceivableNetCurrent",
        "ReceivablesNetCurrent",
    ],
    "inventories": [
        "InventoryNet",
    ],
    "current_assets": [
        "AssetsCurrent",
    ],
    "non_current_assets": [
        "AssetsNoncurrent",
    ],
    "total_assets": [
        "Assets",
    ],
    "trade_payables": [
        "AccountsPayableCurrent",
    ],
    "short_term_debt": [
        "CommercialPaper",
        "ShortTermBorrowings",
        "DebtCurrent",
        "LongTermDebtCurrent",
    ],
    "long_term_debt": [
        "LongTermDebtNoncurrent",
        "LongTermDebt",
    ],
    "lease_liabilities": [
        "OperatingLeaseLiabilityCurrent",
        "OperatingLeaseLiabilityNoncurrent",
    ],
    "current_liabilities": [
        "LiabilitiesCurrent",
    ],
    "non_current_liabilities": [
        "LiabilitiesNoncurrent",
    ],
    "total_liabilities": [
        "Liabilities",
    ],
    "retained_earnings": [
        "RetainedEarningsAccumulatedDeficit",
    ],
    "equity_attributable_to_owners": [
        "StockholdersEquity",
        "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest",
    ],
    "non_controlling_interests": [
        "MinorityInterest",
    ],
    "total_equity": [
        "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest",
        "StockholdersEquity",
    ],
}

US_GAAP_CASH_FLOW_CONCEPTS = {
    "operating_cash_flow": [
        "NetCashProvidedByUsedInOperatingActivities",
        "NetCashProvidedByUsedInOperatingActivitiesContinuingOperations",
    ],
    "capital_expenditure": [
        "PaymentsToAcquirePropertyPlantAndEquipment",
        "PaymentsToAcquireProductiveAssets",
    ],
    "investing_cash_flow": [
        "NetCashProvidedByUsedInInvestingActivities",
    ],
    "financing_cash_flow": [
        "NetCashProvidedByUsedInFinancingActivities",
    ],
    "dividends_paid": [
        "PaymentsOfDividends",
        "PaymentsOfDividendsCommonStock",
    ],
    "share_repurchases": [
        "PaymentsForRepurchaseOfCommonStock",
    ],
    "debt_issuance": [
        "ProceedsFromIssuanceOfLongTermDebt",
    ],
    "debt_repayments": [
        "RepaymentsOfLongTermDebt",
    ],
}

DEI_SHARES_CONCEPTS = [
    "EntityCommonStockSharesOutstanding",
    "CommonStockSharesOutstanding",
]


class SecEdgarClient:
    """Robust, free-first SEC EDGAR client for US public equities."""

    def __init__(
        self,
        root: Path | None = None,
        user_agent: str | None = None,
    ) -> None:
        self.root = root or Path.cwd()
        self.cache_dir = self.root / "data" / "equities" / "sec"
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.user_agent = user_agent or os.environ.get(
            "OPENBAGUS_SEC_USER_AGENT", SEC_DEFAULT_USER_AGENT
        )
        self._ticker_map: dict[str, int] = {}
        self._cik_map: dict[int, dict[str, Any]] = {}
        self._load_cached_tickers()

    def _load_cached_tickers(self) -> None:
        cache_file = self.cache_dir / "company_tickers.json"
        if cache_file.exists():
            try:
                data = json.loads(cache_file.read_text(encoding="utf-8"))
                for item in data.values():
                    sym = item.get("ticker", "").upper()
                    cik = int(item.get("cik_str", 0))
                    if sym and cik:
                        self._ticker_map[sym] = cik
                        self._cik_map[cik] = item
            except Exception as exc:
                logger.warning("Failed to parse cached SEC company tickers: %s", exc)

    def _fetch_url(self, url: str, max_retries: int = 3) -> dict[str, Any] | None:
        headers = {
            "User-Agent": self.user_agent,
            "Accept-Encoding": "gzip, deflate",
            "Host": urllib.parse.urlsplit(url).netloc,
        }
        for attempt in range(max_retries):
            _SEC_LIMITER.wait()
            req = urllib.request.Request(url, headers=headers)
            try:
                with urllib.request.urlopen(req, timeout=15) as resp:
                    if resp.status == 200:
                        content = resp.read()
                        # Handle gzip if necessary
                        if resp.headers.get("Content-Encoding") == "gzip":
                            import gzip
                            content = gzip.decompress(content)
                        return json.loads(content.decode("utf-8"))
                    logger.warning("SEC EDGAR HTTP %d for %s", resp.status, url)
            except urllib.error.HTTPError as exc:
                if exc.code == 429:
                    wait_sec = (attempt + 1) * 2.0
                    logger.warning("SEC rate limited (429). Backing off %0.1fs...", wait_sec)
                    time.sleep(wait_sec)
                elif exc.code == 404:
                    logger.info("SEC resource not found (404): %s", url)
                    return None
                else:
                    logger.warning("SEC HTTP error %d: %s", exc.code, exc)
            except Exception as exc:
                logger.warning("SEC fetch error (attempt %d): %s", attempt + 1, exc)
                time.sleep((attempt + 1) * 1.0)
        return None

    def refresh_ticker_map(self) -> dict[str, int]:
        """Fetches official company_tickers.json from sec.gov."""
        url = "https://www.sec.gov/files/company_tickers.json"
        data = self._fetch_url(url)
        if data:
            cache_file = self.cache_dir / "company_tickers.json"
            cache_file.write_text(json.dumps(data, indent=2), encoding="utf-8")
            self._ticker_map.clear()
            self._cik_map.clear()
            for item in data.values():
                sym = item.get("ticker", "").upper()
                cik = int(item.get("cik_str", 0))
                if sym and cik:
                    self._ticker_map[sym] = cik
                    self._cik_map[cik] = item
        return self._ticker_map

    def resolve_ticker(self, symbol: str) -> int | None:
        """Resolves a ticker symbol (e.g. AAPL) to its 10-digit CIK number."""
        clean_sym = symbol.strip().upper()
        if clean_sym in self._ticker_map:
            return self._ticker_map[clean_sym]
        # If not in cache, refresh ticker map once
        self.refresh_ticker_map()
        return self._ticker_map.get(clean_sym)

    def get_company_facts(self, cik: int, force_refresh: bool = False) -> dict[str, Any] | None:
        """Retrieves aggregated XBRL company facts for a CIK from data.sec.gov."""
        cik_str = f"{cik:010d}"
        cache_file = self.cache_dir / f"companyfacts_CIK{cik_str}.json"
        if not force_refresh and cache_file.exists():
            try:
                return json.loads(cache_file.read_text(encoding="utf-8"))
            except Exception:
                pass

        url = f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik_str}.json"
        data = self._fetch_url(url)
        if data:
            cache_file.write_text(json.dumps(data, indent=2), encoding="utf-8")
            return data
        return None

    def get_submissions(self, cik: int, force_refresh: bool = False) -> dict[str, Any] | None:
        """Retrieves company submission history (filing metadata) from data.sec.gov."""
        cik_str = f"{cik:010d}"
        cache_file = self.cache_dir / f"submissions_CIK{cik_str}.json"
        if not force_refresh and cache_file.exists():
            try:
                return json.loads(cache_file.read_text(encoding="utf-8"))
            except Exception:
                pass

        url = f"https://data.sec.gov/submissions/CIK{cik_str}.json"
        data = self._fetch_url(url)
        if data:
            cache_file.write_text(json.dumps(data, indent=2), encoding="utf-8")
            return data
        return None

    def extract_canonical_statements(
        self,
        symbol: str,
        company_facts: dict[str, Any] | None = None,
    ) -> list[CanonicalFinancialStatement]:
        """Parses raw SEC company facts into normalized CanonicalFinancialStatement objects."""
        clean_sym = symbol.strip().upper()
        if company_facts is None:
            cik = self.resolve_ticker(clean_sym)
            if not cik:
                return []
            company_facts = self.get_company_facts(cik)
            if not company_facts:
                return []

        facts = company_facts.get("facts", {})
        us_gaap = facts.get("us-gaap", {})
        dei = facts.get("dei", {})

        # Period -> CanonicalFinancialStatement builder
        # A period key is "{year}-{form_type}" or "{year}-{fp}" e.g., '2024-FY', '2025-Q1'
        # We index observations by (year, fp, form)
        period_data: dict[str, dict[str, Any]] = {}
        citations_data: dict[str, dict[str, SourceCitation]] = {}
        obs_scores: dict[str, dict[str, tuple]] = {}

        def _observation_score(obs: dict[str, Any], concept_idx: int, period_type: str, statement_type: str) -> tuple[int, int, int, str]:
            concept_priority = -concept_idx
            start = obs.get("start")
            end = obs.get("end")
            if statement_type == "Balance Sheet":
                duration_score = 1
            else:
                duration_score = 0
                if start and end:
                    try:
                        from datetime import date
                        d_days = (date.fromisoformat(end) - date.fromisoformat(start)).days
                        if period_type == "FY":
                            duration_score = 3 if 330 <= d_days <= 385 else (2 if d_days > 180 else 1)
                        else:
                            duration_score = 3 if 75 <= d_days <= 105 else (2 if d_days <= 180 else 1)
                    except Exception:
                        duration_score = 1

            form = (obs.get("form") or "").upper()
            form_score = 2 if form.endswith("/A") else (1 if form in {"10-K", "20-F", "10-Q"} else 0)
            filed = str(obs.get("filed") or "")
            return (concept_priority, duration_score, form_score, filed)

        def _extract_metric(concept_dict: dict[str, list[str]], target_key: str, statement_type: str) -> None:
            for canonical_key, concepts in concept_dict.items():
                for c_idx, concept in enumerate(concepts):
                    if concept not in us_gaap:
                        continue
                    concept_obj = us_gaap[concept]
                    units = concept_obj.get("units", {})
                    # Prefer USD
                    obs_list = units.get("USD") or []
                    for obs in obs_list:
                        form = obs.get("form", "").upper()
                        if form not in {"10-K", "10-Q", "10-K/A", "10-Q/A", "20-F"}:
                            continue
                        fy = obs.get("fy")
                        fp = (obs.get("fp") or "").upper()
                        val = obs.get("val")
                        end = obs.get("end")
                        filed = str(obs.get("filed") or "")
                        accn = obs.get("accn")
                        frame = obs.get("frame", "")

                        if fy is None or val is None or not end:
                            continue

                        # Determine period string
                        if form in {"10-K", "10-K/A", "20-F"} or fp == "FY":
                            period_str = f"{fy}-FY"
                            period_type = "FY"
                        else:
                            period_str = f"{fy}-{fp}" if fp in {"Q1", "Q2", "Q3", "Q4"} else f"{fy}-Q{form}"
                            period_type = fp if fp in {"Q1", "Q2", "Q3", "Q4"} else "Q"

                        if period_str not in period_data:
                            period_data[period_str] = {
                                "symbol": clean_sym,
                                "period": period_str,
                                "period_type": period_type,
                                "currency": "USD",
                                "unit": "USD",
                                "unit_multiplier": 1.0,
                                "basis": "consolidated",
                                "audit_status": "audited" if form in {"10-K", "10-K/A", "20-F"} else "reviewed",
                                "period_end_date": end,
                                "filing_date": filed,
                            }
                            citations_data[period_str] = {}
                            obs_scores[period_str] = {}

                        score = _observation_score(obs, c_idx, period_type, statement_type)
                        curr_score = obs_scores[period_str].get(canonical_key)
                        if curr_score is None or score > curr_score:
                            if canonical_key == "capital_expenditure":
                                norm_val = abs(float(val))
                            else:
                                norm_val = float(val)

                            obs_scores[period_str][canonical_key] = score
                            period_data[period_str][canonical_key] = norm_val
                            if filed and filed > (period_data[period_str].get("filing_date") or ""):
                                period_data[period_str]["filing_date"] = filed

                            citations_data[period_str][canonical_key] = SourceCitation(
                                statement_type=statement_type,
                                xbrl_concept=f"us-gaap:{concept}",
                                xbrl_context=frame or f"FY{fy}{fp}",
                                raw_reported_text=str(val),
                                source_url=f"https://data.sec.gov/api/xbrl/companyfacts/CIK{self.resolve_ticker(clean_sym) or 0:010d}.json",
                            )

        # 1. Income Statement
        _extract_metric(US_GAAP_INCOME_CONCEPTS, "income", "Profit or Loss")
        # 2. Balance Sheet
        _extract_metric(US_GAAP_BALANCE_CONCEPTS, "balance", "Balance Sheet")
        # 3. Cash Flow
        _extract_metric(US_GAAP_CASH_FLOW_CONCEPTS, "cash_flow", "Cash Flows")

        # Extract shares outstanding from DEI
        for share_concept in DEI_SHARES_CONCEPTS:
            if share_concept in dei:
                units = dei[share_concept].get("units", {})
                obs_list = units.get("shares") or []
                for obs in sorted(obs_list, key=lambda o: str(o.get("filed") or "")):
                    fy = obs.get("fy")
                    fp = (obs.get("fp") or "").upper()
                    val = obs.get("val")
                    if fy and val:
                        period_str = f"{fy}-FY" if (fp == "FY" or obs.get("form", "").upper() in {"10-K", "10-K/A", "20-F"}) else f"{fy}-{fp}"
                        if period_str in period_data:
                            period_data[period_str]["shares_outstanding"] = float(val)

        # Build CanonicalFinancialStatement instances
        statements: list[CanonicalFinancialStatement] = []
        for p_key, p_vals in sorted(period_data.items()):
            # Must have at least revenue or total_assets to be meaningful
            if not p_vals.get("revenue") and not p_vals.get("total_assets"):
                continue

            # Compute gross profit if missing
            if p_vals.get("gross_profit") is None and p_vals.get("revenue") is not None and p_vals.get("cost_of_revenue") is not None:
                p_vals["gross_profit"] = p_vals["revenue"] - p_vals["cost_of_revenue"]

            # Compute operating income if missing
            if p_vals.get("operating_income") is None and p_vals.get("gross_profit") is not None and p_vals.get("operating_expenses") is not None:
                p_vals["operating_income"] = p_vals["gross_profit"] - p_vals["operating_expenses"]

            # Compute total interest bearing debt
            st_debt = p_vals.get("short_term_debt") or 0.0
            lt_debt = p_vals.get("long_term_debt") or 0.0
            if "short_term_debt" in p_vals or "long_term_debt" in p_vals:
                p_vals["interest_bearing_debt"] = st_debt + lt_debt

            # Compute free cash flow: OCF - Capex
            if p_vals.get("operating_cash_flow") is not None and p_vals.get("capital_expenditure") is not None:
                p_vals["free_cash_flow"] = p_vals["operating_cash_flow"] - p_vals["capital_expenditure"]

            stmt = CanonicalFinancialStatement(
                symbol=p_vals["symbol"],
                period=p_vals["period"],
                period_type=p_vals["period_type"],
                currency=p_vals["currency"],
                unit=p_vals["unit"],
                unit_multiplier=p_vals["unit_multiplier"],
                basis=p_vals["basis"],
                audit_status=p_vals["audit_status"],
                period_end_date=p_vals["period_end_date"],
                filing_date=p_vals.get("filing_date"),
                # Balance sheet
                cash_and_equivalents=p_vals.get("cash_and_equivalents"),
                short_term_investments=p_vals.get("short_term_investments"),
                trade_receivables=p_vals.get("trade_receivables"),
                inventories=p_vals.get("inventories"),
                current_assets=p_vals.get("current_assets"),
                non_current_assets=p_vals.get("non_current_assets"),
                total_assets=p_vals.get("total_assets"),
                trade_payables=p_vals.get("trade_payables"),
                short_term_debt=p_vals.get("short_term_debt"),
                long_term_debt=p_vals.get("long_term_debt"),
                lease_liabilities=p_vals.get("lease_liabilities"),
                interest_bearing_debt=p_vals.get("interest_bearing_debt"),
                current_liabilities=p_vals.get("current_liabilities"),
                non_current_liabilities=p_vals.get("non_current_liabilities"),
                total_liabilities=p_vals.get("total_liabilities"),
                retained_earnings=p_vals.get("retained_earnings"),
                equity_attributable_to_owners=p_vals.get("equity_attributable_to_owners"),
                non_controlling_interests=p_vals.get("non_controlling_interests"),
                total_equity=p_vals.get("total_equity"),
                # Income statement
                revenue=p_vals.get("revenue"),
                cost_of_revenue=p_vals.get("cost_of_revenue"),
                gross_profit=p_vals.get("gross_profit"),
                operating_expenses=p_vals.get("operating_expenses"),
                operating_income=p_vals.get("operating_income"),
                profit_before_tax=p_vals.get("profit_before_tax"),
                tax_expense=p_vals.get("tax_expense"),
                net_income_total=p_vals.get("net_income_total"),
                net_income_attributable=p_vals.get("net_income_attributable"),
                eps_basic=p_vals.get("eps_basic"),
                eps_diluted=p_vals.get("eps_diluted"),
                shares_outstanding=p_vals.get("shares_outstanding"),
                # Cash flows
                operating_cash_flow=p_vals.get("operating_cash_flow"),
                capital_expenditures=p_vals.get("capital_expenditure"),
                investing_cash_flow=p_vals.get("investing_cash_flow"),
                financing_cash_flow=p_vals.get("financing_cash_flow"),
                dividends_paid=p_vals.get("dividends_paid"),
                citations=citations_data.get(p_key, {}),
            )
            # Run invariant accounting reconciliation checks
            stmt.validate_accounting_relationships()
            statements.append(stmt)

        return statements
