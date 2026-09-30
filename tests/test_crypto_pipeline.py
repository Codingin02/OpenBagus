"""Test Crypto Pipeline Ingestion, Analysis, and Safe Staging."""

import unittest

from openbagus.analysis.engine import DataQualityAgent, run_real_analysis
from openbagus.core.env import get_repo_root
from openbagus.data.ingestion import run_runtime_ingestion
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

    def test_safe_delivery_staging(self):
        root = get_repo_root()
        deliv = run_final_delivery(mode="crypto-daily", dry_run=True, repo_root=root)
        self.assertIn(deliv["status"], {"DELIVERY_STAGED_SUCCESS", "ANALYSIS_MISSING"})
        if deliv["status"] == "DELIVERY_STAGED_SUCCESS":
            self.assertEqual(deliv["send_mode"], "NO_SEND_FILE_ONLY")


if __name__ == "__main__":
    unittest.main()
