"""Effective-dated IDX session, lot, tick and price-limit constraints."""

import json
import math
from datetime import date, datetime, time
from pathlib import Path

from openbagus.domains.equities.data import WIB, timestamp
from openbagus.domains.equities.catalog import source_url


class EquityMarketPolicy:
    def __init__(self, root: Path) -> None:
        local = root / "data/equities/rules.json"
        try:
            self.rules = json.loads((local if local.exists() else root / "config/idx_market_rules.json").read_text(encoding="utf-8"))
            self.validate_rules(self.rules)
        except (OSError, ValueError, KeyError, TypeError):
            self.rules = {}

    @staticmethod
    def validate_rules(rules: dict) -> None:
        source_url(rules["source"])
        if rules.get("timezone") != "Asia/Jakarta" or type(rules.get("lot_size")) is not int or rules["lot_size"] <= 0:
            raise ValueError("Invalid IDX timezone/lot rules")
        dates = [rules.get("effective_from"), rules.get("effective_until")]
        if any(dates) and (not all(dates) or date.fromisoformat(dates[0]) > date.fromisoformat(dates[1])):
            raise ValueError("Invalid rule effective-date interval")
        previous = 0
        bands = rules.get("tick_bands", [])
        if not bands or bands[-1][0] is not None:
            raise ValueError("Incomplete tick bands")
        for upper, tick in bands:
            if not isinstance(tick, (int, float)) or not math.isfinite(tick) or tick <= 0:
                raise ValueError("Invalid tick")
            if upper is not None:
                if not isinstance(upper, (int, float)) or not math.isfinite(upper) or upper <= previous:
                    raise ValueError("Unordered tick bands")
                previous = upper
        for name in ("regular_sessions", "cash_sessions", "negotiated_sessions"):
            for sessions in rules.get(name, {}).values():
                for start, end in sessions:
                    if time.fromisoformat(start) >= time.fromisoformat(end):
                        raise ValueError("Invalid session boundary")
        for day, opened in rules.get("calendar", {}).items():
            date.fromisoformat(day)
            if type(opened) is not bool:
                raise ValueError("Calendar dates require explicit booleans")

    def session_status(self, now: datetime, market: str = "regular") -> str:
        now = now.astimezone(WIB)
        date = now.date().isoformat()
        if now.weekday() >= 5:
            return "CLOSED_WEEKEND"
        start, end = self.rules.get("effective_from"), self.rules.get("effective_until")
        if not start or not end or not start <= date <= end:
            return "RULES_UNVERIFIED"
        day = self.rules.get("calendar", {}).get(date)
        if day is False:
            return "CLOSED_HOLIDAY"
        if day is not True:
            return "CALENDAR_UNVERIFIED"
        key = "fri" if now.weekday() == 4 else "mon_thu"
        sessions = self.rules.get(f"{market}_sessions", {}).get(key, [])
        if not sessions:
            return "MARKET_RULES_UNAVAILABLE"
        clock = now.strftime("%H:%M:%S")
        return "OPEN" if any(a <= clock <= b for a, b in sessions) else "CLOSED_SESSION"

    def tick(self, reference_price: float) -> float:
        if not math.isfinite(reference_price) or reference_price <= 0:
            raise ValueError("Invalid previous-close reference")
        for upper, tick in self.rules.get("tick_bands", []):
            if upper is None or reference_price < upper:
                if tick <= 0:
                    raise ValueError("Invalid tick size")
                return float(tick)
        raise ValueError("Tick schedule unavailable")

    def round_price(self, price: float, reference: float, *, up: bool) -> float:
        tick = self.tick(reference)
        return (math.ceil(price / tick) if up else math.floor(price / tick)) * tick

    def freshness(self, quote: dict, now: datetime) -> str:
        try:
            age = (now - timestamp(quote["as_of"])).total_seconds()
        except (ValueError, TypeError, KeyError):
            return "UNVERIFIED"
        if age < -5:
            return "FUTURE"
        if quote.get("delayed") is not False:
            return "DELAYED_OR_UNVERIFIED"
        if age > 180:
            return "STALE"
        return "FRESH" if self.session_status(now) == "OPEN" else "CLOSED_REFERENCE"

    def position_size(self, entry: float, stop: float, budget: float, risk_pct: float, buy_fee: float, sell_fee: float) -> int:
        if not all(math.isfinite(x) for x in (entry, stop, budget, risk_pct, buy_fee, sell_fee)):
            raise ValueError("Invalid sizing parameters")
        if not 0 < stop < entry or budget <= 0 or not 0 < risk_pct <= 100 or min(buy_fee, sell_fee) < 0 or max(buy_fee, sell_fee) >= 1:
            raise ValueError("Invalid risk/cost inputs")
        lot = int(self.rules.get("lot_size", 0))
        if lot <= 0:
            raise ValueError("Lot size unavailable")
        risk_per_share = entry - stop + entry * buy_fee + stop * sell_fee
        shares = min(budget / (entry * (1 + buy_fee)), budget * risk_pct / 100 / risk_per_share)
        return math.floor(shares / lot) * lot
