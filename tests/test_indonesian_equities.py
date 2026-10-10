"""Synthetic fixtures for permitted IDX imports; never a live market-data source."""

import copy
import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from openbagus.data.assets import AssetRegistry
from openbagus.delivery.adapters import render_research_delivery
from openbagus.domains.crypto.catalog import CryptoAsset
from openbagus.domains.crypto.quant import QuantEngine
from openbagus.domains.crypto.research import CryptoResearchRunner, ResearchPacket
from openbagus.domains.equities.catalog import EquityCatalog, SECTORS
from openbagus.domains.equities.data import EquityData, fundamentals
from openbagus.domains.equities.policy import EquityMarketPolicy
from openbagus.intelligence.intent import IntentRouter, SessionState
from openbagus.intelligence.local_language import LocalLanguageEngine, NarrativeFacts

NOW = datetime(2026, 1, 5, 3, tzinfo=timezone.utc)


def market_fixture(symbol="BBCA"):
    candles = []
    for i in range(25):
        start = NOW - timedelta(days=26-i)
        close = 904 + i * 4
        candles.append({"open_at": start.isoformat(), "close_at": (start + timedelta(hours=6)).isoformat(),
            "open": close-2, "high": close+10, "low": close-10, "close": close, "volume": 1000})
    candles[-1].update(high=1010, low=990, close=1000, volume=1500)
    candles[-4]["high"] = 1300
    return {"symbol": symbol, "authorized_use": True, "source": "https://www.bca.co.id/",
        "retrieved_at": NOW.isoformat(), "currency": "IDR", "volume_unit": "shares", "timeframe": "D1",
        "adjustment": "adjusted", "unresolved_corporate_actions": False, "listing_status": "ACTIVE", "board": "MAIN",
        "quote": {"price": 1000, "previous_close": 1000, "as_of": NOW.isoformat(), "delayed": False,
                  "price_limit_low": 800, "price_limit_high": 1350},
        "fees": {"buy": .0015, "sell": .0025}, "candles": candles}


def statement_fixture():
    return {"source": "https://www.bca.co.id/", "published_at": "2025-03-01T09:00:00+07:00",
        "currency": "IDR", "unit": "million_IDR", "period_type": "FY", "period": "2024", "basis": "consolidated",
        "values": {"revenue": 1000, "net_income": 100, "net_income_attributable": 100,
            "equity": 500, "equity_attributable": 500, "average_equity_attributable": 400,
            "average_assets": 1000, "weighted_average_shares": 1_000_000, "shares_outstanding": 1_000_000},
        "reported_ratios_pct": {"NIM": 5.2, "NPL_gross": 1.5, "CAR": 25}}


class TestIndonesianEquities(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.no_llm = patch.object(LocalLanguageEngine, "is_available", return_value=False)
        self.no_llm.start()
        self.addCleanup(self.no_llm.stop)
        self.router = IntentRouter(repo_root=self.root)
        self.runner = CryptoResearchRunner(self.root)
        self.quant = QuantEngine()
        self.policy = EquityMarketPolicy(self.root)
        self.policy.rules = json.loads((Path(__file__).parents[1] / "config/idx_market_rules.json").read_text())
        self.policy.rules.update(effective_from="2026-01-01", effective_until="2026-01-31",
            calendar={"2026-01-05": True, "2026-01-06": False, "2026-01-09": True})

    def test_identity_taxonomy_and_routing(self):
        for symbol in ("BBCA", "BBRI", "BMRI", "TLKM", "ASII", "ANTM", "IHSG", "LQ45", "IDX30"):
            req = self.router.parse(f"{symbol} hari ini gimana?")
            self.assertEqual(req.domain, "EQUITIES_INDONESIA")
            self.assertEqual(req.asset, symbol)
            self.assertEqual(req.timeframe, "D1")
        for symbol in ("BTC", "ETH"):
            self.assertEqual(self.router.parse(symbol).domain, "CRYPTO_RESEARCH")
        self.assertEqual(len(SECTORS), 11)
        self.assertEqual(self.runner.assets.equities.resolve("BBCA").sector_code, "G")
        self.assertEqual(self.runner.assets.equities.resolve("ANTM").sector_code, "B")
        self.assertEqual(self.runner.assets.equities.resolve("TLKM").sector_code, "J")
        for query in ("Banking Indonesia", "IDX sektor energi"):
            self.assertEqual(self.router.parse(query).request_type, "EQUITY_SECTOR")
        req = self.router.parse("saham AAPL")
        self.assertTrue(req.needs_asset)
        self.assertFalse(req.asset)
        self.assertEqual(self.router.parse("Bank Central Asia daily").asset, "BBCA")
        session = SessionState(last_asset="BBCA", market_type="IDX CASH EQUITY", timeframe="D1")
        self.assertEqual(self.router.parse("1 dolar berapa rupiah?", session).request_type, "FIAT_FX")
        self.assertEqual(self.router.parse("kenapa belum long BTC?", session).asset, "BTC")
        req = self.router.parse("BBCA modal Rp1000000 risiko 2%")
        self.assertEqual((req.equity, req.risk_pct), (1000000, 2))
        self.assertTrue(self.router.parse("AAPL").needs_asset)

    def test_catalog_expansion_lifecycle_and_ambiguity(self):
        path = self.root / "import.json"
        rows = [{"symbol": "NEWX", "name": "Synthetic issuer", "sector_code": "G", "industry": "Banks",
                 "source": "https://www.idx.co.id/", "effective_date": "2026-01-01", "listing_status": "SUSPENDED",
                 "hierarchy": ["G", "G1", "G11", "G111"]}]
        path.write_text(json.dumps(rows))
        self.assertEqual(EquityCatalog(self.root).import_file(path), 1)
        a = EquityCatalog(self.root).resolve("NEWX")
        self.assertEqual(a.hierarchy[-1], "G111")
        self.assertEqual(a.listing_status, "SUSPENDED")
        registry = AssetRegistry(self.root)
        registry.crypto.assets.append(CryptoAsset("fixture-bbca", "BBCA", "Synthetic token"))
        self.assertEqual(len(registry.resolve_asset("BBCA")[1]), 2)
        self.assertEqual(registry.resolve_asset("IDX:BBCA")[0].asset_type, "EQUITY_ID")

    def test_import_integrity_and_no_network(self):
        data = market_fixture()
        p = self.root / "market.json"
        p.write_text(json.dumps(data))
        with patch("urllib.request.urlopen", side_effect=AssertionError("Unauthorized network")):
            self.assertEqual(EquityData(self.root).import_file(p), "BBCA")
            self.assertEqual(EquityData(self.root).load("BBCA")["currency"], "IDR")
        for key, value in (("currency", "USD"), ("volume_unit", "contracts"), ("authorized_use", False), ("adjustment", "unknown")):
            bad = copy.deepcopy(data)
            bad[key] = value
            with self.assertRaises(ValueError):
                EquityData.validate(bad)
        bad = copy.deepcopy(data)
        bad["candles"][0]["high"] = float("nan")
        with self.assertRaises(ValueError):
            EquityData.validate(bad)
        self.assertIn("SOURCE GAP", EquityData(self.root).load("BBRI")["gaps"][0])

    def test_session_boundaries_calendar_and_tick(self):
        for clock, result in (("01:59:59", "CLOSED_SESSION"), ("02:00:00", "OPEN"), ("05:00:01", "CLOSED_SESSION"),
                              ("06:29:59", "CLOSED_SESSION"), ("06:30:00", "OPEN"), ("08:49:59", "OPEN"), ("08:50:00", "CLOSED_SESSION")):
            self.assertEqual(self.policy.session_status(datetime.fromisoformat(f"2026-01-05T{clock}+00:00")), result)
        self.assertEqual(self.policy.session_status(NOW + timedelta(days=1)), "CLOSED_HOLIDAY")
        self.assertEqual(self.policy.session_status(NOW + timedelta(days=2)), "CALENDAR_UNVERIFIED")
        self.assertEqual(self.policy.session_status(NOW + timedelta(days=5)), "CLOSED_WEEKEND")
        self.assertEqual(self.policy.session_status(datetime.fromisoformat("2026-01-09T06:30:00+00:00")), "CLOSED_SESSION")
        self.assertEqual(self.policy.session_status(datetime.fromisoformat("2026-01-09T07:00:00+00:00")), "OPEN")
        self.assertEqual(self.policy.session_status(NOW, "negotiated"), "OPEN")
        for price, tick in ((199, 1), (200, 2), (500, 5), (2000, 10), (5000, 25)):
            self.assertEqual(self.policy.tick(price), tick)
        self.assertEqual(self.policy.position_size(1000, 900, 100_000, 2, .0015, .0025), 0)
        self.assertEqual(self.policy.position_size(1000, 900, 10_000_000, 2, .0015, .0025) % 100, 0)

    def test_equity_decision_geometry_and_stale_guards(self):
        data = market_fixture()
        q = self.quant.evaluate_equity("BBCA", data, self.policy, now=NOW)
        self.assertEqual(q.decision, "BUY", q.decision_reason)
        self.assertLess(q.stop_price, q.price)
        self.assertGreater(q.tp1, q.price)
        self.assertGreaterEqual(q.reward_risk, 1.5)
        self.assertEqual(q.leverage_num, 0)
        for transform in (lambda d: d["quote"].update(delayed=True), lambda d: d.update(timeframe="H1"),
                          lambda d: d.update(listing_status="SUSPENDED"), lambda d: d.update(candles=d["candles"][:5]),
                          lambda d: d.update(adjustment="unadjusted", unresolved_corporate_actions=True),
                          lambda d: d["quote"].update(as_of=(NOW-timedelta(days=2)).isoformat()),
                          lambda d: d["quote"].pop("price_limit_low")):
            bad = copy.deepcopy(data)
            transform(bad)
            q = self.quant.evaluate_equity("BBCA", bad, self.policy, now=NOW)
            self.assertEqual(q.decision, "WAIT", q.decision_reason)
            self.assertIsNone(q.stop_price)
        data["candles"][-4]["high"] = 1060
        q = self.quant.evaluate_equity("BBCA", data, self.policy, now=NOW)
        self.assertEqual(q.decision, "WAIT")
        self.assertFalse(q.rr_gate_passed)

    def test_position_context_downtrend_and_index(self):
        data = market_fixture()
        for i, bar in enumerate(data["candles"]):
            c = 1250 - i*10
            bar.update(open=c+5, close=c, high=c+20, low=c-5)
        self.assertEqual(self.quant.evaluate_equity("BBCA", data, self.policy, now=NOW).decision, "AVOID_ENTRY")
        self.assertEqual(self.quant.evaluate_equity("BBCA", data, self.policy, now=NOW, has_position_context=True).decision, "REDUCE")
        self.assertEqual(self.quant.evaluate_equity("IHSG", data, self.policy, now=NOW, is_index=True).decision, "WAIT")
        for bar in data["candles"]:
            bar.update(open=1000, high=1010, low=990, close=1000, volume=1000)
        self.assertEqual(self.quant.evaluate_equity("BBCA", data, self.policy, now=NOW, has_position_context=True).decision, "HOLD")

    def test_fundamentals_units_period_growth_and_bank_ratios(self):
        statement = statement_fixture()
        result = fundamentals(statement, 1000)
        r = result["ratios"]
        self.assertEqual(r["EPS"], 100)
        self.assertEqual(r["PER"], 10)
        self.assertEqual(r["PBV"], 2)
        self.assertEqual(r["ROE_pct"], 25)
        self.assertEqual(r["NIM_pct"], 5.2)
        previous = copy.deepcopy(statement)
        previous["period"] = "2023"
        previous["values"]["revenue"] = 500
        statement["comparison"] = {"previous_period": "2023", "kind": "YoY"}
        self.assertEqual(fundamentals(statement, 1000, previous)["ratios"]["revenue_growth_YoY_pct"], 100)
        statement["values"]["net_income_attributable"] = -100
        self.assertNotIn("PER", fundamentals(statement, 1000)["ratios"])
        statement["period_type"] = "QUARTER"
        self.assertNotIn("PER", fundamentals(statement, 1000)["ratios"])
        self.assertTrue(fundamentals(None, None)["gaps"])

    def test_crypto_idx_session_comparison_chart_and_return(self):
        session = SessionState(last_asset="BTC", timeframe="H1", market_type="SPOT")
        old = self.quant.evaluate("BTC", {"price": 100, "high": 110, "low": 90})
        packet = ResearchPacket("BTC", "GENERAL / SPOT REFERENCE", "H1", 100, old.decision, old.data_quality, old.setup_quality)
        session.last_quant_result, session.last_research_packet = old, packet
        req = self.router.parse("BBCA", session)
        self.assertTrue(req.needs_topic_switch_confirmation)
        self.runner.execute(req, session)
        self.assertEqual(session.last_asset, "BBCA")
        with patch.object(self.runner.quant, "evaluate_equity", side_effect=AssertionError("Unnecessary refetch")):
            text = self.runner.execute(self.router.parse("kenapa belum buy?", session), session)
            self.assertIn("SOURCE GAP", text)
            comparison = self.router.parse("bandingkan dengan BBRI", session)
            self.assertFalse(comparison.needs_topic_switch_confirmation)
            self.assertEqual(comparison.target_assets, ["BBCA", "BBRI"])
            text = self.runner.execute(self.router.parse("kalau BI rate turun?", session), session)
            self.assertIn("NIM", text)
            self.assertEqual(session.timeframe, "D1")
        result = self.runner.execute(comparison, session)
        self.assertIn("BBRI", result)
        self.assertEqual(session.last_asset, "BBCA")
        with patch("webbrowser.open", return_value=True) as browser:
            self.runner.execute(self.router.parse("chart BBCA", session), session)
            self.assertIn("IDX:BBCA", browser.call_args.args[0])
        req = self.router.parse("balik ke BTC", session)
        with patch.object(self.runner.zerokey, "get_spot_ticker", side_effect=AssertionError("Unexpected fetch")):
            self.runner.execute(req, session)
        self.assertEqual((session.last_asset, session.timeframe), ("BTC", "H1"))

    def test_shell_confirmation_and_nonresearch_bypass(self):
        from openbagus.cli import OpenBagusShell
        shell = OpenBagusShell()
        shell.router, shell.researcher = self.router, self.runner
        shell.session = SessionState(last_asset="BTC", timeframe="H1")
        with redirect_stdout(io.StringIO()), patch("builtins.input", return_value="n"):
            shell.default("BBCA")
        self.assertEqual(shell.session.last_asset, "BTC")
        with redirect_stdout(io.StringIO()), patch("builtins.input", return_value="y"):
            shell.default("BBCA")
        self.assertEqual(shell.session.last_asset, "BBCA")
        for query in ("1+1", "1 USD berapa IDR", "categories"):
            self.assertFalse(shell.router.parse(query, shell.session).needs_topic_switch_confirmation)
        self.assertEqual(shell.session.last_asset, "BBCA")

    def test_quote_cross_asset_grounding_and_delivery(self):
        self.assertEqual(self.router.parse("harga BBCA berapa?").request_type, "EQUITY_QUOTE")
        req = self.router.parse("BTC vs BBCA", SessionState(last_asset="BTC"))
        self.assertEqual(req.request_type, "COMPARE")
        self.assertFalse(req.needs_topic_switch_confirmation)
        facts = NarrativeFacts("BBCA", 1000, "WAIT", currency="IDR", asset_type="EQUITY_ID")
        self.assertFalse(LocalLanguageEngine._narrative_is_grounded(facts, "Harga $1000"))
        self.assertFalse(LocalLanguageEngine._narrative_is_grounded(facts, "Open long BBCA"))
        session = SessionState()
        self.runner.execute(self.router.parse("BBCA"), session)
        message = render_research_delivery(session.last_quant_result, session.last_research_packet)
        self.assertNotIn("$", message["text"])
        self.assertIn("Freshness", message["text"])

    def test_publication_periods_and_commodity_context(self):
        data = market_fixture("ANTM")
        data["events"] = [{"source": "https://www.bi.go.id/", "summary": "Fixture policy publication",
            "published_at": "2025-12-20T10:00:00+07:00", "observation_period": "2025-12",
            "assets": ["ANTM"], "event_at": "2025-12-19T09:00:00+07:00"}]
        EquityData.validate(data)
        text = self.runner.execute(self.router.parse("ANTM pengaruh nikel bagaimana?"), SessionState())
        self.assertIn("biaya", text)
        self.assertIn("belum ada dasar", text)

    def test_imported_macro_event_dedup_dates_and_relative_strength(self):
        data = market_fixture()
        data["events"] = [{"source": "https://www.bi.go.id/", "summary": "Synthetic BI policy event",
            "observation_period": "2026-01", "published_at": "2026-01-01T10:00:00+07:00", "sectors": ["G"]},
            {"source": "https://www.bps.go.id/", "summary": "Synthetic inflation release",
            "observation_period": "2025-12", "published_at": "2026-01-01T09:00:00+07:00", "assets": ["BBCA"]},
            {"source": "https://www.bi.go.id/", "summary": "Synthetic JISDOR reference, not a live price",
            "observation_period": "2026-01-02", "published_at": "2026-01-02T15:30:00+07:00", "assets": ["BBCA"]}]
        data["events"].append(copy.deepcopy(data["events"][0]))
        p = self.root / "market.json"
        p.write_text(json.dumps(data))
        EquityData(self.root).import_file(p)
        self.assertEqual(EquityData(self.root).load("BBCA")["events"][0]["observation_period"], "2026-01")
        with patch("openbagus.domains.equities.research.datetime") as clock:
            clock.now.return_value = NOW
            session = SessionState()
            text = self.runner.execute(self.router.parse("BBCA daily"), session)
        self.assertEqual(len(session.last_research_packet.events), 3)
        self.assertIn("Synthetic JISDOR", text)
        self.assertNotIn("priced in", text)
        data["benchmark_candles"] = [{"close_at": b["close_at"], "close": 1000} for b in data["candles"]]
        q = self.quant.evaluate_equity("BBCA", data, self.policy, now=NOW)
        self.assertIn("relative_strength_vs_IHSG_pct", q.microstructure)
        data["benchmark_candles"][-1]["close_at"] = (NOW + timedelta(days=1)).isoformat()
        q = self.quant.evaluate_equity("BBCA", data, self.policy, now=NOW)
        self.assertNotIn("relative_strength_vs_IHSG_pct", q.microstructure)


if __name__ == "__main__":
    unittest.main()
