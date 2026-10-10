"""Permanent Acceptance Tests for OpenBagus Product Intelligence and Interaction.

Covers Section I requirements (I1 through I9):
I1: Harness interactive session context switching (BTC -> ETH confirmation, N keeps BTC, Y switches, Compare bypasses)
I2: System context continuity (BTC -> system info -> follow-up preserved on BTC)
I3: Chart action (TradingView / GeckoTerminal browser action only, no full quant analysis text, no ASCII chart)
I4: BLS CPI-U freshness verification (August 2026 reference month, next release Oct 14, 2026, not stale)
I5: Federal Reserve FOMC schedule verification (Oct 7, 2026 minutes, Oct 27-28, 2026 meeting)
I6: Conditional factor engine materiality (Stochastic, Pattern, Fibonacci only surfaced when material)
I7: Cross-venue arbitrage materiality (Tiny spread suppressed, large net spread surfaced)
I8: Lunar/astrology factor isolation (Zero weight, suppressed by default, isolated to explicit diagnostic)
I9: Narrative consistency and anti-template compliance
"""

from __future__ import annotations

import unittest
import math
import time
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

from openbagus.cli import OpenBagusShell
from openbagus.data.zerokey import ZeroKeyMarketData
from openbagus.domains.crypto.quant import (
    EvidenceBlockResult,
    QuantDecisionResult,
    QuantEngine,
    ValidationScenario,
)
from openbagus.domains.crypto.research import CryptoResearchRunner, ResearchPacket
from openbagus.intelligence.intent import IntentRequest, IntentRouter, SessionState, _safe_calc
from openbagus.intelligence.local_language import LocalLanguageEngine, NarrativeFacts, format_price
from openbagus.domains.crypto.catalog import CryptoAsset


class TestProductInteraction(unittest.TestCase):
    def setUp(self) -> None:
        self.router = IntentRouter()
        self.quant = QuantEngine()
        self.zerokey = ZeroKeyMarketData()

    def test_continuous_explanatory_session_without_refetch(self):
        runner = CryptoResearchRunner()
        stamp = datetime.now(timezone.utc).isoformat()
        ticker = {"price": 100, "high": 120, "low": 80, "observed_at": stamp, "provider": "Fixture"}
        evidence = {"klines": [{"high": 101, "low": 99, "close": 100}], "derivatives": None, "orderbook": None, "trades": None, "sentiment": {"value": 50}, "stablecoins": {"total": 1}}
        session = SessionState()
        with patch.object(self.router.local_llm, "is_available", return_value=False), patch.object(runner.local_llm, "is_available", return_value=False), patch.object(runner.zerokey, "get_all_evidence", return_value=evidence) as fetch, patch.object(runner.zerokey, "get_spot_ticker", return_value=ticker), patch.object(runner.zerokey, "get_cpi", return_value=None), patch.object(runner.zerokey, "get_fomc", return_value=None), patch.object(runner.zerokey, "get_large_flow_activity", return_value=None):
            first = runner.execute(self.router.parse("BTC H1 sekarang gimana?", session), session)
            self.assertIn("BTC", first)
            count = fetch.call_count
            packet = session.last_research_packet
            original = (packet.price, packet.decision, packet.stop_price, packet.tp1)
            for query in ("Kenapa belum long?", "Kalau OI naik tapi funding negatif?", "Kalau resistance tadi ditembus?", "Jelaskan lebih sederhana.", "Gunakan bahasa Indonesia.", "Bagaimana FOMC memengaruhi skenario tadi?"):
                request = self.router.parse(query, session)
                self.assertIn(request.request_type, {"FOLLOW_UP", "PREFERENCE"}, query)
                self.assertFalse(request.needs_topic_switch_confirmation)
                answer = runner.execute(request, session)
                self.assertIn("BTC", answer)
                self.assertIn("H1", answer)
                self.assertNotIn("Decision Factors", answer)
                self.assertLess(len(answer), 2400)
                self.assertIs(session.last_research_packet, packet)
            self.assertEqual(fetch.call_count, count)
            self.assertEqual(original, (packet.price, packet.decision, packet.stop_price, packet.tp1))
            compare = self.router.parse("Bisa dibandingkan ETH?", session)
            self.assertEqual(compare.request_type, "COMPARE")
            self.assertEqual(compare.target_assets, ["BTC", "ETH"])
            self.assertIn(format_price(session.last_quant_result.structure_levels["resistance"]), runner._render_explanation(session, "Kalau resistance tadi ditembus?"))
            self.assertIn("deleveraging", runner._render_explanation(session, "Kalau funding naik tetapi OI turun?"))
            self.assertNotIn("Funding negatif berarti", runner._render_explanation(session, "Kalau funding naik tetapi OI turun?"))

    def test_ema_atr_and_data_integrity(self):
        values = [100.0] * 21 + [110.0]
        self.assertAlmostEqual(self.quant._ema(values, 8), 100 + 20 / 9)
        candles = [{"time": i, "high": 101, "low": 99, "close": 100} for i in range(15)]
        candles.append({"time": 15, "high": 110, "low": 99, "close": 109})
        atr = self.quant._eval_volatility_regime(109, 110, 99, candles)
        self.assertAlmostEqual(atr.details["atr"], (2 * 13 + 11) / 14)
        future = {"time": 16, "close_time": (time.time() + 1000) * 1000, "high": 999, "low": 99, "close": 990}
        clean, valid = self.quant._closed_candles(candles[::-1] + [future])
        self.assertTrue(valid)
        self.assertEqual(clean[-1]["close"], 109)
        bad = {"high": float("nan"), "low": 1, "close": 3}
        self.assertFalse(self.quant._closed_candles([bad])[1])
        for stamp in (None, "2000-01-01T00:00:00Z", "2999-01-01T00:00:00Z"):
            q = self.quant.evaluate("BTC", {"price": 100, "high": 130, "low": 90, "pct_change": 5, "observed_at": stamp}, klines=candles, market_type="perpetual")
            self.assertEqual(q.decision, "NO_TRADE")
            self.assertFalse(q.quality_gate_passed)
        q = self.quant.evaluate("BTC", {"price": 100, "high": 130, "low": 90, "observed_at": datetime.now(timezone.utc).isoformat()}, klines=candles)
        self.assertEqual(q.evidence_count, 1)
        self.assertFalse(q.quality_gate_passed)
        self.assertEqual(self.quant._eval_context_sentiment(None, None).quality, 0)

    def test_derivative_provider_units(self):
        row = {"symbol": "BTCUSDT", "price": 102, "index": 100, "funding_rate": -0.02, "open_interest": 1000000, "market": "Fixture"}
        with patch.object(self.zerokey, "_get_json", side_effect=[None, [row]]):
            data = self.zerokey.get_derivatives("BTC")
        self.assertAlmostEqual(data["funding_rate"], -0.0002)
        self.assertEqual(data["basis_bps"], 200)
        self.assertEqual(data["open_interest_unit"], "USD")
        ev = self.quant._eval_derivatives_basis(102, 0, data)
        self.assertIsNone(ev.details["open_interest_change_pct"])

    def test_language_followup_rerenders_without_fetch(self):
        runner = CryptoResearchRunner()
        q = self.quant.evaluate("IMX", {"price": 1.23, "high": 1.3, "low": 1.1})
        packet = ResearchPacket(asset="IMX", market="GENERAL / SPOT REFERENCE", timeframe="H1", price=q.price, decision=q.decision, data_quality=q.data_quality, setup_quality=q.setup_quality)
        session = SessionState(last_asset="IMX", last_quant_result=q, last_research_packet=packet)
        original = (q.price, q.decision, q.stop_price, q.tp1)
        with patch.object(runner.local_llm, "is_available", return_value=False), patch.object(runner.zerokey, "get_spot_ticker") as fetch, patch.object(runner.quant, "evaluate") as quant:
            req = self.router.parse("jelasin dalam bahasa indonesia", session)
            self.assertEqual(req.request_type, "PREFERENCE")
            result = runner.execute(req, session)
            self.assertIn("Pada timeframe", result)
            self.assertEqual(session.language, "ID")
            self.assertIn("IMX", result)
            self.assertIn("$1.23", result)
            result = runner.execute(self.router.parse("english please", session), session)
            self.assertIn("On the H1 timeframe", result)
            self.assertEqual(session.language, "EN")
            fetch.assert_not_called()
            quant.assert_not_called()
            self.assertEqual(original, (q.price, q.decision, q.stop_price, q.tp1))
            self.assertIs(session.last_research_packet, packet)

    def test_single_token_discovery_and_ambiguity(self):
        manta = CryptoAsset(id="manta-network", symbol="MANTA", name="Manta Network")
        catalog = self.router.catalog
        catalog.assets = [a for a in catalog.assets if a.symbol != "MANTA"]
        with patch.object(catalog, "discover_online", return_value=[manta]) as discovery:
            req = self.router.parse("manta")
            self.assertEqual(req.asset, "MANTA")
            discovery.assert_called_once_with("manta")
        with patch.object(catalog, "discover_online") as discovery, patch.object(self.router.local_llm, "is_available", return_value=False):
            self.assertEqual(self.router.parse("aku lagi capek nih").request_type, "UNKNOWN")
            discovery.assert_not_called()
        candidates = [CryptoAsset(id=f"xyz-{i}", symbol="XYZ", name=f"XYZ {i}", rank=i) for i in range(7)]
        with patch.object(catalog, "discover_online", return_value=candidates):
            req = self.router.parse("XYZ")
            self.assertTrue(req.is_ambiguous)
            self.assertLessEqual(len(req.candidates), 5)
            self.assertIsNone(req.asset)
            self.assertEqual(req.candidates, [f"xyz-{i}" for i in range(5)])
        catalog.assets.extend(candidates)
        runner = CryptoResearchRunner()
        runner.catalog = catalog
        self.assertIn("XYZ 0", runner.execute(req))
        selected = self.router.parse("xyz-0")
        self.assertEqual(selected.asset, "XYZ")
        self.assertEqual(selected.asset_id, "xyz-0")

    def test_position_context_is_explicit_and_not_persisted(self):
        with patch.object(self.router.local_llm, "is_available", return_value=False):
            self.assertFalse(self.router.parse("ETH").has_position_context)
            for query in ("aku pegang ETH", "posisi ETH saya", "saya sudah beli BTC", "should I reduce my SOL?", "jual sebagian ETH?", "kurangi posisi BTC", "I already hold ETH, should I reduce?"):
                self.assertTrue(self.router.parse(query).has_position_context, query)

    def test_unconfirmed_trigger_claims_are_rejected(self):
        engine = LocalLanguageEngine()
        facts = NarrativeFacts(asset="BTC", price=85262, decision="WAIT", bullish_trigger_level=86516,
            bullish_trigger_state="NOT_CONFIRMED", bearish_trigger_level=84489,
            bearish_trigger_state="NOT_CONFIRMED", bullish_trigger="H1 close above $86,516",
            bearish_trigger="H1 close below $84,489")
        with patch.object(engine, "is_available", return_value=True):
            for text in ("BTC crossed above 86516 and broke below 84489.", "BTC closed above 86516.", "BTC breakout confirmed.", "Harga sudah menembus 86516.", "Harga sudah close di atas 86516.", "BTC broke below 84489.", "BTC breakdown has occurred."):
                with patch.object(engine, "_run_llama", return_value=text):
                    self.assertIsNone(engine.generate_narrative(facts), text)
            with patch.object(engine, "_run_llama", return_value="BTC WAIT; long baru valid jika H1 close di atas $86,516."):
                self.assertIsNotNone(engine.generate_narrative(facts))

    def test_material_factors_are_prose_not_orphan_lines(self):
        runner = CryptoResearchRunner()
        q = self.quant.evaluate("ETH", {"price": 100, "high": 110, "low": 90})
        packet = ResearchPacket(asset="ETH", market="SPOT", timeframe="H1", price=100, decision=q.decision, data_quality=q.data_quality, setup_quality=q.setup_quality,
            fibonacci={"material": True, "values": {"summary": "Fib aligns with independently valid support"}}, fibonacci_confluence="Fib aligns with independently valid support")
        with patch.object(runner.local_llm, "is_available", return_value=False):
            normal = runner._render_section_25_view(q, packet=packet, raw_query="ETH")
            self.assertNotIn("\nFibonacci:", normal)
            self.assertIn("Setup confluence:", normal)
            diagnostics = runner._render_section_25_view(q, packet=packet, raw_query="show fib ETH")
            self.assertIn("\nFibonacci:", diagnostics)

    def test_session_status_after_research(self):
        import io
        from contextlib import redirect_stdout
        shell = OpenBagusShell()
        q = self.quant.evaluate("BTC", {"price": 100, "high": 110, "low": 90})
        shell.session.last_quant_result = q
        shell.session.last_research_at = "2026-10-06T00:00:00Z"
        output = io.StringIO()
        with redirect_stdout(output):
            shell.do_status("")
        self.assertIn("Last Research", output.getvalue())
        self.assertIn("BTC / H1", output.getvalue())
        self.assertNotIn("no runs yet", output.getvalue())
        self.assertNotIn("Chart", shell.session.status_display())

    def test_domain_gate_regressions(self) -> None:
        cases = {
            "harga rupiah saat ini dibandingkan dolar?": ("FIAT_FX", None),
            "1 dolar berapa rupiah?": ("FIAT_FX", None),
            "1 USD berapa IDR": ("FIAT_FX", None),
            "1+1 =?": ("CALCULATOR", None),
            "1 btc berapa dolar": ("CRYPTO_QUOTE", "BTC"),
            "harga ETH berapa?": ("CRYPTO_QUOTE", "ETH"),
            "berapa SOL sekarang?": ("CRYPTO_QUOTE", "SOL"),
            "beli gunakan card saya": ("EXECUTION_REQUEST", None),
            "buy BTC with my card": ("EXECUTION_REQUEST", None),
            "purchase BTC": ("EXECUTION_REQUEST", None),
            "execute order": ("EXECUTION_REQUEST", None),
            "categoories": ("SYSTEM_INFO", None),
            "catgories": ("SYSTEM_INFO", None),
            "wai tolong berikan Assets": ("SYSTEM_INFO", None),
            "tolong berikan assets": ("SYSTEM_INFO", None),
            "lihat categories": ("SYSTEM_INFO", None),
            "categories": ("SYSTEM_INFO", None),
            "other": ("CATEGORY", None),
            "Other / Unknown": ("CATEGORY", None),
            "AI": ("CATEGORY", None),
            "RWA": ("CATEGORY", None),
            "Privacy": ("CATEGORY", None),
            "DeFi": ("CATEGORY", None),
            "chat ondo": ("CHART", "ONDO"),
            "char BTC": ("CHART", "BTC"),
            "chart ETH": ("CHART", "ETH"),
            "hello world": ("UNKNOWN", None),
            "help": ("COMMAND", None),
        }
        session = SessionState(last_asset="BTC")
        with patch.object(self.router.local_llm, "is_available", return_value=False), patch.object(self.router.catalog, "discover_online") as discovery:
            for query, (request_type, asset) in cases.items():
                with self.subTest(query=query):
                    req = self.router.parse(query, session)
                    self.assertEqual(req.request_type, request_type)
                    self.assertEqual(req.asset, asset)
                    self.assertFalse(req.needs_topic_switch_confirmation)
                    self.assertEqual(session.last_asset, "BTC")
            discovery.assert_not_called()
            self.assertEqual(self.router.parse("other", session).category, "Other / Unknown")
            self.assertEqual(self.router.parse("wai tolong berikan Assets", session).system_query, "list_assets")
            self.assertEqual(self.router.parse("categoories", session).system_query, "list_categories")
            self.assertEqual(self.router.parse("1+1 =?", session).focus, "2")
            self.assertEqual(self.router.parse("1 dolar berapa rupiah?", session).focus, "USD/IDR")
            for word in ("card", "harga", "dolar", "chat", "bitco"):
                self.assertIsNone(self.router.catalog.resolve_asset(word)[0])

    def test_non_research_bypasses_harness_and_quant(self) -> None:
        shell = OpenBagusShell()
        shell.session.last_asset = "BTC"
        with patch.object(shell.router.local_llm, "is_available", return_value=False), patch.object(shell.researcher, "execute", return_value="OK"), patch("builtins.input") as confirmation:
            for query in ("1+1", "1 USD berapa IDR", "categories", "chart ETH", "other"):
                shell.default(query)
            confirmation.assert_not_called()
            self.assertEqual(shell.session.last_asset, "BTC")
        runner = CryptoResearchRunner()
        session = SessionState(last_asset="BTC")
        with patch.object(runner.quant, "evaluate") as quant, patch.object(runner.zerokey, "get_spot_ticker", return_value={"price": 86434.22, "observed_at": "2026-10-05T10:00:00Z", "provider": "mock"}):
            result = runner.execute(IntentRequest(intent="CRYPTO_QUOTE", request_type="CRYPTO_QUOTE", asset="BTC"), session)
            self.assertIn("$86,434.22", result)
            for forbidden in ("LONG", "SHORT", "NO_TRADE", "Fibonacci", "Reward:Risk"):
                self.assertNotIn(forbidden, result)
            self.assertEqual(runner.execute(self.router.parse("1+1 =?"), session), "2")
            quant.assert_not_called()
            self.assertEqual(session.last_asset, "BTC")

    def test_calculator_limits(self) -> None:
        for expression, expected in (("1+1", "2"), ("1000 * 0.02", "20"), ("(1500 / 3) + 25", "525")):
            self.assertEqual(_safe_calc(expression), expected)
        for expression in ("__import__('os')", "1 / 0", "2**1000000", "1+" * 200 + "1", "text 1+1", "9**9**9"):
            self.assertIsNone(_safe_calc(expression))

    def test_fx_public_pair_mock(self) -> None:
        data = {"base": "USD", "quote": "IDR", "rate": 16000, "date": "2026-10-02"}
        with patch.object(self.zerokey, "_get_json", return_value=data) as http:
            result = self.zerokey.get_fx_rate("USD", "IDR", 2)
            self.assertEqual(result["converted"], 32000)
            self.assertEqual(result["rate"], 16000)
            self.assertEqual(result["date"], "2026-10-02")
            self.assertIn("https://api.frankfurter.dev/v2/rate/USD/IDR", str(http.call_args))
        with patch.object(self.zerokey, "_get_json", return_value={"base": "EUR", "quote": "IDR", "rate": 1, "date": "invalid"}):
            self.assertEqual(self.zerokey.get_fx_rate("USD", "IDR")["error"], "FX_FETCH_FAILED")

    def test_general_market_and_timeframe(self) -> None:
        with patch.object(self.router.local_llm, "is_available", return_value=False):
            for query, tf in (("BTC hari ini gimana?", "H1"), ("BTC today", "H1"), ("BTC intraday", "H1"), ("BTC short term", "H1"), ("BTC H4", "H4"), ("BTC daily", "D1"), ("BTC swing", "H4")):
                req = self.router.parse(query)
                self.assertNotEqual(req.market, "perpetual", query)
                self.assertEqual(req.timeframe, tf)
            for query in ("long BTC", "BTC perpetual", "open position ETH"):
                self.assertEqual(self.router.parse(query).market, "perpetual", query)
        with patch.object(self.router.local_llm, "is_available", return_value=True), patch.object(self.router.local_llm, "interpret_intent", return_value={"request_type": "ANALYZE", "asset": "BTC", "market": "PERPETUAL"}):
            self.assertEqual(self.router.parse("BTC short term").market, "all")
            self.assertEqual(self.router.parse("BTC hari ini gimana?").market, "all")

    def test_semantic_grounding_and_sampling(self) -> None:
        engine = LocalLanguageEngine()
        facts = NarrativeFacts(asset="BTC", price=86434.22, decision="WAIT", fibonacci_level=85778.55)
        with patch.object(engine, "is_available", return_value=True):
            for phrase in ("below Fibonacci", "di bawah Fibonacci", "under Fibonacci", "pada akhir bulan", "bulan depan", "minggu depan"):
                with patch.object(engine, "_run_llama", return_value=f"BTC WAIT {phrase}."):
                    self.assertIsNone(engine.generate_narrative(facts), phrase)
            with patch.object(engine, "_run_llama", return_value="BTC WAIT; harga di atas Fibonacci.") as inference:
                self.assertIsNotNone(engine.generate_narrative(facts))
                self.assertEqual(inference.call_args.kwargs["temp"], 0.4)
                self.assertEqual(inference.call_args.kwargs["top_p"], 0.8)
                self.assertEqual(inference.call_args.kwargs["top_k"], 20)
                self.assertEqual(inference.call_args.kwargs["presence_penalty"], 1.2)
            with patch.object(engine, "_run_llama", return_value='{"request_type":"ANALYZE","asset":"BTC"}') as inference:
                self.assertIsNotNone(engine.interpret_intent("analisa BTC"))
                self.assertEqual(inference.call_args.kwargs["temp"], 0.0)
        self.assertEqual(format_price(0.000545), "$0.000545")
        self.assertEqual(format_price(86434.22), "$86,434.22")
        tiny = NarrativeFacts(asset="TEST", price=0.000545, decision="WAIT")
        with patch.object(engine, "is_available", return_value=True), patch.object(engine, "_run_llama", return_value="TEST WAIT.") as inference:
            engine.generate_narrative(tiny)
            self.assertIn("$0.000545", inference.call_args.args[0])
        with patch.object(engine, "is_available", return_value=True), patch.object(engine, "_run_llama", return_value="TEST WAIT pada $0.00."):
            self.assertIsNone(engine.generate_narrative(tiny))

    def test_packet_fibonacci_facts_and_safe_fallback(self) -> None:
        runner = CryptoResearchRunner()
        q = self.quant.evaluate("BTC", {"symbol": "BTC", "price": 86434.22, "high": 87000, "low": 83000, "volume": 1000000})
        packet = ResearchPacket(asset="BTC", market="GENERAL / SPOT REFERENCE", timeframe="H1", price=86434.22, decision="WAIT", data_quality="good", setup_quality="weak", fibonacci_confluence="Confluence at Fib 0.618 ($85,778.55)", fibonacci={"material": True, "values": {"fib_618": 85778.55}})
        with patch.object(runner.local_llm, "is_available", return_value=True), patch.object(runner.local_llm, "_run_llama", return_value="BTC WAIT di bawah Fibonacci.") as inference:
            report = runner._render_section_25_view(q, packet=packet, raw_query="BTC hari ini gimana?")
            self.assertNotIn("di bawah Fibonacci", report)
            self.assertIn("86434", inference.call_args.args[0].replace(",", ""))
            self.assertIn("85778.55", inference.call_args.args[0])
            self.assertIn("price relation: ABOVE", inference.call_args.args[0])
        with patch.object(runner.local_llm, "is_available", return_value=True), patch.object(runner.local_llm, "generate_narrative", side_effect=ValueError("invalid optional fact")):
            self.assertIn(q.decision, runner._render_section_25_view(q, raw_query="BTC"))

    def test_frequency_requires_stable_windows(self) -> None:
        stable = [{"close": 100 + math.sin(2 * math.pi * i / 12)} for i in range(120)]
        changing = [{"close": 100 + math.sin(2 * math.pi * i / (7 if i < 60 else 19))} for i in range(120)]
        self.assertTrue(self.quant.evaluate_frequency_cycle(stable)["material"])
        self.assertFalse(self.quant.evaluate_frequency_cycle(changing)["material"])

    # ============================================================
    # I1. HARNESS TEST
    # ============================================================
    def test_i1_harness_session(self) -> None:
        """Verify strict context switching: BTC -> ETH asks confirmation; N keeps BTC; repeat ETH + Y switches; BTC vs ETH runs COMPARE."""
        shell = OpenBagusShell()
        shell.session.last_asset = "BTC"

        # Mock runner.execute to prevent live network calls during shell interaction
        with patch.object(shell.researcher, "execute", return_value="Executed") as mock_exec:
            # 1. User inputs "ETH" while BTC is active, user enters "N"
            with patch("builtins.input", return_value="N"):
                shell.default("ETH")
                # Context must remain BTC
                self.assertEqual(shell.session.last_asset, "BTC")

            # 2. User inputs natural language query "kalau ETH gimana?", user enters "N"
            with patch("builtins.input", return_value="N"):
                shell.default("kalau ETH gimana?")
                # Context must remain BTC
                self.assertEqual(shell.session.last_asset, "BTC")

            # 3. User repeats "ETH" and confirms with "Y"
            with patch("builtins.input", return_value="Y"):
                shell.default("ETH")
                # Context must switch to ETH
                self.assertEqual(shell.session.last_asset, "ETH")

            # 4. User inputs comparison "BTC vs ETH" and "bandingkan BTC dengan ETH"
            with patch("builtins.input") as mock_input:
                shell.default("BTC vs ETH")
                shell.default("bandingkan BTC dengan ETH")
                # Context switch confirmation must NOT be triggered for COMPARE
                mock_input.assert_not_called()

            # 5. Explicit command "/switch BTC" switches immediately without confirmation
            with patch("builtins.input") as mock_input:
                shell.do_switch("BTC")
                mock_input.assert_not_called()
                self.assertEqual(shell.session.last_asset, "BTC")

    # ============================================================
    # I2. SYSTEM CONTEXT TEST
    # ============================================================
    def test_i2_system_context(self) -> None:
        """Verify BTC analysis -> system question ('siapa pembuat OpenBagus?') -> follow-up ('entry tadi dimana?') retains BTC context."""
        session = SessionState()
        session.last_asset = "BTC"

        # 1. System question
        req_sys = self.router.parse("siapa pembuat OpenBagus?", session=session)
        self.assertEqual(req_sys.request_type, "SYSTEM_INFO")
        self.assertIsNone(req_sys.asset)
        # Context remains BTC
        self.assertEqual(session.last_asset, "BTC")

        # 2. Follow-up query
        req_followup = self.router.parse("entry tadi dimana?", session=session)
        self.assertIn(req_followup.request_type, ("POSITION", "EXPLAIN_LEVELS", "FOLLOW_UP"))
        self.assertEqual(req_followup.asset, "BTC")
        self.assertEqual(session.last_asset, "BTC")

    # ============================================================
    # I3. CHART TEST
    # ============================================================
    def test_i3_chart_browser_action(self) -> None:
        """Verify 'chartnya dong' triggers browser chart action only, without full Quant analysis or ASCII candlesticks."""
        session = SessionState()
        session.last_asset = "BTC"
        runner = CryptoResearchRunner()

        req = self.router.parse("chartnya dong", session=session)
        self.assertEqual(req.request_type, "CHART")
        self.assertEqual(req.asset, "BTC")

        # Mock webbrowser.open to prevent browser launching in CI/automated runs
        with patch("webbrowser.open") as mock_open:
            with patch.object(runner.zerokey, "get_spot_ticker", return_value={"price": 85000.0}):
                res = runner.execute(req, session=session)

                # Browser opened with TradingView
                mock_open.assert_called_once()
                opened_url = mock_open.call_args[0][0]
                self.assertIn("tradingview.com", opened_url)
                self.assertIn("BTC", opened_url)

                # Output is concise status only
                self.assertTrue(res.startswith("Opening BTC") or "Opening BTC" in res)
                self.assertNotIn("Quant Decision:", res)
                self.assertNotIn("Reward:Risk", res)
                self.assertNotIn("───", res)

    # ============================================================
    # I4. CPI TEST
    # ============================================================
    def test_i4_cpi_freshness(self) -> None:
        """Verify CPI metadata: August 2026 reference month, next release Oct 14, 2026, is_stale=False."""
        cpi = self.zerokey.get_cpi()
        self.assertEqual(cpi.get("series_id"), "CUUR0000SA0")
        self.assertEqual(cpi.get("reference_month"), "August 2026")
        self.assertEqual(cpi.get("next_release_date"), "2026-10-14")
        self.assertFalse(cpi.get("is_stale"))
        self.assertIn("August 2026", cpi.get("summary", ""))

    # ============================================================
    # I5. FOMC TEST
    # ============================================================
    def test_i5_fomc_schedule(self) -> None:
        """Verify FOMC schedule: Oct 7, 2026 minutes, Oct 27-28, 2026 meeting, and error fallback."""
        fomc = self.zerokey.get_fomc()
        self.assertEqual(fomc.get("next_event"), "2026-10-07 minutes")
        self.assertEqual(fomc.get("next_meeting"), "October 27-28, 2026")
        self.assertIn("2026-10-07 minutes", fomc.get("summary", ""))

        # Error handling when calendar parsing fails
        fomc_err = self.zerokey.get_fomc(html_source="<html>Corrupted HTML without valid dates</html>")
        self.assertEqual(fomc_err.get("error"), "FOMC_CALENDAR_PARSE_ERROR")

    # ============================================================
    # I6. CONDITIONAL FACTOR TEST
    # ============================================================
    def test_i6_conditional_factor_engine(self) -> None:
        """Verify Stochastic, Pattern, and Fibonacci only appear when material confluence criteria are met."""
        # 1. Fibonacci
        klines_fib = [
            {"high": 50.0 + (i * 2.0), "low": 50.0 + (i * 2.0), "close": 50.0 + (i * 2.0)}
            for i in range(26)
        ]
        # Price mid-range (83.0) far from any Fib level -> not material
        fib_mid = self.quant.evaluate_fibonacci(klines_fib, 83.0, 75.0, 60.0, 90.0)
        self.assertFalse(fib_mid.get("material"))

        # Price at 69.15 near Fib 0.618 (69.10) with pivot at 69.0 -> material
        fib_conf = self.quant.evaluate_fibonacci(klines_fib, 69.15, 69.0, 60.0, 90.0)
        self.assertTrue(fib_conf.get("material"))
        self.assertIn("0.618", fib_conf.get("values", {}).get("confluence", ""))

        # 2. Stochastic
        # Flat klines -> neutral %K ~ 50 -> not material
        flat_klines = [{"high": 105.0, "low": 95.0, "close": 100.0} for _ in range(20)]
        stoch_flat = self.quant.evaluate_stochastic(flat_klines, 100.0, 100.0, 95.0, 105.0)
        self.assertFalse(stoch_flat.get("material"))

        # Bearish cross near resistance -> material
        klines_stoch_ob = []
        for _ in range(14):
            klines_stoch_ob.append({"high": 100.0, "low": 50.0, "close": 85.0})
        klines_stoch_ob.append({"high": 100.0, "low": 50.0, "close": 95.0})
        klines_stoch_ob.append({"high": 100.0, "low": 50.0, "close": 98.0})
        klines_stoch_ob.append({"high": 100.0, "low": 50.0, "close": 89.0})
        stoch_bear = self.quant.evaluate_stochastic(klines_stoch_ob, 89.0, 75.0, 60.0, 90.0)
        self.assertTrue(stoch_bear.get("material"))
        self.assertEqual(stoch_bear.get("direction"), "BEARISH")

        # 3. Chart Patterns
        # Flat klines -> no pattern -> not material
        pat_flat = self.quant.evaluate_pattern(flat_klines, 100.0, 100.0, 95.0, 105.0)
        self.assertFalse(pat_flat.get("material"))

        # Confirmed Bearish Engulfing at resistance -> material
        klines_bear_engulf = [
            {"open": 90.0, "high": 92.0, "low": 89.0, "close": 91.0, "volume": 100.0},
            {"open": 91.0, "high": 100.0, "low": 90.5, "close": 99.5, "volume": 120.0},
            {"open": 100.0, "high": 100.5, "low": 89.0, "close": 89.5, "volume": 350.0},
        ]
        pat_bear = self.quant.evaluate_pattern(klines_bear_engulf, 89.5, 95.0, 85.0, 100.0, atr=5.0)
        self.assertTrue(pat_bear.get("material"))
        self.assertEqual(pat_bear.get("values", {}).get("name"), "Bearish Engulfing")

    # ============================================================
    # I7. ARBITRAGE TEST
    # ============================================================
    def test_i7_arbitrage_engine(self) -> None:
        """Verify cross-venue spread materiality: small spreads erased by costs are suppressed; large spreads surfaced."""
        # Tiny gross spread (0.02%) erased by ~0.25% cost -> not material
        ticker_tiny = {"cross_venue_quotes": {"A": {"price": 100.0}, "B": {"price": 100.02}}}
        arb_tiny = self.quant.evaluate_arbitrage(ticker_tiny, 100.0)
        self.assertFalse(arb_tiny.get("material"))

        # Large gross spread (1.50%) surviving ~0.25% cost -> material
        ticker_wide = {"cross_venue_quotes": {"Binance": {"price": 100.0}, "Gate.io": {"price": 101.5}}}
        arb_wide = self.quant.evaluate_arbitrage(ticker_wide, 100.0)
        self.assertTrue(arb_wide.get("material"))
        self.assertGreater(arb_wide.get("values", {}).get("estimated_net_spread_pct", 0.0), 0.10)

    # ============================================================
    # I8. LUNAR TEST
    # ============================================================
    def test_i8_lunar_experimental_astrology(self) -> None:
        """Verify astrology/lunar factor: zero weight, hidden on normal queries, isolated diagnostic only if explicitly asked."""
        runner = CryptoResearchRunner()
        lunar_item = self.quant.evaluate_lunar()
        self.assertTrue(lunar_item.get("available"))
        self.assertFalse(lunar_item.get("material"))
        self.assertEqual(lunar_item.get("values", {}).get("weight"), 0.0)

        # Build mock packet via quant.evaluate
        decision_res = self.quant.evaluate(
            "BTC",
            {"symbol": "BTC", "price": 85000.0, "high": 87000.0, "low": 83000.0, "volume": 1000000.0},
        )

        # 1. Normal BTC query -> no astrology/lunar in report
        with patch.object(runner.local_llm, "is_available", return_value=False):
            rep_normal = runner._render_section_25_view(decision_res, raw_query="analisa BTC")
            self.assertNotIn("Astrology", rep_normal)
            self.assertNotIn("Lunar", rep_normal)

            # 2. Explicit query -> displays experimental diagnostic note
            rep_astro = runner._render_section_25_view(decision_res, raw_query="show experimental lunar factor")
            self.assertIn("Astrology (EXPERIMENTAL / Weight=0)", rep_astro)

        # Decision is unaffected
        self.assertEqual(decision_res.decision, "WAIT")

    # ============================================================
    # I9. NARRATIVE TEST
    # ============================================================
    def test_i9_narrative_consistency_and_anti_template(self) -> None:
        """Verify narrative preserves quantitative decision and numbers while omitting repetitive template headers."""
        runner = CryptoResearchRunner()

        val_bull = ValidationScenario(
            direction="LONG",
            trigger_condition="H1 close above $87,500",
            volume_condition="Volume expansion",
            order_flow_condition="Taker buy > 0.10",
            derivatives_condition="OI expansion",
            entry_zone="$87,500",
            stop_price=86000.0,
            tp1=90000.0,
            tp2=92000.0,
            reward_risk=1.67,
            reward_risk_str="1:1.67",
            summary="Bullish continuation above 87,500",
        )
        val_bear = ValidationScenario(
            direction="SHORT",
            trigger_condition="H1 breakdown below $83,000",
            volume_condition="Sell volume spike",
            order_flow_condition="Taker sell < -0.10",
            derivatives_condition="OI rise on breakdown",
            entry_zone="$83,000",
            stop_price=84500.0,
            tp1=80000.0,
            tp2=78000.0,
            reward_risk=2.0,
            reward_risk_str="1:2.00",
            summary="Bearish continuation below 83,000",
        )

        decision_res = self.quant.evaluate(
            "BTC",
            {"symbol": "BTC", "price": 85000.0, "high": 87000.0, "low": 83000.0, "volume": 1000000.0},
        )
        decision_res.bullish_validation = val_bull
        decision_res.bearish_validation = val_bear

        with patch.object(runner.local_llm, "is_available", return_value=False):
            report = runner._render_section_25_view(decision_res, raw_query="BTC")

        # 1. Quantitative decision preserved
        self.assertIn("WAIT", report)
        self.assertIn("$85,000", report)

        # 2. Conditional actionable setup present with concrete levels
        self.assertIn("Conditional setup:", report)
        self.assertIn("Long valid if : H1 close above $87,500", report)
        self.assertIn("Short valid if: H1 breakdown below $83,000", report)

        # 3. No formulaic template headers
        self.assertNotIn("Reason:", report)
        self.assertNotIn("Watch:", report)
        self.assertNotIn("Summary:", report)
        self.assertNotIn("Why:", report)

        # 4. Irrelevant/non-material factors omitted
        self.assertNotIn("Fibonacci:", report)
        self.assertNotIn("Stochastic:", report)
        self.assertNotIn("Arbitrage:", report)


if __name__ == "__main__":
    unittest.main()
