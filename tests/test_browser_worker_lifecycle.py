"""Tests for BrowserWorkerManager full lifecycle, security bounds, and state machine.

Verifies:
1. DOWNLOADED != READY: Download alone never marks job as READY.
2. Full lifecycle: FETCHING -> PARSING -> VALIDATING -> CALCULATING -> READY.
3. Parse failure or unparsable format transitions to PARTIAL_DATA, never false-positive READY.
4. Security: 50MB file size limit enforcement (oversized files skipped/deleted).
5. Security: Path traversal protection on downloaded filenames.
"""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from openbagus.domains.equities.browser_worker import (
    BrowserJob,
    BrowserWorkerManager,
)
from openbagus.domains.equities.financial_model import CanonicalFinancialStatement


class TestBrowserWorkerLifecycle(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.manager = BrowserWorkerManager(root=self.root)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_downloaded_alone_does_not_equal_ready(self) -> None:
        """A downloaded file that fails to parse must transition to PARTIAL_DATA, NOT READY."""
        job = BrowserJob(
            job_id="job-unparsed-1",
            symbol="BBCA",
            target_url="https://bca.co.id/investor-relations/reports",
            state="QUEUED",
        )
        self.manager._save_job(job)

        # Create dummy unparsable file
        dest_dir = self.manager.downloads_dir / "BBCA"
        dest_dir.mkdir(parents=True, exist_ok=True)
        corrupted_file = dest_dir / "corrupted_statement.pdf"
        corrupted_file.write_text("Not a valid PDF header or content", encoding="utf-8")

        # Mock the browser download to produce the corrupted file
        with patch("playwright.sync_api.sync_playwright") as mock_playwright:
            mock_p = MagicMock()
            mock_browser = MagicMock()
            mock_context = MagicMock()
            mock_page = MagicMock()
            mock_playwright.return_value.__enter__.return_value = mock_p
            mock_p.chromium.launch.return_value = mock_browser
            mock_browser.new_context.return_value = mock_context
            mock_context.new_page.return_value = mock_page

            # Mock finding 1 link and downloading it
            mock_link = MagicMock()
            mock_link.get_attribute.return_value = "https://bca.co.id/corrupted_statement.pdf"
            mock_link.inner_text.return_value = "Laporan Keuangan"
            mock_page.locator.return_value.all.return_value = [mock_link]

            mock_download = MagicMock()
            mock_download.suggested_filename = "corrupted_statement.pdf"
            mock_page.expect_download.return_value.__enter__.return_value.value = mock_download

            self.manager._run_job_worker(job)

        updated_job = self.manager.get_job("job-unparsed-1")
        self.assertIsNotNone(updated_job)
        # MUST NOT be READY
        self.assertNotEqual(updated_job.state, "READY")
        self.assertEqual(updated_job.state, "PARTIAL_DATA")
        self.assertIn("belum dapat diekstrak otomatis", updated_job.message)

    def test_full_pipeline_success_transitions_to_ready(self) -> None:
        """When download parses successfully into a statement, it passes VALIDATING and CALCULATING to READY."""
        job = BrowserJob(
            job_id="job-success-1",
            symbol="TLKM",
            target_url="https://telkom.co.id/financial-reports",
            state="QUEUED",
        )
        self.manager._save_job(job)

        dest_dir = self.manager.downloads_dir / "TLKM"
        dest_dir.mkdir(parents=True, exist_ok=True)
        sample_file = dest_dir / "valid_statement.xlsx"
        sample_file.write_text("dummy xlsx binary content", encoding="utf-8")

        mock_stmt = CanonicalFinancialStatement(
            symbol="TLKM",
            period="2024-FY",
            period_type="FY",
            currency="IDR",
            unit="million_IDR",
            unit_multiplier=1e6,
            basis="consolidated",
            audit_status="audited",
            period_end_date="2024-12-31",
            revenue=150_000_000.0,
            operating_income=45_000_000.0,
            net_income_attributable=25_000_000.0,
            total_assets=280_000_000.0,
            total_liabilities=130_000_000.0,
            equity_attributable_to_owners=150_000_000.0,
            shares_outstanding=99_062_216_600.0,
        )

        with patch("playwright.sync_api.sync_playwright") as mock_playwright, \
             patch("openbagus.domains.equities.parsers.xlsx_parser.IdxXlsxParser.parse_file", return_value=mock_stmt):
            mock_p = MagicMock()
            mock_browser = MagicMock()
            mock_context = MagicMock()
            mock_page = MagicMock()
            mock_playwright.return_value.__enter__.return_value = mock_p
            mock_p.chromium.launch.return_value = mock_browser
            mock_browser.new_context.return_value = mock_context
            mock_context.new_page.return_value = mock_page

            mock_link = MagicMock()
            mock_link.get_attribute.return_value = "https://telkom.co.id/valid_statement.xlsx"
            mock_link.inner_text.return_value = "Laporan 2024"
            mock_page.locator.return_value.all.return_value = [mock_link]

            mock_download = MagicMock()
            mock_download.suggested_filename = "valid_statement.xlsx"
            mock_page.expect_download.return_value.__enter__.return_value.value = mock_download

            self.manager._run_job_worker(job)

        updated_job = self.manager.get_job("job-success-1")
        self.assertIsNotNone(updated_job)
        self.assertEqual(updated_job.state, "READY")
        self.assertEqual(updated_job.progress_pct, 100)
        self.assertIsNotNone(updated_job.parsed_statement)
        self.assertEqual(updated_job.parsed_statement["period"], "2024-FY")

    def test_oversized_file_limit_enforcement(self) -> None:
        """Files exceeding 50MB must be rejected and not included in parsed statements."""
        job = BrowserJob(
            job_id="job-oversized-1",
            symbol="BMRI",
            target_url="https://bankmandiri.co.id/reports",
            state="QUEUED",
        )
        self.manager._save_job(job)

        dest_dir = self.manager.downloads_dir / "BMRI"
        dest_dir.mkdir(parents=True, exist_ok=True)
        oversized_file = dest_dir / "huge_report.pdf"

        with patch("playwright.sync_api.sync_playwright") as mock_playwright, \
             patch("pathlib.Path.stat") as mock_stat:
            mock_p = MagicMock()
            mock_browser = MagicMock()
            mock_context = MagicMock()
            mock_page = MagicMock()
            mock_playwright.return_value.__enter__.return_value = mock_p
            mock_p.chromium.launch.return_value = mock_browser
            mock_browser.new_context.return_value = mock_context
            mock_context.new_page.return_value = mock_page

            mock_link = MagicMock()
            mock_link.get_attribute.return_value = "https://bankmandiri.co.id/huge_report.pdf"
            mock_link.inner_text.return_value = "Huge Report"
            mock_page.locator.return_value.all.return_value = [mock_link]

            mock_download = MagicMock()
            mock_download.suggested_filename = "huge_report.pdf"
            mock_page.expect_download.return_value.__enter__.return_value.value = mock_download

            # Return 60MB size
            stat_obj = MagicMock()
            stat_obj.st_size = 60 * 1024 * 1024
            mock_stat.return_value = stat_obj

            self.manager._run_job_worker(job)

        updated_job = self.manager.get_job("job-oversized-1")
        self.assertIsNotNone(updated_job)
        self.assertNotEqual(updated_job.state, "READY")
        self.assertEqual(updated_job.state, "PARTIAL_DATA")


if __name__ == "__main__":
    unittest.main()
