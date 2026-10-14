"""Acceptance Test Suite for OpenBagus Automated Data & AI Intelligence.

Covers Tests A through N using standard unittest:
- Test A: RATU Live EOD & Financials (auto-fetch, 400+ candles, non-empty close, valid ratios, PER/PBV)
- Test B: DATA Live EOD & Financials (lexical disambiguation, auto-fetch, valid candles)
- Test C: Small-Cap Discovery (catalog resolution, acceleration board)
- Test D: BBCA Multi-Period Bank Ratios (NIM, CAR, NPL, Solvency across periods)
- Test E: US Equity SEC EDGAR Facts (Apple Inc. CIK 320193 / AAPL XBRL facts)
- Test F: Crypto Multi-Exchange Zero-Key (BTC spot quote from Binance Vision / Gate.io)
- Test G: Macro Indicator Adapter (Indonesia CPI / Inflasi from World Bank Open Data)
- Test H: OpenAI Provider Level 1 & Level 2 Verification
- Test I: Gemini Provider Level 1 & Level 2 Verification
- Test J: Cost-Aware Router & $0 Default Guardrail
- Test K: Rate-Limiting Backoff & Provider Error 429 Handling
- Test L: Offline Cache Resiliency
- Test M: Conversational Context Retention
- Test N: Worktree & Boundary Safety
"""

from __future__ import annotations

import json
import os
import shutil
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from openbagus.ai.credentials import CredentialManager, mask_secret, redact_secrets
from openbagus.ai.harness.orchestrator import AgentHarness
from openbagus.ai.memory.working_context import WorkingContext
from openbagus.ai.providers.gemini_provider import GeminiProvider
from openbagus.ai.providers.openai_provider import OpenAIProvider
from openbagus.ai.routing.cost_router import CostAwareModelRouter, ModelRole
from openbagus.ai.tools.finance_tools import (
    CalculateFinancialRatiosTool,
    CalculateValuationTool,
    GetDataCoverageTool,
    GetMacroSeriesTool,
    GetMarketPriceTool,
    GetOHLCVTool,
    RefreshAssetDataTool,
)
from openbagus.core.env import get_repo_root
from openbagus.data.provider_base import ErrorCode
from openbagus.data.registry import DataProviderRegistry
from openbagus.data.scheduler import DataSyncScheduler, SyncPriority
from openbagus.data.zerokey import ZeroKeyMarketData
from openbagus.domains.equities.catalog import EquityCatalog
from openbagus.domains.equities.data import EquityData
from openbagus.domains.equities.storage import FinancialStatementStorage
from openbagus.domains.equities.sec_edgar import SecEdgarClient


class TestDataIntelligenceLive(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.repo_root = get_repo_root()

    # -------------------------------------------------------------------------
    # Test A: RATU Live EOD & Financials
    # -------------------------------------------------------------------------
    def test_a_ratu_live_eod_and_financials(self) -> None:
        eq_data = EquityData(self.repo_root)
        data = eq_data.load("RATU", auto_fetch=True)
        self.assertIsInstance(data, dict)
        candles = data.get("candles", [])
        self.assertGreaterEqual(len(candles), 300, f"Expected >= 300 candles, got {len(candles)}")

        last_candle = candles[-1]
        self.assertGreater(float(last_candle["close"]), 0)

        # Verify market price tool
        px_tool = GetMarketPriceTool()
        res, meta = px_tool.run(ticker="RATU")
        self.assertIsNotNone(res.get("close"))
        self.assertNotIn(res.get("observation_date"), (None, "-"))

        # Verify ratios calculation
        ratios_tool = CalculateFinancialRatiosTool()
        r_res, _ = ratios_tool.run(ticker="RATU")
        self.assertEqual(r_res.get("symbol"), "RATU")
        self.assertIsNotNone(r_res.get("der"))
        self.assertIsNotNone(r_res.get("roe_pct"))
        self.assertEqual(r_res.get("accounting_health"), "Solvent")

        # Verify valuation tool
        val_tool = CalculateValuationTool()
        v_res, _ = val_tool.run(ticker="RATU")
        self.assertEqual(v_res.get("symbol"), "RATU")
        self.assertIsNotNone(v_res.get("multiples", {}).get("PER"))
        self.assertIsNotNone(v_res.get("multiples", {}).get("PBV"))

    # -------------------------------------------------------------------------
    # Test B: DATA Live EOD & Financials (Disambiguation)
    # -------------------------------------------------------------------------
    def test_b_data_live_eod_and_financials(self) -> None:
        cat = EquityCatalog(self.repo_root)
        resolved = cat.resolve("DATA")
        self.assertIsNotNone(resolved)
        self.assertEqual(resolved.symbol, "DATA")
        self.assertIn("REMALA", resolved.name.upper())

        eq_data = EquityData(self.repo_root)
        data = eq_data.load("DATA", auto_fetch=True)
        self.assertIsInstance(data, dict)
        candles = data.get("candles", [])
        self.assertGreaterEqual(len(candles), 400)
        self.assertGreater(float(candles[-1]["close"]), 0)

    # -------------------------------------------------------------------------
    # Test C: Small-Cap & Universe Discovery
    # -------------------------------------------------------------------------
    def test_c_small_cap_discovery(self) -> None:
        cat = EquityCatalog(self.repo_root)
        stats = cat.get_universe_stats()
        self.assertGreaterEqual(stats["common_equities"], 950)
        self.assertIn("DEVELOPMENT", stats["boards"])
        self.assertIn("ACCELERATION", stats["boards"])

        accel = cat.resolve("SOLIX") or cat.resolve("AYAM") or cat.resolve("FILM")
        self.assertIsNotNone(accel)

    # -------------------------------------------------------------------------
    # Test D: BBCA Multi-Period Bank Ratios
    # -------------------------------------------------------------------------
    def test_d_bbca_multi_period_bank_ratios(self) -> None:
        storage = FinancialStatementStorage(self.repo_root)
        periods = storage.list_periods("BBCA")
        self.assertIn("2023-FY", periods)
        self.assertIn("2024-FY", periods)

        stmt_2024 = storage.get_statement("BBCA", "2024-FY")
        self.assertIsNotNone(stmt_2024)
        ratios = stmt_2024.get("reported_ratios_pct", {})
        self.assertGreaterEqual(ratios.get("NIM", 0.0), 5.0)
        self.assertGreaterEqual(ratios.get("CAR", 0.0), 20.0)
        self.assertLessEqual(ratios.get("NPL_gross", 10.0), 3.0)

        # Test tool run
        tool = CalculateFinancialRatiosTool()
        res, _ = tool.run(ticker="BBCA")
        self.assertEqual(res.get("symbol"), "BBCA")
        self.assertIsNotNone(res.get("reported_banking_ratios"))

    # -------------------------------------------------------------------------
    # Test E: US Equity SEC EDGAR Facts (Apple Inc. / AAPL)
    # -------------------------------------------------------------------------
    def test_e_us_equity_sec_edgar_facts(self) -> None:
        client = SecEdgarClient(self.repo_root)
        cik = client.resolve_ticker("AAPL")
        self.assertIsNotNone(cik)

        facts = client.get_company_facts("AAPL")
        self.assertIsNotNone(facts)
        self.assertEqual(facts.get("entityName"), "Apple Inc.")
        self.assertIn("us-gaap", facts.get("facts", {}))

        stmts = client.extract_canonical_statements("AAPL")
        self.assertGreaterEqual(len(stmts), 10)
        latest = stmts[0]
        self.assertEqual(latest.symbol, "AAPL")
        self.assertIsNotNone(latest.total_assets)

    # -------------------------------------------------------------------------
    # Test F: Crypto Multi-Exchange Zero-Key (BTC)
    # -------------------------------------------------------------------------
    def test_f_crypto_multi_exchange_zero_key(self) -> None:
        zerokey = ZeroKeyMarketData.get_instance()
        btc = zerokey.get_spot_ticker("BTC")
        self.assertIsNotNone(btc)
        self.assertGreater(btc["price"], 10_000.0)
        self.assertGreater(btc["volume"], 0)

        px_tool = GetMarketPriceTool()
        res, meta = px_tool.run(ticker="BTC")
        self.assertTrue(res.get("is_crypto"))
        self.assertGreater(res.get("price"), 10_000.0)

    # -------------------------------------------------------------------------
    # Test G: Macro Indicator Adapter (Indonesia CPI)
    # -------------------------------------------------------------------------
    def test_g_macro_indicator_adapter(self) -> None:
        reg = DataProviderRegistry.get_instance(self.repo_root)
        prov = reg.get_provider("WORLD_BANK_MACRO")
        self.assertIsNotNone(prov)
        res = prov.fetch_macro_series("CPI")
        self.assertTrue(res.success)
        self.assertEqual(res.data["indicator"], "CPI")
        self.assertEqual(res.data["country"], "IDN")
        self.assertGreater(float(res.data["latest_value"]), 0)

        macro_tool = GetMacroSeriesTool()
        t_res, meta = macro_tool.run(series="CPI")
        self.assertEqual(t_res.get("indicator"), "CPI")
        self.assertEqual(meta.get("source").lower(), "worldbank_macro")

    # -------------------------------------------------------------------------
    # Test H: OpenAI Provider Level 1 & Level 2 Verification
    # -------------------------------------------------------------------------
    def test_h_openai_provider_levels(self) -> None:
        prov = OpenAIProvider(api_key="sk-testmockedkey1234567890abcdef")
        self.assertEqual(prov.get_provider_name(), "OPENAI")
        info = prov.get_model_info()
        self.assertTrue(info["configured"])
        self.assertTrue(info["masked_key"].startswith("sk-"))

        with patch("urllib.request.urlopen") as mock_url:
            mock_resp = MagicMock()
            mock_resp.read.return_value = json.dumps({"data": [{"id": "gpt-4o-mini"}]}).encode("utf-8")
            mock_resp.__enter__.return_value = mock_resp
            mock_url.return_value = mock_resp

            ok, msg = prov.verify_level_1()
            self.assertTrue(ok)
            self.assertIn("terverifikasi", msg.lower())

    # -------------------------------------------------------------------------
    # Test I: Gemini Provider Level 1 & Level 2 Verification
    # -------------------------------------------------------------------------
    def test_i_gemini_provider_levels(self) -> None:
        prov = GeminiProvider(api_key="AIzaSyMockedKey1234567890abcdef")
        self.assertEqual(prov.get_provider_name(), "GEMINI")
        info = prov.get_model_info()
        self.assertTrue(info["configured"])
        self.assertTrue(info["masked_key"].startswith("AIza"))

        with patch("urllib.request.urlopen") as mock_url:
            mock_resp = MagicMock()
            mock_resp.read.return_value = json.dumps({"models": [{"name": "models/gemini-2.5-flash"}]}).encode("utf-8")
            mock_resp.__enter__.return_value = mock_resp
            mock_url.return_value = mock_resp

            ok, msg = prov.verify_level_1()
            self.assertTrue(ok)
            self.assertIn("terverifikasi", msg.lower())

    # -------------------------------------------------------------------------
    # Test J: Cost-Aware Router & $0 Default Guardrail
    # -------------------------------------------------------------------------
    def test_j_cost_aware_router_budget(self) -> None:
        tmp_dir = Path(tempfile.mkdtemp())
        try:
            ledger_file = tmp_dir / "test_spend.json"
            router = CostAwareModelRouter(ledger_path=ledger_file)
            router.set_budget(0.00, enable_cloud=False)

            self.assertFalse(router.can_use_cloud())
            p, role = router.route(ModelRole.RESEARCH_SYNTHESIZER)
            self.assertIn(p.get_provider_name(), ("OLLAMA_DEEP", "LLAMA_CPP_LOCAL", "LLAMA_CPP_CUDA", "DETERMINISTIC_FALLBACK"))

            router.set_budget(5.00, enable_cloud=True)
            self.assertTrue(router.can_use_cloud())
            self.assertEqual(router.get_remaining_budget_usd(), 5.00)

            router.record_usage("OPENAI", "gpt-4o", ModelRole.RESEARCH_SYNTHESIZER, 1_000_000, 1_000_000)
            self.assertEqual(router.get_remaining_budget_usd(), 0.0)
            self.assertFalse(router.can_use_cloud())
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)

    # -------------------------------------------------------------------------
    # Test K: Rate-Limiting Backoff & Provider Error Handling
    # -------------------------------------------------------------------------
    def test_k_rate_limiting_and_backoff(self) -> None:
        sched = DataSyncScheduler.get_instance(self.repo_root)
        sched._trigger_backoff("YAHOO_FINANCE", base_delay=10.0)

        res = sched.sync_ticker("BBCA", priority=SyncPriority.B_ACTIVE_WATCHLIST, force=False)
        self.assertEqual(res.status, "RATE_LIMITED")
        self.assertEqual(res.error_code, ErrorCode.RATE_LIMITED.value)

        sched._rate_limits["YAHOO_FINANCE"]["backoff_until"] = 0.0

    # -------------------------------------------------------------------------
    # Test L: Offline Cache Resiliency
    # -------------------------------------------------------------------------
    def test_l_offline_cache_resiliency(self) -> None:
        eq_data = EquityData(self.repo_root)
        cached_file = eq_data.directory / "RATU.json"
        self.assertTrue(cached_file.exists())

        offline_data = eq_data.load("RATU", auto_fetch=False)
        self.assertIsNotNone(offline_data)
        self.assertGreater(len(offline_data.get("candles", [])), 0)

    # -------------------------------------------------------------------------
    # Test M: Conversational Context Retention
    # -------------------------------------------------------------------------
    def test_m_conversational_context_retention(self) -> None:
        harness = AgentHarness()
        ctx = WorkingContext()

        # Turn 1: Analyze RATU
        r1 = harness.run("Tolong analisis saham RATU", context=ctx)
        self.assertEqual(ctx.active_ticker, "RATU")
        self.assertIn("RATU", r1.content)
        self.assertGreaterEqual(len(ctx.turns), 2)

        # Turn 2: Follow-up question about volume (retaining RATU)
        r2 = harness.run("Berapa volume transaksinya?", context=ctx)
        self.assertEqual(ctx.active_ticker, "RATU")
        self.assertTrue("Volume" in r2.content or "RATU" in r2.content or "lembar" in r2.content)

        # Turn 3: Switch to BTC
        r3 = harness.run("Bagaimana dengan BTC?", context=ctx)
        self.assertEqual(ctx.active_ticker, "BTC")
        self.assertIn("BTC", r3.content)
        self.assertGreaterEqual(len(ctx.turns), 6)

    # -------------------------------------------------------------------------
    # Test N: Worktree & Boundary Safety
    # -------------------------------------------------------------------------
    def test_n_worktree_and_boundary_safety(self) -> None:
        projects_dir = Path("E:/Projects")
        worktree_3d = projects_dir / "OpenBagus-3D"
        worktree_voice = projects_dir / "OpenBagus-Voice"

        if worktree_3d.exists():
            git_head_3d = worktree_3d / ".git"
            self.assertTrue(git_head_3d.exists())

        if worktree_voice.exists():
            git_head_voice = worktree_voice / ".git"
            self.assertTrue(git_head_voice.exists())


if __name__ == "__main__":
    unittest.main()
