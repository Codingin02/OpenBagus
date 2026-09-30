"""OpenBagus Real Analysis Engine.

Python-driven quantitative and decision core.
Evaluates data freshness, executes market structure and risk calculations,
builds macro scenario overlays, calculates conviction and actionability scores,
and enforces safety guards.

LLM is interface/critic only and NEVER acts as the numeric decision core.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from openbagus.core.env import get_repo_root
from openbagus.core.guards import guard_payload
from openbagus.core.market_structure import analyze_market_structure
from openbagus.domains.crypto.microstructure import analyze_crypto_microstructure
from openbagus.intelligence.macro.scenario import build_macro_overlay, build_scenario_thesis
from openbagus.risk.metrics import calculate_risk_metrics

ENGINE_VERSION = "openbagus.analysis_engine.v2"
SNAPSHOT_PATH = Path("reports/runtime/openbagus_real_data_snapshot_latest.json")
ANALYSIS_JSON_PATH = Path("reports/runtime/openbagus_real_analysis_latest.json")
ANALYSIS_MD_PATH = Path("reports/runtime/openbagus_real_analysis_latest.md")


def _utc_now() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


def _to_iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)
    except ValueError:
        return None


def _to_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        f = float(value)
        if f != f:  # NaN
            return None
        return f
    except (TypeError, ValueError):
        return None


def _round(value: float | None, digits: int = 4) -> float | None:
    if value is None:
        return None
    return round(float(value), digits)


class DataQualityAgent:
    """Evaluates data freshness and enforces strict data blocking for stale inputs."""

    def __init__(self, snapshot: Mapping[str, Any], generated_at_utc: str) -> None:
        self.snapshot = snapshot
        self.generated_at_utc = generated_at_utc
        self.generated_dt = _parse_iso(generated_at_utc) or _utc_now()

    def evaluate_market_row(self, symbol: str, row: Mapping[str, Any] | None) -> dict[str, Any]:
        if row is None:
            return {
                "symbol": symbol,
                "analysis_status": "STALE_DATA_BLOCKED",
                "freshness_status": "SOURCE_NOT_AVAILABLE",
                "freshness_minutes": None,
                "blocked_reasons": [f"{symbol}: runtime market row is missing or source unavailable."],
            }

        observed = _parse_iso(str(row.get("observed_at_utc", "")))
        age_minutes = None
        if observed is not None:
            age_minutes = max(0.0, round((self.generated_dt - observed).total_seconds() / 60.0, 2))

        asset_class = str(row.get("asset_class", ""))
        freshness_status = str(row.get("freshness_status", "SOURCE_GAP"))
        blocked_reasons: list[str] = []
        analysis_status = "OK"

        if age_minutes is None:
            analysis_status = "STALE_DATA_BLOCKED"
            blocked_reasons.append(f"{symbol}: observed_at_utc is missing or invalid.")
        elif freshness_status == "STALE":
            analysis_status = "STALE_DATA_BLOCKED"
            blocked_reasons.append(f"{symbol}: runtime freshness_status is STALE.")
        elif age_minutes > 1440:  # 24 hours
            analysis_status = "STALE_DATA_BLOCKED"
            blocked_reasons.append(f"{symbol}: market data is older than 24 hours.")
        elif asset_class == "crypto_market" and age_minutes > 720:  # 12 hours for crypto
            analysis_status = "DEGRADED_ANALYSIS"
            blocked_reasons.append(f"{symbol}: crypto data is older than 12 hours.")
        elif freshness_status in {"LAGGING_WITHIN_MAX", "DELAYED_SOURCE"}:
            analysis_status = "DEGRADED_ANALYSIS"

        return {
            "symbol": symbol,
            "analysis_status": analysis_status,
            "freshness_status": freshness_status,
            "freshness_minutes": age_minutes,
            "source_name": row.get("source_name"),
            "provider": row.get("provider"),
            "observed_at_utc": row.get("observed_at_utc"),
            "blocked_reasons": blocked_reasons,
        }

    def summarize_source_health(self) -> dict[str, Any]:
        health_rows = list(self.snapshot.get("source_health", []))
        return {
            "total_sources_attempted": len(health_rows),
            "ok": sum(1 for row in health_rows if row.get("status") == "OK"),
            "warning": sum(1 for row in health_rows if row.get("status") == "WARNING"),
            "fail": sum(1 for row in health_rows if row.get("status") == "FAIL"),
            "sample": health_rows[:8],
        }


class MacroAgent:
    """Synthesizes macro indicators into structured research views."""

    def __init__(self, macro_rows: list[Mapping[str, Any]]) -> None:
        self.macro_rows = macro_rows

    def macro_views(self) -> dict[str, Any]:
        views: dict[str, Any] = {}
        for row in self.macro_rows:
            country = str(row.get("country") or "GLOBAL")
            views.setdefault(country, {"status": "DATA_AVAILABLE", "indicators": []})
            views[country]["indicators"].append({
                "indicator_code": row.get("indicator_code"),
                "indicator_name": row.get("indicator_name"),
                "value": row.get("value"),
                "unit": row.get("unit"),
                "freshness_status": row.get("freshness_status"),
                "source_name": row.get("source_name"),
            })
        if not views:
            views["GLOBAL"] = {
                "status": "SOURCE_NOT_AVAILABLE",
                "reason": "Latest runtime snapshot does not contain macro rows.",
            }
        return views

    def country_overlays(self) -> dict[str, Any]:
        countries = {"US": "United States", "GLOBAL": "Global Macro"}
        overlays = {code: {"country_name": name, "status": "SOURCE_NOT_AVAILABLE"} for code, name in countries.items()}
        for row in self.macro_rows:
            country = str(row.get("country") or "GLOBAL")
            if country in overlays:
                overlays[country] = {
                    "country_name": overlays[country]["country_name"],
                    "status": "DATA_AVAILABLE",
                    "indicator_code": row.get("indicator_code"),
                    "indicator_name": row.get("indicator_name"),
                    "value": row.get("value"),
                    "unit": row.get("unit"),
                    "freshness_status": row.get("freshness_status"),
                    "source_name": row.get("source_name"),
                }
        return overlays


class QuantCoreAgent:
    """Numerical and quantitative decision engine. Calculates scores, stance, and setups."""

    def __init__(self, macro_rows: list[Mapping[str, Any]], macro_views: Mapping[str, Any], country_overlays: Mapping[str, Any]) -> None:
        self.macro_rows = macro_rows
        self.macro_views = macro_views
        self.country_overlays = country_overlays

    def analyze_asset(self, symbol: str, row: Mapping[str, Any] | None, data_quality: Mapping[str, Any]) -> dict[str, Any]:
        blocked = data_quality.get("analysis_status") == "STALE_DATA_BLOCKED"
        rows = [row] if row else []

        if blocked:
            market_structure = {
                "status": "STALE_DATA_BLOCKED",
                "reason": "Fresh market data is required before market structure analysis.",
            }
            risk_metrics = {
                "status": "STALE_DATA_BLOCKED",
                "reason": "Fresh market data is required before risk analysis.",
            }
        else:
            market_structure = analyze_market_structure(rows)
            risk_metrics = calculate_risk_metrics(symbol, rows, macro_rows=self.macro_rows)

        macro_overlay = build_macro_overlay(self.macro_views, self.country_overlays)
        scenario = build_scenario_thesis(
            symbol=symbol,
            market_row=row,
            analysis_status=str(data_quality.get("analysis_status")),
            market_structure=market_structure,
            risk_metrics=risk_metrics,
            macro_overlay=macro_overlay,
        )

        crypto_microstructure = None
        if row and row.get("asset_class") == "crypto_market":
            crypto_microstructure = analyze_crypto_microstructure(symbol, row, self.macro_rows)

        stance_packet = self._portfolio_stance(symbol, row, data_quality, market_structure, risk_metrics, scenario)

        price = _to_float(row.get("price")) if row else None
        return {
            "current_price": price,
            "research_view": self._research_view(symbol, row, data_quality, market_structure, scenario),
            "trade_setup_review": self._trade_setup_review(symbol, data_quality, market_structure),
            "portfolio_stance": stance_packet["portfolio_stance"],
            "conviction_score": stance_packet["conviction_score"],
            "actionability_score": stance_packet["actionability_score"],
            "invalidation_level": stance_packet["invalidation_level"],
            "target_zone": stance_packet["target_zone"],
            "risk_note": stance_packet["risk_note"],
            "data_quality": dict(data_quality),
            "market_structure": market_structure,
            "risk_metrics": risk_metrics,
            "scenario_thesis": scenario,
            "crypto_microstructure": crypto_microstructure,
        }

    def _research_view(
        self,
        symbol: str,
        row: Mapping[str, Any] | None,
        data_quality: Mapping[str, Any],
        market_structure: Mapping[str, Any],
        scenario: Mapping[str, Any],
    ) -> dict[str, Any]:
        if row is None or data_quality.get("analysis_status") == "STALE_DATA_BLOCKED":
            return {
                "symbol": symbol,
                "status": "STALE_DATA_BLOCKED",
                "summary": "Research view is blocked until fresh runtime data is available.",
            }
        return {
            "symbol": symbol,
            "status": data_quality.get("analysis_status"),
            "summary": (
                f"{symbol} exhibits fresh runtime data for quantitative research. "
                f"Market structure status: {market_structure.get('status')}; "
                f"scenario status: {scenario.get('status')}."
            ),
            "source_freshness": data_quality.get("freshness_status"),
        }

    def _trade_setup_review(self, symbol: str, data_quality: Mapping[str, Any], market_structure: Mapping[str, Any]) -> dict[str, Any]:
        if data_quality.get("analysis_status") == "STALE_DATA_BLOCKED":
            return {
                "symbol": symbol,
                "status": "STALE_DATA_BLOCKED",
                "review": "No setup review because freshness guard is blocking this asset.",
            }
        sr = market_structure.get("support_resistance", {})
        return {
            "symbol": symbol,
            "status": "RESEARCH_ONLY",
            "review": "Trade setup is formulated as a quantitative review, not an execution instruction.",
            "support_reference": sr.get("support"),
            "resistance_reference": sr.get("resistance"),
            "freshness_status": data_quality.get("freshness_status"),
        }

    def _portfolio_stance(
        self,
        symbol: str,
        row: Mapping[str, Any] | None,
        data_quality: Mapping[str, Any],
        market_structure: Mapping[str, Any],
        risk_metrics: Mapping[str, Any],
        scenario: Mapping[str, Any],
    ) -> dict[str, Any]:
        if row is None or data_quality.get("analysis_status") == "STALE_DATA_BLOCKED":
            return {
                "portfolio_stance": "Watchlist",
                "conviction_score": 0,
                "actionability_score": 0,
                "invalidation_level": None,
                "target_zone": None,
                "risk_note": "Fresh runtime data is required; numerical evaluation is blocked for this asset.",
            }

        score = 50.0
        actionability = 40.0

        if data_quality.get("analysis_status") == "OK":
            score += 15.0
            actionability += 15.0
        elif data_quality.get("analysis_status") == "DEGRADED_ANALYSIS":
            score -= 5.0
            actionability -= 10.0

        sr = market_structure.get("support_resistance", {})
        range_position = _to_float(sr.get("range_position"))
        if range_position is not None:
            if 0.35 <= range_position <= 0.70:
                score += 5.0
            elif range_position > 0.85:
                score -= 4.0
                actionability -= 5.0
            elif range_position < 0.20:
                score -= 3.0

        if risk_metrics.get("status") != "OK":
            score -= 8.0
            actionability -= 8.0

        base_probability = _to_float((scenario.get("scenario_probability") or {}).get("base"))
        if base_probability is not None:
            score += (base_probability - 0.40) * 20.0

        score = max(0.0, min(100.0, score))
        actionability = max(0.0, min(100.0, actionability))

        if score >= 68 and actionability >= 55:
            stance = "Accumulate-on-weakness"
        elif score >= 48:
            stance = "Hold"
        elif score >= 32:
            stance = "Watchlist"
        else:
            stance = "Avoid"

        support = _to_float(sr.get("support"))
        resistance = _to_float(sr.get("resistance"))
        price = _to_float(row.get("price"))
        invalidation = support
        if support is not None and price is not None:
            invalidation = support - abs(price - support) * 0.20

        target_zone = None
        if support is not None and resistance is not None:
            target_zone = [_round(support, 2), _round(resistance, 2)]

        return {
            "portfolio_stance": stance,
            "conviction_score": int(round(score)),
            "actionability_score": int(round(actionability)),
            "invalidation_level": _round(invalidation, 2),
            "target_zone": target_zone,
            "risk_note": "Quantitative stance; always respect invalidation and liquidity constraints.",
        }


class OpenBagusAnalysisEngine:
    """Master research analysis engine for OpenBagus."""

    def __init__(self, repo_root: Path | None = None) -> None:
        self.root = repo_root or get_repo_root()

    def run(self, *, assets: list[str] | None = None, all_core: bool = False) -> dict[str, Any]:
        snapshot_path = self.root / SNAPSHOT_PATH
        if not snapshot_path.exists():
            raise FileNotFoundError(f"Runtime ingestion snapshot not found: {snapshot_path}")

        with snapshot_path.open("r", encoding="utf-8") as f:
            snapshot = json.load(f)

        generated_at_utc = _to_iso(_utc_now())
        market_rows = list(snapshot.get("market_rows", []))
        macro_rows = list(snapshot.get("macro_rows", []))
        market_by_symbol = {str(row.get("symbol")): row for row in market_rows}

        # Select symbols
        if not assets:
            selected = list(market_by_symbol.keys())
        else:
            selected = [a for a in assets if a in market_by_symbol]

        data_quality_agent = DataQualityAgent(snapshot, generated_at_utc)
        macro_agent = MacroAgent(macro_rows)
        macro_views = macro_agent.macro_views()
        country_overlays = macro_agent.country_overlays()
        quant_agent = QuantCoreAgent(macro_rows, macro_views, country_overlays)

        asset_views: dict[str, Any] = {}
        blocked_reasons: list[str] = []

        for symbol in selected:
            row = market_by_symbol.get(symbol)
            data_quality = data_quality_agent.evaluate_market_row(symbol, row)
            blocked_reasons.extend(data_quality["blocked_reasons"])
            view = quant_agent.analyze_asset(symbol, row, data_quality)
            view["llm_critic"] = {
                "symbol": symbol,
                "status": "INTERFACE_ONLY",
                "llm_called": False,
                "note": "LLM critic interface is advisory and never overrides numerical quant engine calculations.",
            }
            asset_views[symbol] = view

        # Freshness summary
        statuses = [v["data_quality"]["analysis_status"] for v in asset_views.values()]
        if any(s == "STALE_DATA_BLOCKED" for s in statuses):
            overall_status = "STALE_DATA_BLOCKED"
        elif any(s == "DEGRADED_ANALYSIS" for s in statuses):
            overall_status = "DEGRADED_ANALYSIS"
        else:
            overall_status = "OK"

        payload_raw = {
            "engine_version": ENGINE_VERSION,
            "platform": "OpenBagus",
            "active_domain": "crypto",
            "generated_at_utc": generated_at_utc,
            "runtime_input": {
                "source": str(SNAPSHOT_PATH),
                "run_id": snapshot.get("run_id"),
                "generated_at_utc": snapshot.get("generated_at_utc"),
            },
            "selected_symbols": selected,
            "data_freshness_summary": {
                "overall_analysis_status": overall_status,
                "by_asset": {sym: view["data_quality"] for sym, view in asset_views.items()},
            },
            "source_health_summary": data_quality_agent.summarize_source_health(),
            "asset_views": asset_views,
            "macro_views": macro_views,
            "blocked_reasons": blocked_reasons,
        }

        # Format markdown
        markdown = self._generate_markdown(payload_raw)

        # Apply compliance guard
        compliance_guard = guard_payload(payload_raw, markdown)
        payload = dict(payload_raw)
        payload["compliance_guard"] = compliance_guard

        # Re-render markdown if needed
        markdown = self._generate_markdown(payload)

        # Write reports
        self._write_reports(payload, markdown)
        return payload

    def _generate_markdown(self, payload: dict[str, Any]) -> str:
        lines = [
            "# OpenBagus Quantitative Research Analysis",
            "",
            f"- Platform: `OpenBagus`",
            f"- Active Domain: `crypto`",
            f"- Generated At (UTC): `{payload['generated_at_utc']}`",
            f"- Overall Freshness Status: `{payload['data_freshness_summary']['overall_analysis_status']}`",
            f"- Numeric Decision Core: `Python Quant Engine (Standalone)`",
            "",
            "## Asset Quantitative Stance",
            "",
            "| Asset | Status | Freshness | Stance | Conviction | Actionability | Invalidation | Risk Note |",
            "| --- | --- | --- | --- | ---: | ---: | ---: | --- |",
        ]
        for symbol, view in payload.get("asset_views", {}).items():
            dq = view["data_quality"]
            inv = f"${view['invalidation_level']:,.2f}" if view.get("invalidation_level") else "N/A"
            lines.append(
                f"| {symbol} | {dq['analysis_status']} | {dq['freshness_status']} | "
                f"**{view['portfolio_stance']}** | {view['conviction_score']}/100 | "
                f"{view['actionability_score']}/100 | {inv} | {view['risk_note']} |"
            )

        lines.extend([
            "",
            "## Invalidation & Setup Details",
            "",
        ])
        for symbol, view in payload.get("asset_views", {}).items():
            ms = view.get("market_structure", {})
            cm = view.get("crypto_microstructure", {})
            lines.extend([
                f"### {symbol}",
                f"- Regime: `{ms.get('regime', 'UNKNOWN')}`",
                f"- Setup: `{view.get('trade_setup_review', {}).get('review', '')}`",
                f"- Target Zone: `{view.get('target_zone')}`",
                f"- Microstructure Status: `{cm.get('status', 'N/A') if cm else 'N/A'}`",
                "",
            ])

        lines.extend([
            "## Source Health & Compliance",
            "",
            f"- Total Sources: `{payload['source_health_summary']['total_sources_attempted']}`",
            f"- OK: `{payload['source_health_summary']['ok']}`",
            f"- Warning: `{payload['source_health_summary']['warning']}`",
            f"- Fail: `{payload['source_health_summary']['fail']}`",
            "",
            "> **Research Note:** OpenBagus generates quantitative analytics and research setups only. "
            "It does not place trades, custody funds, or execute automated exchange orders.",
            "",
        ])
        return "\n".join(lines)

    def _write_reports(self, payload: dict[str, Any], markdown: str) -> None:
        runtime_dir = self.root / "reports/runtime"
        runtime_dir.mkdir(parents=True, exist_ok=True)

        json_path = self.root / ANALYSIS_JSON_PATH
        with json_path.open("w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2)

        md_path = self.root / ANALYSIS_MD_PATH
        with md_path.open("w", encoding="utf-8") as f:
            f.write(markdown)


def run_real_analysis(
    *,
    assets: list[str] | None = None,
    idx_symbols: list[str] | None = None,
    all_core: bool = False,
    repo_root: Path | None = None,
) -> dict[str, Any]:
    """Convenience functional wrapper for OpenBagusAnalysisEngine."""
    engine = OpenBagusAnalysisEngine(repo_root=repo_root)
    return engine.run(assets=assets, all_core=all_core)
