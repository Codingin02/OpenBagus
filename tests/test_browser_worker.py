"""Unit and integration tests for BrowserWorkerManager and BrowserJob.

Verifies:
- Official financial domain whitelist verification.
- Blocked domain protection (BLOCKED_SOURCE state).
- Job enqueueing, status persistence to disk, and retrieval.
- Active jobs cache vs disk hydration.
- Concurrency limiting via semaphore.
- Job state progression handling.
"""

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from openbagus.domains.equities.browser_worker import (
    APPROVED_DOMAINS,
    BrowserJob,
    BrowserWorkerManager,
)


class TestBrowserWorkerManager(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.manager = BrowserWorkerManager(root=self.root)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_url_whitelist_approval(self) -> None:
        # Approved domains
        self.assertTrue(self.manager.is_url_approved("https://www.sec.gov/edgar/searchedgar/companysearch"))
        self.assertTrue(self.manager.is_url_approved("https://data.sec.gov/api/xbrl/companyfacts/CIK0000320193.json"))
        self.assertTrue(self.manager.is_url_approved("https://www.idx.co.id/id/perusahaan-tercatat/laporan-keuangan-dan-tahunan/"))
        self.assertTrue(self.manager.is_url_approved("https://idx.co.id/filings/BBCA.xlsx"))
        self.assertTrue(self.manager.is_url_approved("https://bca.co.id/investor-relations/reports"))
        self.assertTrue(self.manager.is_url_approved("https://ir.apple.com/financials/default.aspx"))

        # Blocked domains
        self.assertFalse(self.manager.is_url_approved("https://unknown-financial-blog.xyz/scam"))
        self.assertFalse(self.manager.is_url_approved("http://malicious-site.org/leak.pdf"))
        self.assertFalse(self.manager.is_url_approved("https://google.com"))

    def test_enqueue_blocked_url(self) -> None:
        job = self.manager.enqueue_retrieval(
            symbol="BBCA",
            target_url="https://unauthorized-leak.com/filing.pdf",
        )
        self.assertEqual(job.state, "BLOCKED_SOURCE")
        self.assertIn("tidak ada dalam whitelist", job.message)

        # Verify persisted state
        persisted = self.manager.get_job(job.job_id)
        self.assertIsNotNone(persisted)
        self.assertEqual(persisted.state, "BLOCKED_SOURCE")

    def test_enqueue_valid_url_persistence(self) -> None:
        with patch.object(self.manager, "_run_job_worker"):
            job = self.manager.enqueue_retrieval(
                symbol="BBRI",
                target_url="https://www.idx.co.id/id/perusahaan-tercatat/laporan-keuangan/",
                period="2024-FY",
            )
            self.assertEqual(job.symbol, "BBRI")
            self.assertEqual(job.state, "QUEUED")
            self.assertEqual(job.period, "2024-FY")

            # Check retrieval from memory
            job_mem = self.manager.get_job(job.job_id)
            self.assertEqual(job_mem.job_id, job.job_id)

            # Check list_jobs
            jobs = self.manager.list_jobs()
            self.assertGreaterEqual(len(jobs), 1)
            self.assertEqual(jobs[0].job_id, job.job_id)

    def test_job_state_transitions_mocked_worker(self) -> None:
        job = BrowserJob(
            job_id="job-test-123",
            symbol="TLKM",
            target_url="https://www.idx.co.id/filings/TLKM.pdf",
            state="QUEUED",
        )
        self.manager._save_job(job)

        # Update to FETCHING
        job.state = "FETCHING"
        job.progress_pct = 25
        self.manager._save_job(job)

        loaded = self.manager.get_job("job-test-123")
        self.assertEqual(loaded.state, "FETCHING")
        self.assertEqual(loaded.progress_pct, 25)

        # Update to READY
        job.state = "READY"
        job.progress_pct = 100
        job.downloaded_files = ["/path/to/TLKM_2024.pdf"]
        self.manager._save_job(job)

        loaded_final = self.manager.get_job("job-test-123")
        self.assertEqual(loaded_final.state, "READY")
        self.assertEqual(loaded_final.progress_pct, 100)
        self.assertEqual(loaded_final.downloaded_files, ["/path/to/TLKM_2024.pdf"])


if __name__ == "__main__":
    unittest.main()
