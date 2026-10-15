"""Canonical Financial Facts Database for OpenBagus.

Stores atomic, lineage-bearing, normalized financial facts and filing records
in SQLite (WAL mode) to support longitudinal multi-year research, fast cross-company
queries, provenance auditing, and restatement tracking.
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

logger = logging.getLogger(__name__)


class FinancialFactsDatabase:
    """SQLite-backed canonical repository of atomic financial facts and filing indices."""

    def __init__(self, db_path: Path | None = None, root: Path | None = None, data_root: Path | None = None) -> None:
        if db_path is not None:
            self.db_path = db_path
        else:
            from openbagus.core.env import get_operational_data_root
            if data_root is not None:
                base = data_root
            elif os.environ.get("OPENBAGUS_DATA_ROOT"):
                base = Path(os.environ["OPENBAGUS_DATA_ROOT"]).resolve()
            elif root is not None and (root / "data" / "equities" / "financial_facts.db").exists() and not (get_operational_data_root() / "equities" / "financial_facts.db").exists():
                base = root / "data"
            else:
                base = get_operational_data_root()
            self.db_path = base / "equities" / "financial_facts.db"
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(str(self.db_path), timeout=15.0)
        conn.row_factory = sqlite3.Row
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    def _init_schema(self) -> None:
        with self._connection() as conn:
            conn.execute("PRAGMA journal_mode=WAL;")
            conn.execute("PRAGMA synchronous=NORMAL;")

            # Table 1: Filing Index
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS filing_index (
                    filing_id TEXT PRIMARY KEY,
                    symbol TEXT NOT NULL,
                    exchange TEXT NOT NULL,
                    filing_type TEXT NOT NULL,
                    period TEXT NOT NULL,
                    fiscal_year INTEGER,
                    period_end_date TEXT,
                    filing_date TEXT,
                    source_provider TEXT NOT NULL,
                    source_url TEXT,
                    local_path TEXT,
                    status TEXT NOT NULL,
                    indexed_at TEXT NOT NULL
                );
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_filing_symbol_period ON filing_index(symbol, period);"
            )

            # Table 2: Normalized Financial Facts
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS financial_facts (
                    fact_id TEXT PRIMARY KEY,
                    symbol TEXT NOT NULL,
                    exchange TEXT NOT NULL,
                    period TEXT NOT NULL,
                    period_type TEXT NOT NULL,
                    fiscal_year INTEGER,
                    period_end_date TEXT NOT NULL,
                    filing_date TEXT,
                    category TEXT NOT NULL,
                    metric_name TEXT NOT NULL,
                    original_label TEXT,
                    taxonomy_tag TEXT,
                    value REAL NOT NULL,
                    currency TEXT NOT NULL,
                    unit_scaling TEXT NOT NULL,
                    is_consolidated INTEGER NOT NULL DEFAULT 1,
                    audit_status TEXT NOT NULL DEFAULT 'audited',
                    source_provider TEXT NOT NULL,
                    source_url TEXT,
                    accession_number TEXT,
                    extraction_method TEXT,
                    version INTEGER NOT NULL DEFAULT 1,
                    restatement_of TEXT,
                    computation_lineage TEXT,
                    validation_status TEXT NOT NULL DEFAULT 'VALID',
                    created_at TEXT NOT NULL
                );
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_facts_sym_metric_period ON financial_facts(symbol, metric_name, period);"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_facts_sym_period ON financial_facts(symbol, period);"
            )

    def record_filing(
        self,
        symbol: str,
        exchange: str,
        filing_type: str,
        period: str,
        fiscal_year: int | None,
        period_end_date: str | None,
        filing_date: str | None,
        source_provider: str,
        source_url: str | None = None,
        local_path: str | None = None,
        status: str = "INDEXED",
    ) -> str:
        """Records or updates a filing in the filing index."""
        filing_id = f"{symbol.upper()}:{period}:{filing_type.upper()}"
        now_iso = datetime.now(timezone.utc).isoformat()
        with self._connection() as conn:
            conn.execute(
                """
                INSERT INTO filing_index (
                    filing_id, symbol, exchange, filing_type, period,
                    fiscal_year, period_end_date, filing_date, source_provider,
                    source_url, local_path, status, indexed_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(filing_id) DO UPDATE SET
                    status = excluded.status,
                    source_url = COALESCE(excluded.source_url, filing_index.source_url),
                    local_path = COALESCE(excluded.local_path, filing_index.local_path),
                    indexed_at = excluded.indexed_at;
                """,
                (
                    filing_id,
                    symbol.upper(),
                    exchange.upper(),
                    filing_type.upper(),
                    period,
                    fiscal_year,
                    period_end_date,
                    filing_date,
                    source_provider,
                    source_url,
                    local_path,
                    status,
                    now_iso,
                ),
            )
        return filing_id

    def store_fact(
        self,
        symbol: str,
        exchange: str,
        period: str,
        period_type: str,
        metric_name: str,
        value: float,
        currency: str = "IDR",
        category: str = "Income Statement",
        unit_scaling: str = "exact",
        fiscal_year: int | None = None,
        period_end_date: str | None = None,
        filing_date: str | None = None,
        original_label: str | None = None,
        taxonomy_tag: str | None = None,
        is_consolidated: bool = True,
        audit_status: str = "audited",
        source_provider: str = "OFFICIAL_FILING",
        source_url: str | None = None,
        accession_number: str | None = None,
        extraction_method: str = "XBRL_NORMALIZATION",
        version: int = 1,
        restatement_of: str | None = None,
        computation_lineage: dict[str, Any] | None = None,
        validation_status: str = "VALID",
    ) -> str:
        """Stores or updates an atomic financial fact with audit lineage."""
        sym = symbol.upper()
        p_end = period_end_date or period
        fact_id = f"{sym}:{period}:{metric_name}:v{version}"
        lineage_json = json.dumps(computation_lineage, ensure_ascii=False) if computation_lineage else None
        now_iso = datetime.now(timezone.utc).isoformat()

        if source_url and ("idx.co.id/filings" in source_url.lower() or "synthetic" in source_url.lower()):
            raise ValueError(f"Invented or synthetic source URL rejected: {source_url}")

        with self._connection() as conn:
            conn.execute(
                """
                INSERT INTO financial_facts (
                    fact_id, symbol, exchange, period, period_type, fiscal_year,
                    period_end_date, filing_date, category, metric_name,
                    original_label, taxonomy_tag, value, currency, unit_scaling,
                    is_consolidated, audit_status, source_provider, source_url,
                    accession_number, extraction_method, version, restatement_of,
                    computation_lineage, validation_status, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(fact_id) DO UPDATE SET
                    value = excluded.value,
                    validation_status = excluded.validation_status,
                    computation_lineage = excluded.computation_lineage;
                """,
                (
                    fact_id,
                    sym,
                    exchange.upper(),
                    period,
                    period_type,
                    fiscal_year,
                    p_end,
                    filing_date,
                    category,
                    metric_name,
                    original_label,
                    taxonomy_tag,
                    float(value),
                    currency,
                    unit_scaling,
                    1 if is_consolidated else 0,
                    audit_status,
                    source_provider,
                    source_url,
                    accession_number,
                    extraction_method,
                    version,
                    restatement_of,
                    lineage_json,
                    validation_status,
                    now_iso,
                ),
            )
        return fact_id

    def get_fact(
        self, symbol: str, metric_name: str, period: str, include_quarantined: bool = False
    ) -> dict[str, Any] | None:
        """Retrieves a specific fact for an issuer and period."""
        status_clause = "" if include_quarantined else " AND validation_status IN ('VALID', 'VALIDATED')"
        with self._connection() as conn:
            cur = conn.execute(
                f"""
                SELECT * FROM financial_facts
                WHERE symbol = ? AND metric_name = ? AND period = ?{status_clause}
                ORDER BY version DESC LIMIT 1;
                """,
                (symbol.upper(), metric_name, period),
            )
            row = cur.fetchone()
            if row:
                res = dict(row)
                if res.get("computation_lineage"):
                    try:
                        res["computation_lineage"] = json.loads(res["computation_lineage"])
                    except Exception:
                        pass
                return res
        return None

    def get_facts_for_period(
        self, symbol: str, period: str, include_quarantined: bool = False
    ) -> dict[str, float]:
        """Returns all metric values for an issuer and period as a {metric_name: value} dictionary."""
        status_clause = "" if include_quarantined else " AND validation_status IN ('VALID', 'VALIDATED')"
        with self._connection() as conn:
            cur = conn.execute(
                f"""
                SELECT metric_name, value FROM financial_facts
                WHERE symbol = ? AND period = ?{status_clause}
                ORDER BY version ASC;
                """,
                (symbol.upper(), period),
            )
            return {row["metric_name"]: row["value"] for row in cur.fetchall()}

    def get_metric_history(
        self,
        symbol: str,
        metric_name: str,
        limit: int = 10,
        period_type: str | None = None,
        include_quarantined: bool = False,
    ) -> list[dict[str, Any]]:
        """Returns time series history for a metric ordered chronologically."""
        query = """
            SELECT period, fiscal_year, period_end_date, value, currency, unit_scaling, validation_status, source_provider, source_url
            FROM financial_facts
            WHERE symbol = ? AND metric_name = ?
        """
        params: list[Any] = [symbol.upper(), metric_name]
        if not include_quarantined:
            query += " AND validation_status IN ('VALID', 'VALIDATED')"
        if period_type:
            query += " AND period_type = ?"
            params.append(period_type)
        query += " ORDER BY period ASC LIMIT ?"
        params.append(limit)

        with self._connection() as conn:
            cur = conn.execute(query, params)
            return [dict(row) for row in cur.fetchall()]

    def list_available_periods(self, symbol: str, include_quarantined: bool = False) -> list[str]:
        """Lists all distinct reporting periods available in the database for an issuer."""
        status_clause = "" if include_quarantined else " WHERE validation_status IN ('VALID', 'VALIDATED') AND symbol = ?"
        where_clause = status_clause if not include_quarantined else " WHERE symbol = ?"
        with self._connection() as conn:
            cur = conn.execute(
                f"""
                SELECT DISTINCT period FROM financial_facts
                {where_clause}
                ORDER BY period ASC;
                """,
                (symbol.upper(),),
            )
            return [row["period"] for row in cur.fetchall()]
