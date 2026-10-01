import os
import ssl
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from openbagus.analysis.engine import DataQualityAgent, run_real_analysis
from openbagus.core.env import get_repo_root
from openbagus.data.ingestion import RuntimeDataIngestion, run_runtime_ingestion
from openbagus.delivery.runner import run_final_delivery


class TestCryptoPipeline(unittest.TestCase):
    def test_missing_market_data_is_blocked(self):
        quality = DataQualityAgent({}, "2026-10-01T00:00:00Z").evaluate_market_row("BTC/USD", None)
        self.assertEqual(quality["analysis_status"], "STALE_DATA_BLOCKED")
        self.assertEqual(quality["freshness_status"], "SOURCE_NOT_AVAILABLE")

    def test_dry_run_ingestion(self):
        root = get_repo_root()
        res = run_runtime_ingestion(mode="dry-run", all_core=True, repo_root=root)
        self.assertEqual(res["mode"], "dry-run")
        self.assertEqual(res["active_domain"], "crypto")
        self.assertGreater(len(res["source_health"]), 0)

    def test_provider_config_and_tls_are_active(self):
        engine = RuntimeDataIngestion(get_repo_root())
        templates = engine.source_config["source_templates"]
        self.assertIn("coingecko_simple_price", templates)
        self.assertTrue(all("provider_symbol" in item for item in engine.source_config["core_assets"]["macro_market"].values()))
        self.assertEqual(engine.ssl_context.verify_mode, ssl.CERT_REQUIRED)
        self.assertTrue(engine.ssl_context.check_hostname)

    def test_fred_key_is_not_persisted_in_source_url(self):
        with tempfile.TemporaryDirectory() as temp_dir, patch.dict(os.environ, {"FRED_API_KEY": "private-test-key"}):
            root = Path(temp_dir)
            config_dir = root / "config"
            config_dir.mkdir()
            (config_dir / "openbagus_data_sources.json").write_text(
                '{"source_templates":{"fred_latest":{"url":"https://example.test?series_id={series_id}&api_key={api_key}"}}}',
                encoding="utf-8",
            )
            engine = RuntimeDataIngestion(root)
            response = {"ok": True, "payload": {"observations": [{"value": "4.1", "date": "2026-09-30"}]}}
            with patch.object(engine, "_fetch_json", return_value=response):
                engine._fetch_fred_if_available()

        self.assertTrue(engine.macro_rows)
        self.assertNotIn("private-test-key", str(engine.macro_rows))

    def test_provider_failure_remains_an_explicit_source_gap(self):
        engine = RuntimeDataIngestion(get_repo_root())
        asset_config = engine.source_config["core_assets"]["crypto"]["BTC/USD"]
        failure = {"ok": False, "payload": None, "error": "network unavailable"}
        with patch.object(engine, "_fetch_json", return_value=failure):
            engine._fetch_crypto_from_coingecko("BTC/USD", asset_config)

        self.assertFalse(engine.market_rows)
        self.assertEqual(engine.source_health[-1]["status"], "FAIL")
        self.assertEqual(engine.source_health[-1]["reason"], "network unavailable")

    def test_safe_delivery_staging(self):
        root = get_repo_root()
        deliv = run_final_delivery(mode="crypto-daily", dry_run=True, repo_root=root)
        self.assertIn(deliv["status"], {"DELIVERY_STAGED_SUCCESS", "ANALYSIS_MISSING"})
        if deliv["status"] == "DELIVERY_STAGED_SUCCESS":
            self.assertEqual(deliv["send_mode"], "NO_SEND_FILE_ONLY")


if __name__ == "__main__":
    unittest.main()
