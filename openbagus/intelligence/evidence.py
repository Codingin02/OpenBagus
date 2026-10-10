"""Canonical Financial Evidence Engine for OpenBagus.

Grounds all quantitative decisions, local LLM narratives, and CLI presentations
in structured, typed, traceable financial metrics.

Operating Principle:
USER QUESTION -> INTENT -> RELEVANT DATA -> VERIFICATION -> CALCULATIONS
-> EVIDENCE COMPARISON -> QUANT DECISION -> LOCAL AI NARRATIVE -> CITED OUTPUT
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum
from typing import Any, Mapping


class FactCategory(str, Enum):
    """Rigorous categorization of financial assertions."""
    OBSERVED = "OBSERVED"        # Directly obtained market or economic observations
    CALCULATED = "CALCULATED"    # Deterministic results using recorded inputs and formulas
    REPORTED = "REPORTED"        # Claims by identifiable original publisher/institution
    INFERRED = "INFERRED"        # Interpretations logically derived from supported evidence
    HYPOTHESIS = "HYPOTHESIS"    # Conditional assumptions requiring additional testing
    SIMULATED = "SIMULATED"      # Outputs from historical or hypothetical simulation


class IndependenceGroup(str, Enum):
    """Independent evidence families to prevent counting correlated indicators as multiple proofs."""
    PRICE_STRUCTURE = "PRICE_STRUCTURE"        # OHLCV, swing highs/lows, S/R, breakouts
    ORDERBOOK_LIQUIDITY = "ORDERBOOK_LIQUIDITY"  # Depth, bid/ask spread, orderbook imbalance
    DERIVATIVES = "DERIVATIVES"                # Funding rate, open interest, basis, liquidations
    MOMENTUM_OSCILLATOR = "MOMENTUM_OSCILLATOR"  # RSI, Stochastic, MACD (correlated to price)
    VOLATILITY = "VOLATILITY"                  # ATR, Bollinger width, historical volatility
    FUNDAMENTALS = "FUNDAMENTALS"              # Financial statements, earnings, ratios, ownership
    MACRO_EVENT = "MACRO_EVENT"                # CPI, NFP, Fed rate, BI rate, GDP, PMI
    COMMODITY_FX = "COMMODITY_FX"              # Oil, gold, nickel, DXY, USD/IDR
    ARBITRAGE_DISLOCATION = "ARBITRAGE"        # Cross-venue spreads, fee-adjusted dislocations
    NEWS_PROVENANCE = "NEWS"                  # Verified regulatory/corporate disclosures


@dataclass
class EvidenceMetric:
    """Traceable individual metric record."""
    metric_id: str
    asset_id: str
    metric_type: str
    numeric_value: float | int | None
    unit: str
    market: str
    timeframe: str
    observation_time: str
    retrieval_time: str
    source_id: str
    calculation_method: str = "DIRECT_OBSERVATION"
    input_metric_ids: list[str] = field(default_factory=list)
    freshness_status: str = "FRESH"
    quality_status: str = "HIGH"
    independence_group: IndependenceGroup = IndependenceGroup.PRICE_STRUCTURE
    category: FactCategory = FactCategory.OBSERVED
    description: str = ""

    def formatted_value(self) -> str:
        if self.numeric_value is None:
            return "N/A"
        if self.unit == "USD":
            if abs(self.numeric_value) >= 1:
                return f"${self.numeric_value:,.2f}"
            return f"${self.numeric_value:.6f}".rstrip("0").rstrip(".")
        if self.unit == "IDR":
            return f"Rp{self.numeric_value:,.0f}"
        if self.unit == "%":
            return f"{self.numeric_value:+.2f}%" if self.numeric_value != 0 else "0.00%"
        if self.unit == "x":
            return f"{self.numeric_value:.2f}x"
        if self.unit == "ratio":
            return f"1:{self.numeric_value:.2f}"
        if isinstance(self.numeric_value, float):
            return f"{self.numeric_value:,.2f}"
        return f"{self.numeric_value:,}"


@dataclass
class DerivedSetupMetrics:
    """Validated geometric and fee-adjusted trade scenario levels."""
    entry: float | None = None
    stop: float | None = None
    target: float | None = None
    risk_distance: float | None = None
    reward_distance: float | None = None
    gross_rr: float | None = None
    estimated_cost: float | None = None
    net_risk: float | None = None
    net_reward: float | None = None
    net_rr: float | None = None
    trigger_level: float | None = None
    trigger_state: str = "UNCONFIRMED"
    scenario_type: str = "CONDITIONAL"

    @classmethod
    def calculate(
        cls,
        entry: float | None,
        stop: float | None,
        target: float | None,
        roundtrip_fee_pct: float = 0.0012,
        trigger_level: float | None = None,
        trigger_state: str = "UNCONFIRMED",
        scenario_type: str = "CONDITIONAL",
    ) -> DerivedSetupMetrics:
        if entry is None or stop is None or target is None:
            return cls(
                entry=entry, stop=stop, target=target,
                trigger_level=trigger_level, trigger_state=trigger_state,
                scenario_type=scenario_type,
            )

        is_long = target > entry
        risk_dist = abs(entry - stop)
        reward_dist = abs(target - entry)
        gross_rr = reward_dist / risk_dist if risk_dist > 0 else 0.0

        # Cost deduction
        cost = entry * roundtrip_fee_pct
        if is_long:
            net_reward = max(0.0, reward_dist - cost)
            net_risk = risk_dist + cost
        else:
            net_reward = max(0.0, reward_dist - cost)
            net_risk = risk_dist + cost
        net_rr = net_reward / net_risk if net_risk > 0 else 0.0

        return cls(
            entry=entry,
            stop=stop,
            target=target,
            risk_distance=risk_dist,
            reward_distance=reward_dist,
            gross_rr=round(gross_rr, 2),
            estimated_cost=round(cost, 2),
            net_risk=round(net_risk, 2),
            net_reward=round(net_reward, 2),
            net_rr=round(net_rr, 2),
            trigger_level=trigger_level,
            trigger_state=trigger_state,
            scenario_type=scenario_type,
        )


@dataclass
class EvidencePacket:
    """Canonical collection of validated financial facts for one research request."""
    asset: str
    market: str
    timeframe: str
    currency: str = "USD"
    asset_type: str = "CRYPTO"
    decision: str = "NO_TRADE"
    decision_reason: str = ""
    regime: str = "Compressed"
    observation_timestamp: str = ""
    retrieval_timestamp: str = ""
    metrics: dict[str, EvidenceMetric] = field(default_factory=dict)
    derived_setup: DerivedSetupMetrics | None = None
    contradictions: list[str] = field(default_factory=list)
    confirming_evidence: list[str] = field(default_factory=list)
    cited_sources: list[dict[str, Any]] = field(default_factory=list)
    heuristic_weights: dict[str, float] = field(default_factory=dict)
    data_quality: str = "HIGH"
    data_freshness: str = "FRESH"

    def add_metric(self, metric: EvidenceMetric) -> None:
        self.metrics[metric.metric_id] = metric

    def get_metric(self, metric_id: str) -> EvidenceMetric | None:
        return self.metrics.get(metric_id)

    def get_valid_numbers(self) -> set[Decimal]:
        """Extract all legitimate numbers from metrics and derived calculations for grounding."""
        valid: set[Decimal] = set()

        def _add_num(v: float | int | None) -> None:
            if v is None:
                return
            try:
                d = Decimal(str(v))
                valid.add(d)
                for places in (2, 4, 0):
                    r = round(d, places)
                    if d == 0 or r != 0:
                        valid.add(r)
            except Exception:
                pass

        for m in self.metrics.values():
            _add_num(m.numeric_value)

        if self.derived_setup:
            ds = self.derived_setup
            for v in (
                ds.entry, ds.stop, ds.target, ds.risk_distance, ds.reward_distance,
                ds.gross_rr, ds.estimated_cost, ds.net_risk, ds.net_reward, ds.net_rr,
                ds.trigger_level,
            ):
                _add_num(v)

        return valid

    def independent_confirmation_count(self) -> int:
        """Counts how many distinct independence groups confirm the directional thesis."""
        groups: set[IndependenceGroup] = set()
        for m in self.metrics.values():
            if m.category in (FactCategory.OBSERVED, FactCategory.CALCULATED) and m.quality_status in ("HIGH", "MEDIUM"):
                groups.add(m.independence_group)
        return len(groups)

    def summary_table(self) -> str:
        """Renders a compact markdown/ASCII table of primary metrics."""
        lines = [
            f"| Metrik | Nilai | Tipe | Kategori | Sumber |",
            f"| :--- | :--- | :--- | :--- | :--- |",
        ]
        for m in sorted(self.metrics.values(), key=lambda x: x.metric_type):
            lines.append(f"| {m.metric_type} | {m.formatted_value()} | {m.independence_group.value} | {m.category.value} | {m.source_id} |")
        return "\n".join(lines)


def build_evidence_packet_from_research(
    packet: Any,
    quant_result: Any = None,
    roundtrip_fee_pct: float = 0.0012,
) -> EvidencePacket:
    """Builds a canonical EvidencePacket from existing ResearchPacket and QuantDecisionResult."""
    now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    asset = getattr(packet, "asset", "ASSET")
    market = getattr(packet, "market", "SPOT")
    tf = getattr(packet, "timeframe", "H1")
    currency = getattr(packet, "currency", "USD")
    asset_type = getattr(packet, "asset_type", "CRYPTO")
    price = float(getattr(packet, "price", 0.0) or 0.0)
    decision = getattr(packet, "decision", "NO_TRADE")
    reason = getattr(packet, "decision_reason", getattr(packet, "reason", ""))
    regime = getattr(packet, "regime", "Compressed")
    quality = getattr(packet, "data_quality", "HIGH")
    freshness = getattr(packet, "data_freshness", "FRESH")

    ep = EvidencePacket(
        asset=asset,
        market=market,
        timeframe=tf,
        currency=currency,
        asset_type=asset_type,
        decision=decision,
        decision_reason=reason,
        regime=regime,
        observation_timestamp=getattr(packet, "price_as_of", "") or now_iso,
        retrieval_timestamp=now_iso,
        contradictions=list(getattr(packet, "contradictions", []) or []),
        data_quality=quality,
        data_freshness=freshness,
    )

    # 1. Base Price Metric
    if price > 0:
        ep.add_metric(EvidenceMetric(
            metric_id=f"{asset}_PRICE",
            asset_id=asset,
            metric_type="PRICE",
            numeric_value=price,
            unit=currency,
            market=market,
            timeframe=tf,
            observation_time=ep.observation_timestamp,
            retrieval_time=now_iso,
            source_id="MARKET_TICKER",
            category=FactCategory.OBSERVED,
            independence_group=IndependenceGroup.PRICE_STRUCTURE,
            description="Latest traded or top-of-book reference price",
        ))

    # 2. Extract Scenario and Derived Levels
    scenario = None
    if hasattr(packet, "bullish_validation") and packet.bullish_validation:
        scenario = packet.bullish_validation
    elif hasattr(packet, "bearish_validation") and packet.bearish_validation:
        scenario = packet.bearish_validation

    entry_val = None
    stop_val = getattr(packet, "stop_price", None)
    target_val = getattr(packet, "tp1", None)
    trigger_level = None
    trigger_state = "UNCONFIRMED"

    if scenario:
        trigger_level = getattr(scenario, "trigger_level", None)
        trigger_state = getattr(scenario, "trigger_state", "UNCONFIRMED")
        entry_val = getattr(scenario, "entry_price", None) or getattr(scenario, "entry_zone", None)
        if isinstance(entry_val, str):
            # parse numeric entry from string like "$65,400"
            m = re.search(r"[\$Rp]?\s*([0-9,]+(?:\.[0-9]+)?)", entry_val)
            if m:
                try:
                    entry_val = float(m.group(1).replace(",", ""))
                except Exception:
                    entry_val = None
            else:
                entry_val = None
        if stop_val is None:
            stop_val = getattr(scenario, "stop_price", None)
        if target_val is None:
            target_val = getattr(scenario, "tp1", None)

    if entry_val is None and price > 0 and decision in ("BUY", "LONG", "SHORT"):
        entry_val = price

    if entry_val and stop_val and target_val:
        ds = DerivedSetupMetrics.calculate(
            entry=float(entry_val),
            stop=float(stop_val),
            target=float(target_val),
            roundtrip_fee_pct=roundtrip_fee_pct,
            trigger_level=float(trigger_level) if trigger_level is not None else None,
            trigger_state=trigger_state,
        )
        ep.derived_setup = ds

        # Add derived metrics into packet
        ep.add_metric(EvidenceMetric(
            metric_id=f"{asset}_ENTRY", asset_id=asset, metric_type="ENTRY",
            numeric_value=ds.entry, unit=currency, market=market, timeframe=tf,
            observation_time=ep.observation_timestamp, retrieval_time=now_iso,
            source_id="QUANT_ENGINE", category=FactCategory.CALCULATED,
            independence_group=IndependenceGroup.PRICE_STRUCTURE,
        ))
        ep.add_metric(EvidenceMetric(
            metric_id=f"{asset}_STOP", asset_id=asset, metric_type="STOP",
            numeric_value=ds.stop, unit=currency, market=market, timeframe=tf,
            observation_time=ep.observation_timestamp, retrieval_time=now_iso,
            source_id="QUANT_ENGINE", category=FactCategory.CALCULATED,
            independence_group=IndependenceGroup.PRICE_STRUCTURE,
        ))
        ep.add_metric(EvidenceMetric(
            metric_id=f"{asset}_TARGET", asset_id=asset, metric_type="TARGET",
            numeric_value=ds.target, unit=currency, market=market, timeframe=tf,
            observation_time=ep.observation_timestamp, retrieval_time=now_iso,
            source_id="QUANT_ENGINE", category=FactCategory.CALCULATED,
            independence_group=IndependenceGroup.PRICE_STRUCTURE,
        ))
        ep.add_metric(EvidenceMetric(
            metric_id=f"{asset}_RISK_DIST", asset_id=asset, metric_type="RISK_DISTANCE",
            numeric_value=ds.risk_distance, unit=currency, market=market, timeframe=tf,
            observation_time=ep.observation_timestamp, retrieval_time=now_iso,
            source_id="QUANT_ENGINE", category=FactCategory.CALCULATED,
            calculation_method="abs(entry - stop)",
            independence_group=IndependenceGroup.PRICE_STRUCTURE,
        ))
        ep.add_metric(EvidenceMetric(
            metric_id=f"{asset}_REWARD_DIST", asset_id=asset, metric_type="REWARD_DISTANCE",
            numeric_value=ds.reward_distance, unit=currency, market=market, timeframe=tf,
            observation_time=ep.observation_timestamp, retrieval_time=now_iso,
            source_id="QUANT_ENGINE", category=FactCategory.CALCULATED,
            calculation_method="abs(target - entry)",
            independence_group=IndependenceGroup.PRICE_STRUCTURE,
        ))
        ep.add_metric(EvidenceMetric(
            metric_id=f"{asset}_GROSS_RR", asset_id=asset, metric_type="GROSS_RR",
            numeric_value=ds.gross_rr, unit="ratio", market=market, timeframe=tf,
            observation_time=ep.observation_timestamp, retrieval_time=now_iso,
            source_id="QUANT_ENGINE", category=FactCategory.CALCULATED,
            calculation_method="reward_dist / risk_dist",
            independence_group=IndependenceGroup.PRICE_STRUCTURE,
        ))
        ep.add_metric(EvidenceMetric(
            metric_id=f"{asset}_NET_RR", asset_id=asset, metric_type="NET_RR",
            numeric_value=ds.net_rr, unit="ratio", market=market, timeframe=tf,
            observation_time=ep.observation_timestamp, retrieval_time=now_iso,
            source_id="QUANT_ENGINE", category=FactCategory.CALCULATED,
            calculation_method="net_reward / net_risk",
            independence_group=IndependenceGroup.PRICE_STRUCTURE,
        ))
        ep.add_metric(EvidenceMetric(
            metric_id=f"{asset}_COST_EST", asset_id=asset, metric_type="ESTIMATED_COST",
            numeric_value=ds.estimated_cost, unit=currency, market=market, timeframe=tf,
            observation_time=ep.observation_timestamp, retrieval_time=now_iso,
            source_id="QUANT_ENGINE", category=FactCategory.CALCULATED,
            calculation_method="entry * fee_rate",
            independence_group=IndependenceGroup.PRICE_STRUCTURE,
        ))

    # 3. Microstructure & Indicators
    stoch = getattr(packet, "stochastic", {})
    if stoch.get("material") and isinstance(stoch.get("values"), dict):
        vals = stoch["values"]
        if vals.get("k") is not None:
            ep.add_metric(EvidenceMetric(
                metric_id=f"{asset}_STOCH_K", asset_id=asset, metric_type="STOCH_K",
                numeric_value=float(vals["k"]), unit="", market=market, timeframe=tf,
                observation_time=ep.observation_timestamp, retrieval_time=now_iso,
                source_id="STOCHASTIC_INDICATOR", category=FactCategory.CALCULATED,
                independence_group=IndependenceGroup.MOMENTUM_OSCILLATOR,
            ))
        if vals.get("d") is not None:
            ep.add_metric(EvidenceMetric(
                metric_id=f"{asset}_STOCH_D", asset_id=asset, metric_type="STOCH_D",
                numeric_value=float(vals["d"]), unit="", market=market, timeframe=tf,
                observation_time=ep.observation_timestamp, retrieval_time=now_iso,
                source_id="STOCHASTIC_INDICATOR", category=FactCategory.CALCULATED,
                independence_group=IndependenceGroup.MOMENTUM_OSCILLATOR,
            ))

    # 4. Arbitrage Dislocation
    arb = getattr(packet, "arbitrage", {})
    if arb.get("material") and isinstance(arb.get("values"), dict):
        vals = arb["values"]
        spread_pct = vals.get("estimated_net_spread_pct")
        if spread_pct is not None:
            ep.add_metric(EvidenceMetric(
                metric_id=f"{asset}_ARB_NET_SPREAD", asset_id=asset, metric_type="ARB_NET_SPREAD",
                numeric_value=float(spread_pct), unit="%", market="CROSS_EXCHANGE", timeframe=tf,
                observation_time=ep.observation_timestamp, retrieval_time=now_iso,
                source_id="ARBITRAGE_ENGINE", category=FactCategory.CALCULATED,
                independence_group=IndependenceGroup.ARBITRAGE_DISLOCATION,
            ))

    # 5. Fundamental ratios for Equities
    fund = getattr(packet, "fundamentals", {})
    if isinstance(fund, dict):
        ratios = fund.get("ratios", {})
        for r_name, r_val in ratios.items():
            if isinstance(r_val, (int, float)):
                ep.add_metric(EvidenceMetric(
                    metric_id=f"{asset}_{r_name.upper()}", asset_id=asset, metric_type=r_name.upper(),
                    numeric_value=float(r_val), unit="x" if "pe" in r_name.lower() or "pbv" in r_name.lower() else "%",
                    market="IDX", timeframe="D1",
                    observation_time=fund.get("period", ep.observation_timestamp), retrieval_time=now_iso,
                    source_id=fund.get("source", "IDX_FINANCIALS"), category=FactCategory.REPORTED,
                    independence_group=IndependenceGroup.FUNDAMENTALS,
                ))

    return ep
