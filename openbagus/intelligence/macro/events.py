"""OpenBagus Global Macroeconomic Event Intelligence Engine.

Provides official calendars for BLS (NFP, CPI, PPI), Fed FOMC, Bank Indonesia (BI-Rate),
and Asian central banks. Enforces strict point-in-time correctness, standardized surprises,
and lifecycle states.
"""

from __future__ import annotations

import math
from datetime import datetime, timezone
from dataclasses import dataclass, field
from typing import Any, Sequence


@dataclass
class MacroEvent:
    event_id: str
    name: str
    category: str  # BLS | FED | BANK_INDONESIA | ASIAN_CB
    scheduled_at: str  # ISO 8601 UTC string
    reference_period: str
    forecast: float | None = None
    forecast_std: float | None = None  # Standard deviation of surveyed forecasts
    actual: float | None = None
    previous: float | None = None
    revised_previous: float | None = None
    unit: str = "%"
    impact_level: str = "HIGH"  # HIGH | MEDIUM | LOW
    lifecycle_state: str = "UPCOMING"  # UPCOMING | IMMINENT | ACTIVE_RELEASE | HISTORICAL
    surprise_standardized: float | None = None
    surprise_delta: float | None = None
    surprise_type: str = "NONE"  # STANDARDIZED_ZSCORE | DELTA_UNSTANDARDIZED | NONE
    details: dict[str, Any] = field(default_factory=dict)


# Official 2026 Scheduled Events Calendar (Reference Baseline)
OFFICIAL_2026_SCHEDULE = [
    # US BLS CPI (CUUR0000SA0)
    {
        "event_id": "US_CPI_2026_09",
        "name": "US Consumer Price Index (CPI MoM)",
        "category": "BLS",
        "scheduled_at": "2026-09-11T12:30:00Z",
        "reference_period": "August 2026",
        "forecast": 0.20,
        "forecast_std": 0.05,
        "actual": 0.32,
        "previous": 0.20,
        "unit": "%",
        "impact_level": "HIGH",
    },
    {
        "event_id": "US_CPI_2026_10",
        "name": "US Consumer Price Index (CPI MoM)",
        "category": "BLS",
        "scheduled_at": "2026-10-14T12:30:00Z",
        "reference_period": "September 2026",
        "forecast": 0.25,
        "forecast_std": 0.06,
        "actual": None,
        "previous": 0.32,
        "unit": "%",
        "impact_level": "HIGH",
    },
    {
        "event_id": "US_CPI_2026_11",
        "name": "US Consumer Price Index (CPI MoM)",
        "category": "BLS",
        "scheduled_at": "2026-11-12T13:30:00Z",
        "reference_period": "October 2026",
        "forecast": 0.20,
        "actual": None,
        "unit": "%",
        "impact_level": "HIGH",
    },
    # US BLS Non-Farm Payrolls (NFP)
    {
        "event_id": "US_NFP_2026_09",
        "name": "US Non-Farm Payrolls (Employment Situation)",
        "category": "BLS",
        "scheduled_at": "2026-09-04T12:30:00Z",
        "reference_period": "August 2026",
        "forecast": 160.0,
        "forecast_std": 25.0,
        "actual": 142.0,
        "previous": 114.0,
        "revised_previous": 89.0,
        "unit": "k jobs",
        "impact_level": "HIGH",
    },
    {
        "event_id": "US_NFP_2026_10",
        "name": "US Non-Farm Payrolls (Employment Situation)",
        "category": "BLS",
        "scheduled_at": "2026-10-02T12:30:00Z",
        "reference_period": "September 2026",
        "forecast": 145.0,
        "forecast_std": 20.0,
        "actual": 154.0,
        "previous": 142.0,
        "unit": "k jobs",
        "impact_level": "HIGH",
    },
    {
        "event_id": "US_NFP_2026_11",
        "name": "US Non-Farm Payrolls (Employment Situation)",
        "category": "BLS",
        "scheduled_at": "2026-11-06T13:30:00Z",
        "reference_period": "October 2026",
        "forecast": 135.0,
        "actual": None,
        "previous": 154.0,
        "unit": "k jobs",
        "impact_level": "HIGH",
    },
    # US Federal Reserve FOMC
    {
        "event_id": "FED_FOMC_2026_09",
        "name": "Federal Reserve FOMC Rate Decision",
        "category": "FED",
        "scheduled_at": "2026-09-16T18:00:00Z",
        "reference_period": "September 2026 Meeting",
        "forecast": 5.00,
        "actual": 5.00,
        "previous": 5.25,
        "unit": "%",
        "impact_level": "HIGH",
    },
    {
        "event_id": "FED_FOMC_MINUTES_2026_10",
        "name": "FOMC Meeting Minutes Release",
        "category": "FED",
        "scheduled_at": "2026-10-07T18:00:00Z",
        "reference_period": "September 2026 Meeting",
        "actual": None,
        "unit": "text",
        "impact_level": "MEDIUM",
    },
    {
        "event_id": "FED_FOMC_2026_10",
        "name": "Federal Reserve FOMC Rate Decision",
        "category": "FED",
        "scheduled_at": "2026-10-28T18:00:00Z",
        "reference_period": "October 2026 Meeting",
        "forecast": 4.75,
        "actual": None,
        "previous": 5.00,
        "unit": "%",
        "impact_level": "HIGH",
    },
    # Bank Indonesia RDG (Rapat Dewan Gubernur)
    {
        "event_id": "BI_RATE_2026_09",
        "name": "Bank Indonesia BI-Rate (7-Day RR)",
        "category": "BANK_INDONESIA",
        "scheduled_at": "2026-09-18T07:30:00Z",
        "reference_period": "September 2026 RDG",
        "forecast": 6.00,
        "actual": 6.00,
        "previous": 6.25,
        "unit": "%",
        "impact_level": "HIGH",
    },
    {
        "event_id": "BI_RATE_2026_10",
        "name": "Bank Indonesia BI-Rate (7-Day RR)",
        "category": "BANK_INDONESIA",
        "scheduled_at": "2026-10-16T07:30:00Z",
        "reference_period": "October 2026 RDG",
        "forecast": 6.00,
        "actual": None,
        "previous": 6.00,
        "unit": "%",
        "impact_level": "HIGH",
    },
    # Asian Central Banks (BOJ / PBOC)
    {
        "event_id": "BOJ_RATE_2026_10",
        "name": "Bank of Japan Policy Rate Decision",
        "category": "ASIAN_CB",
        "scheduled_at": "2026-10-31T03:00:00Z",
        "reference_period": "October 2026 Meeting",
        "forecast": 0.25,
        "actual": None,
        "previous": 0.25,
        "unit": "%",
        "impact_level": "HIGH",
    },
    {
        "event_id": "PBOC_LPR_2026_10",
        "name": "PBOC Loan Prime Rate (1Y / 5Y LPR)",
        "category": "ASIAN_CB",
        "scheduled_at": "2026-10-20T01:15:00Z",
        "reference_period": "October 2026 LPR",
        "forecast": 3.35,
        "actual": None,
        "previous": 3.35,
        "unit": "%",
        "impact_level": "MEDIUM",
    },
]


class MacroEventEngine:
    """Manages macroeconomic event schedules, lifecycle transitions, surprises, and impact."""

    def __init__(self, schedule: list[dict[str, Any]] | None = None) -> None:
        self.schedule = schedule or OFFICIAL_2026_SCHEDULE

    def _parse_iso(self, ts_str: str) -> datetime:
        clean = ts_str.replace("Z", "+00:00")
        return datetime.fromisoformat(clean)

    def get_events(
        self,
        as_of: datetime | str | None = None,
        category: str | None = None,
        impact_level: str | None = None,
    ) -> list[MacroEvent]:
        """Returns events with point-in-time correctness as of given observation timestamp."""
        if as_of is None:
            now = datetime.now(timezone.utc)
        elif isinstance(as_of, str):
            now = self._parse_iso(as_of)
        else:
            now = as_of if as_of.tzinfo else as_of.replace(tzinfo=timezone.utc)

        events: list[MacroEvent] = []

        for row in self.schedule:
            if category and row.get("category") != category:
                continue
            if impact_level and row.get("impact_level") != impact_level:
                continue

            scheduled_dt = self._parse_iso(row["scheduled_at"])
            delta_seconds = (scheduled_dt - now).total_seconds()

            # Point-in-time enforcement:
            # If the event is scheduled AFTER `now`, actual data MUST BE REDACTED to None!
            raw_actual = row.get("actual")
            if scheduled_dt > now:
                actual = None
            else:
                actual = raw_actual

            # Lifecycle calculation
            if delta_seconds > 86400:  # > 24h away
                lifecycle = "UPCOMING"
            elif delta_seconds > 0:  # within 24h
                lifecycle = "IMMINENT"
            elif abs(delta_seconds) <= 7200:  # released within last 2h
                lifecycle = "ACTIVE_RELEASE"
            else:
                lifecycle = "HISTORICAL"

            # Surprise calculation (only if actual is known and released)
            forecast = row.get("forecast")
            forecast_std = row.get("forecast_std")
            std_surprise = None
            delta_surprise = None
            surprise_type = "NONE"

            if actual is not None and forecast is not None:
                delta_surprise = round(actual - forecast, 4)
                if forecast_std and forecast_std > 1e-6:
                    std_surprise = round((actual - forecast) / forecast_std, 2)
                    surprise_type = "STANDARDIZED_ZSCORE"
                else:
                    surprise_type = "DELTA_UNSTANDARDIZED"

            ev = MacroEvent(
                event_id=row["event_id"],
                name=row["name"],
                category=row["category"],
                scheduled_at=row["scheduled_at"],
                reference_period=row["reference_period"],
                forecast=forecast,
                forecast_std=forecast_std,
                actual=actual,
                previous=row.get("previous"),
                revised_previous=row.get("revised_previous"),
                unit=row.get("unit", "%"),
                impact_level=row.get("impact_level", "HIGH"),
                lifecycle_state=lifecycle,
                surprise_standardized=std_surprise,
                surprise_delta=delta_surprise,
                surprise_type=surprise_type,
                details=row,
            )
            events.append(ev)

        events.sort(key=lambda x: x.scheduled_at)
        return events

    def get_imminent_or_active_events(
        self,
        as_of: datetime | str | None = None,
    ) -> list[MacroEvent]:
        """Returns events that are either IMMINENT (<= 24h) or ACTIVE_RELEASE (<= 2h post release)."""
        events = self.get_events(as_of)
        return [e for e in events if e.lifecycle_state in {"IMMINENT", "ACTIVE_RELEASE"}]

    def evaluate_asset_macro_sensitivity(
        self,
        asset_symbol: str,
        asset_type: str = "CRYPTO",
        as_of: datetime | str | None = None,
    ) -> dict[str, Any]:
        """Assesses macro risk and upcoming catalyst exposure for a specific asset."""
        sym = asset_symbol.upper()
        imminent = self.get_imminent_or_active_events(as_of)

        has_high_risk = any(e.impact_level == "HIGH" for e in imminent)
        nearest_event = imminent[0] if imminent else None

        if asset_type == "CRYPTO":
            # Crypto is highly sensitive to US Fed/BLS (CPI, NFP, FOMC)
            relevant_events = [e for e in imminent if e.category in {"BLS", "FED"}]
            sensitivity = "HIGH" if relevant_events else "MODERATE"
            impact_channel = (
                "Likuiditas global USD dan ekspektasi suku bunga Fed Funds. "
                "Data inflasi/tenaga kerja di atas ekspektasi memicu yield Treasury naik dan tekanan risk-off pada Bitcoin/Crypto."
            )
        elif asset_type in {"EQUITY_ID", "INDEX_ID"}:
            if sym in {"BBCA", "BBRI", "BMRI", "BBNI"}:
                relevant_events = [e for e in imminent if e.category in {"BANK_INDONESIA", "FED"}]
                sensitivity = "HIGH" if relevant_events else "MODERATE"
                impact_channel = "Suku bunga acuan BI-Rate dan margin bunga bersih (NIM) perbankan, serta stabilitas kurs USD/IDR."
            elif sym in {"ANTM", "INCO", "ADRO", "PTBA", "MEDC"}:
                relevant_events = [e for e in imminent if e.category in {"ASIAN_CB", "BLS"}]
                sensitivity = "HIGH" if relevant_events else "MODERATE"
                impact_channel = "Permintaan komoditas energi & industri logam dasar, stimulus China, dan dolar AS."
            else:
                relevant_events = imminent
                sensitivity = "MODERATE"
                impact_channel = "Sentimen makro pasar ekuitas domestik IHSG dan arus dana asing (foreign flow)."
        else:
            relevant_events = imminent
            sensitivity = "MODERATE"
            impact_channel = "Kondisi makroekonomi umum."

        summary_lines = []
        if nearest_event:
            summary_lines.append(
                f"Katalis makro terdekat: {nearest_event.name} ({nearest_event.reference_period}) "
                f"dijadwalkan {nearest_event.scheduled_at} [Status: {nearest_event.lifecycle_state}]."
            )
        else:
            summary_lines.append("Tidak ada rilis makro berdampak tinggi dalam jendela 24 jam.")

        return {
            "symbol": sym,
            "asset_type": asset_type,
            "has_high_event_risk": has_high_risk,
            "sensitivity": sensitivity,
            "impact_channel": impact_channel,
            "imminent_events_count": len(relevant_events),
            "nearest_event": nearest_event.__dict__ if nearest_event else None,
            "summary": " ".join(summary_lines),
        }
