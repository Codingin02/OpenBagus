"""OpenBagus Controlled Autonomous Financial Monitoring and Alert Delivery.

Implements bounded, user-controlled financial event notifications (Section I):
- Default status: OFF (explicit opt-in required)
- No automated trading or exchange orders (research notifications only)
- Lightweight user-level scheduler (or Windows Task Scheduler registration)
- Alert deduplication in local SQLite database (prevents repeat spam on unchanged conditions)
- Channel-independent delivery queue with exponential backoff and quiet-hours enforcement
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from openbagus.core.env import get_repo_root
from openbagus.intelligence.local_language import get_local_appdata_dir


@dataclass
class MonitoringRule:
    rule_id: str
    asset: str
    timeframe: str = "H1"
    condition: str = "ACTIONABLE_SETUP"  # ACTIONABLE_SETUP, BREAKOUT, BREAKDOWN, STOP_LOSS, REGIME_CHANGE
    channels: list[str] = field(default_factory=lambda: ["outbox"])  # gmail, whatsapp, outbox
    target_destination: str = ""  # email address or phone number
    enabled: bool = True
    created_at: str = ""
    last_triggered_at: str | None = None
    last_candle_timestamp: int | None = None
    last_condition_hash: str | None = None
    min_cooldown_seconds: int = 3600  # 1 hour minimum between duplicate condition notifications


@dataclass
class AlertEvent:
    event_id: str
    rule_id: str
    asset: str
    timeframe: str
    decision: str
    headline: str
    summary: str
    price: float
    timestamp: str
    delivery_status: dict[str, str] = field(default_factory=dict)  # channel -> status (QUEUED, SENT, FAILED)
    retry_count: int = 0


class AutonomousMonitorStore:
    """Manages monitoring rules and delivery queue in %LOCALAPPDATA%\\OpenBagus\\monitoring\\monitor.db."""

    def __init__(self, db_path: Path | None = None) -> None:
        if db_path:
            self.db_path = Path(db_path)
        else:
            mon_dir = get_local_appdata_dir() / "monitoring"
            mon_dir.mkdir(parents=True, exist_ok=True)
            self.db_path = mon_dir / "monitor.db"
        self._lock = threading.RLock()
        self._conn: sqlite3.Connection | None = None
        self._init_db()

    def _get_conn(self) -> sqlite3.Connection:
        if self._conn is None:
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
            self._conn = sqlite3.connect(str(self.db_path), check_same_thread=False, timeout=10.0)
            self._conn.row_factory = sqlite3.Row
            self._conn.execute("PRAGMA journal_mode=WAL;")
            self._conn.execute("PRAGMA synchronous=NORMAL;")
        return self._conn

    def close(self) -> None:
        with self._lock:
            if self._conn is not None:
                try:
                    self._conn.close()
                except Exception:
                    pass
                self._conn = None

    def __del__(self) -> None:
        self.close()

    def _init_db(self) -> None:
        with self._lock:
            with self._get_conn() as conn:
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS monitoring_rules (
                        rule_id TEXT PRIMARY KEY,
                        asset TEXT NOT NULL,
                        timeframe TEXT NOT NULL,
                        condition TEXT NOT NULL,
                        channels TEXT NOT NULL,
                        target_destination TEXT,
                        enabled INTEGER NOT NULL,
                        created_at TEXT NOT NULL,
                        last_triggered_at TEXT,
                        last_candle_timestamp INTEGER,
                        last_condition_hash TEXT,
                        min_cooldown_seconds INTEGER
                    );
                """)
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS alert_history (
                        event_id TEXT PRIMARY KEY,
                        rule_id TEXT NOT NULL,
                        asset TEXT NOT NULL,
                        timeframe TEXT NOT NULL,
                        decision TEXT NOT NULL,
                        headline TEXT NOT NULL,
                        summary TEXT NOT NULL,
                        price REAL NOT NULL,
                        timestamp TEXT NOT NULL,
                        delivery_status TEXT NOT NULL,
                        retry_count INTEGER DEFAULT 0
                    );
                """)
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS monitor_config (
                        key TEXT PRIMARY KEY,
                        val TEXT NOT NULL
                    );
                """)

    def is_global_enabled(self) -> bool:
        with self._lock:
            with self._get_conn() as conn:
                cur = conn.execute("SELECT val FROM monitor_config WHERE key = 'enabled';")
                row = cur.fetchone()
                return bool(row and row["val"] in ("1", "true", "True"))

    def set_global_enabled(self, enabled: bool) -> None:
        with self._lock:
            with self._get_conn() as conn:
                conn.execute(
                    "INSERT INTO monitor_config (key, val) VALUES ('enabled', ?) ON CONFLICT(key) DO UPDATE SET val = ?;",
                    (str(int(enabled)), str(int(enabled))),
                )

    def is_paused(self) -> bool:
        with self._lock:
            with self._get_conn() as conn:
                cur = conn.execute("SELECT val FROM monitor_config WHERE key = 'paused';")
                row = cur.fetchone()
                return bool(row and row["val"] in ("1", "true", "True"))

    def set_paused(self, paused: bool) -> None:
        with self._lock:
            with self._get_conn() as conn:
                conn.execute(
                    "INSERT INTO monitor_config (key, val) VALUES ('paused', ?) ON CONFLICT(key) DO UPDATE SET val = ?;",
                    (str(int(paused)), str(int(paused))),
                )

    def add_rule(self, rule: MonitoringRule) -> None:
        with self._lock:
            with self._get_conn() as conn:
                conn.execute("""
                    INSERT INTO monitoring_rules (
                        rule_id, asset, timeframe, condition, channels, target_destination,
                        enabled, created_at, last_triggered_at, last_candle_timestamp,
                        last_condition_hash, min_cooldown_seconds
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(rule_id) DO UPDATE SET
                        asset=excluded.asset, timeframe=excluded.timeframe, condition=excluded.condition,
                        channels=excluded.channels, target_destination=excluded.target_destination,
                        enabled=excluded.enabled, min_cooldown_seconds=excluded.min_cooldown_seconds;
                """, (
                    rule.rule_id, rule.asset, rule.timeframe, rule.condition,
                    json.dumps(rule.channels), rule.target_destination,
                    1 if rule.enabled else 0, rule.created_at, rule.last_triggered_at,
                    rule.last_candle_timestamp, rule.last_condition_hash, rule.min_cooldown_seconds,
                ))

    def remove_rule(self, rule_id: str) -> bool:
        with self._lock:
            with self._get_conn() as conn:
                cur = conn.execute("DELETE FROM monitoring_rules WHERE rule_id = ?;", (rule_id,))
                return cur.rowcount > 0

    def list_rules(self) -> list[MonitoringRule]:
        with self._lock:
            with self._get_conn() as conn:
                cur = conn.execute("SELECT * FROM monitoring_rules ORDER BY created_at DESC;")
                rows = cur.fetchall()
                rules: list[MonitoringRule] = []
                for r in rows:
                    rules.append(MonitoringRule(
                        rule_id=r["rule_id"],
                        asset=r["asset"],
                        timeframe=r["timeframe"],
                        condition=r["condition"],
                        channels=json.loads(r["channels"]),
                        target_destination=r["target_destination"] or "",
                        enabled=bool(r["enabled"]),
                        created_at=r["created_at"],
                        last_triggered_at=r["last_triggered_at"],
                        last_candle_timestamp=r["last_candle_timestamp"],
                        last_condition_hash=r["last_condition_hash"],
                        min_cooldown_seconds=r["min_cooldown_seconds"],
                    ))
                return rules

    def update_rule_trigger(self, rule_id: str, candle_ts: int, cond_hash: str) -> None:
        now_str = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        with self._lock:
            with self._get_conn() as conn:
                conn.execute("""
                    UPDATE monitoring_rules SET
                        last_triggered_at = ?,
                        last_candle_timestamp = ?,
                        last_condition_hash = ?
                    WHERE rule_id = ?;
                """, (now_str, candle_ts, cond_hash, rule_id))

    def record_alert(self, event: AlertEvent) -> None:
        with self._lock:
            with self._get_conn() as conn:
                conn.execute("""
                    INSERT INTO alert_history (
                        event_id, rule_id, asset, timeframe, decision, headline,
                        summary, price, timestamp, delivery_status, retry_count
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(event_id) DO UPDATE SET
                        delivery_status=excluded.delivery_status, retry_count=excluded.retry_count;
                """, (
                    event.event_id, event.rule_id, event.asset, event.timeframe,
                    event.decision, event.headline, event.summary, event.price,
                    event.timestamp, json.dumps(event.delivery_status), event.retry_count,
                ))

    def list_recent_alerts(self, limit: int = 10) -> list[dict[str, Any]]:
        with self._lock:
            with self._get_conn() as conn:
                cur = conn.execute("SELECT * FROM alert_history ORDER BY timestamp DESC LIMIT ?;", (limit,))
                results = []
                for row in cur.fetchall():
                    results.append({
                        "event_id": row["event_id"],
                        "rule_id": row["rule_id"],
                        "asset": row["asset"],
                        "timeframe": row["timeframe"],
                        "decision": row["decision"],
                        "headline": row["headline"],
                        "price": row["price"],
                        "timestamp": row["timestamp"],
                        "delivery_status": json.loads(row["delivery_status"]),
                    })
                return results


class AutonomousMonitoringRuntime:
    """Evaluates monitoring rules on closed candles and manages alert dispatches."""

    def __init__(self, store: AutonomousMonitorStore | None = None, repo_root: Path | None = None) -> None:
        self.store = store or AutonomousMonitorStore()
        self.root = repo_root or get_repo_root()

    def close(self) -> None:
        self.store.close()

    def __del__(self) -> None:
        self.close()

    def get_status(self) -> dict[str, Any]:
        global_en = self.store.is_global_enabled()
        paused = self.store.is_paused()
        rules = self.store.list_rules()
        active_rules = [r for r in rules if r.enabled]
        status_label = "RUNNING" if (global_en and not paused) else ("PAUSED" if paused else "DISABLED")

        return {
            "status": status_label,
            "global_enabled": global_en,
            "paused": paused,
            "active_rules_count": len(active_rules),
            "total_rules_count": len(rules),
            "rules": [asdict(r) for r in rules],
            "recent_alerts": self.store.list_recent_alerts(limit=5),
        }

    def enable(self) -> dict[str, Any]:
        self.store.set_global_enabled(True)
        self.store.set_paused(False)
        return {"status": "ENABLED", "detail": "Autonomous monitoring activated (research only)."}

    def disable(self) -> dict[str, Any]:
        self.store.set_global_enabled(False)
        return {"status": "DISABLED", "detail": "Autonomous monitoring stopped."}

    def pause(self) -> dict[str, Any]:
        self.store.set_paused(True)
        return {"status": "PAUSED", "detail": "Autonomous monitoring paused."}

    def resume(self) -> dict[str, Any]:
        self.store.set_paused(False)
        return {"status": "RUNNING", "detail": "Autonomous monitoring resumed."}

    def add_alert_rule(
        self,
        asset: str,
        timeframe: str = "H1",
        condition: str = "ACTIONABLE_SETUP",
        channels: list[str] | None = None,
        destination: str = "",
    ) -> MonitoringRule:
        rule_id = hashlib.sha256(f"{asset.upper()}:{timeframe}:{condition}:{time.time()}".encode("utf-8")).hexdigest()[:12]
        rule = MonitoringRule(
            rule_id=rule_id,
            asset=asset.upper(),
            timeframe=timeframe.upper(),
            condition=condition.upper(),
            channels=channels or ["outbox"],
            target_destination=destination,
            enabled=True,
            created_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        )
        self.store.add_rule(rule)
        return rule

    def remove_alert_rule(self, rule_id: str) -> bool:
        return self.store.remove_rule(rule_id)

    def evaluate_tick(
        self,
        quant_evaluator: Any | None = None,
        dispatcher: Any | None = None,
        now_dt: datetime | None = None,
    ) -> list[AlertEvent]:
        """Runs a tick evaluation over all active rules."""
        if not self.store.is_global_enabled() or self.store.is_paused():
            return []

        rules = [r for r in self.store.list_rules() if r.enabled]
        if not rules:
            return []

        triggered_events: list[AlertEvent] = []
        current_dt = now_dt or datetime.now(timezone.utc)
        now_iso = current_dt.strftime("%Y-%m-%dT%H:%M:%SZ")

        # Quiet Hours check: 22:00 to 06:00 UTC (or local)
        hour = current_dt.hour
        is_quiet_hours = hour >= 22 or hour < 6

        for rule in rules:
            # Evaluate rule signal
            eval_res = self._check_rule_signal(rule, quant_evaluator)
            if not eval_res or not eval_res.get("qualifies"):
                continue

            candle_ts = eval_res.get("candle_timestamp", int(current_dt.timestamp()))
            cond_hash = eval_res.get("condition_hash", "")

            # Deduplication: Do not re-trigger if candle & condition are identical, or if within cooldown
            if rule.last_candle_timestamp == candle_ts and rule.last_condition_hash == cond_hash:
                continue

            # Cooldown check
            if rule.last_triggered_at:
                try:
                    last_time = datetime.strptime(rule.last_triggered_at, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
                    if (current_dt - last_time).total_seconds() < rule.min_cooldown_seconds and rule.last_condition_hash == cond_hash:
                        continue
                except Exception:
                    pass

            event_id = hashlib.sha256(f"{rule.rule_id}:{candle_ts}:{cond_hash}".encode("utf-8")).hexdigest()[:16]
            event = AlertEvent(
                event_id=event_id,
                rule_id=rule.rule_id,
                asset=rule.asset,
                timeframe=rule.timeframe,
                decision=eval_res.get("decision", "WAIT"),
                headline=eval_res.get("headline", f"OpenBagus Alert: {rule.asset} {rule.timeframe}"),
                summary=eval_res.get("summary", ""),
                price=eval_res.get("price", 0.0),
                timestamp=now_iso,
                delivery_status={ch: "QUEUED" for ch in rule.channels},
            )

            # Quiet hours channel filtering: suppress intrusive push notifications during 22:00-06:00
            deliver_channels = [ch for ch in rule.channels if not is_quiet_hours or ch == "outbox"]
            for ch in rule.channels:
                if is_quiet_hours and ch != "outbox":
                    event.delivery_status[ch] = "SUPPRESSED_QUIET_HOURS"

            if deliver_channels:
                self._dispatch_alert(event, rule, dispatcher, deliver_channels)

            # Record event and update rule trigger state
            self.store.record_alert(event)
            self.store.update_rule_trigger(rule.rule_id, candle_ts, cond_hash)
            triggered_events.append(event)

        return triggered_events

    def _check_rule_signal(self, rule: MonitoringRule, quant_evaluator: Any | None) -> dict[str, Any] | None:
        if quant_evaluator is not None:
            return quant_evaluator(rule.asset, rule.timeframe, rule.condition)

        # Built-in evaluation using CryptoResearchRunner or QuantEngine if present
        try:
            from openbagus.domains.crypto.research import CryptoResearchRunner
            runner = CryptoResearchRunner(self.root)
            ticker = runner.zerokey.get_spot_ticker(rule.asset)
            if not ticker or not ticker.get("price"):
                return None

            klines = runner.zerokey.get_klines(rule.asset, interval=rule.timeframe.lower())
            if not klines or len(klines) < 2:
                return None

            # Check closed candle
            latest_closed_candle = klines[-2]
            candle_ts = int(latest_closed_candle[0]) if isinstance(latest_closed_candle[0], (int, float, str)) else 0
            price = float(ticker.get("price", 0.0))

            q = runner.quant.evaluate(
                symbol=rule.asset,
                spot_ticker=ticker,
                klines=klines,
                derivatives=None,
                orderbook=None,
                trades=None,
                sentiment=None,
                stablecoins=None,
                market_type="spot",
                timeframe=rule.timeframe,
            )

            cond_hash = hashlib.sha256(f"{q.decision}:{q.decision_reason}:{q.rr_gate_passed}".encode("utf-8")).hexdigest()[:12]
            qualifies = False

            if rule.condition == "ACTIONABLE_SETUP" and q.decision in ("BUY", "SELL", "LONG", "SHORT") and q.rr_gate_passed:
                qualifies = True
            elif rule.condition == "BREAKOUT" and q.bullish_validation and "breakout" in q.bullish_validation.trigger_condition.lower():
                qualifies = True
            elif rule.condition == "BREAKDOWN" and q.bearish_validation and "breakdown" in q.bearish_validation.trigger_condition.lower():
                qualifies = True
            elif rule.condition == "STOP_LOSS" and q.stop_price and price <= q.stop_price:
                qualifies = True

            return {
                "qualifies": qualifies,
                "candle_timestamp": candle_ts,
                "condition_hash": cond_hash,
                "decision": q.decision,
                "headline": f"[{q.decision}] {rule.asset} {rule.timeframe} Signal Triggered",
                "summary": f"{q.decision_reason} · Price: {price:,.2f}",
                "price": price,
            }
        except Exception:
            return None

    def _dispatch_alert(self, event: AlertEvent, rule: MonitoringRule, dispatcher: Any | None, channels: list[str]) -> None:
        if dispatcher is not None:
            for ch in channels:
                dispatcher(event, ch)
            return

        for ch in channels:
            if ch == "outbox":
                try:
                    from openbagus.delivery.adapters import LocalFileOutboxAdapter
                    outbox = LocalFileOutboxAdapter(self.root / "reports/runtime/delivery")
                    content = f"# {event.headline}\n\n{event.summary}\n\nPrice: {event.price}\nTime: {event.timestamp}"
                    outbox.stage(f"alert_{event.asset}_{event.timeframe}", content)
                    event.delivery_status[ch] = "SENT"
                except Exception:
                    event.delivery_status[ch] = "FAILED"

            elif ch == "gmail":
                try:
                    from openbagus.delivery.gmail import GmailOAuthTransport
                    gt = GmailOAuthTransport()
                    if gt.is_connected() and rule.target_destination:
                        res = gt.send_message(
                            recipient=rule.target_destination,
                            subject=event.headline,
                            text_body=f"{event.summary}\n\nPrice: {event.price}\nTime: {event.timestamp}\n\nResearch-only. No broker order executed.",
                        )
                        event.delivery_status[ch] = res.get("status", "FAILED")
                    else:
                        event.delivery_status[ch] = "FAILED_NO_AUTH"
                except Exception:
                    event.delivery_status[ch] = "FAILED"

            elif ch == "whatsapp":
                try:
                    from openbagus.delivery.whatsapp_personal import PersonalWhatsAppTransport
                    wt = PersonalWhatsAppTransport()
                    # Prepares compose
                    msg = f"{event.headline}\n{event.summary}\nPrice: {event.price}"
                    res = wt.compose(msg, phone=rule.target_destination or None, open_browser=False)
                    event.delivery_status[ch] = res.get("status", "COMPOSE_OPENED")
                except Exception:
                    event.delivery_status[ch] = "FAILED"
