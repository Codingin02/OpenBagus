"""Native Background Browser Engine and Document Retrieval Worker.

Uses Playwright and headless Chromium inside OpenBagus to retrieve public,
authorized financial statements and filings from approved domains when direct
structured APIs are unavailable or when JavaScript rendering is required.

Job Lifecycle States:
  QUEUED -> FETCHING -> PARSING -> VALIDATING -> CALCULATING -> READY
  PARTIAL_DATA, STALE, BLOCKED_SOURCE, FAILED, CANCELLED
"""

from __future__ import annotations

import json
import logging
import os
import re
import threading
import time
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

logger = logging.getLogger(__name__)

# Approved official financial document discovery domains
APPROVED_DOMAINS = {
    "sec.gov",
    "data.sec.gov",
    "www.sec.gov",
    "idx.co.id",
    "www.idx.co.id",
    # Official Bank & Blue Chip IR sites
    "bca.co.id",
    "bri.co.id",
    "bankmandiri.co.id",
    "telkom.co.id",
    "astra.co.id",
    "unitedtractors.com",
    "adaro.com",
    "indofood.com",
    "icbp.co.id",
    "apple.com",
    "microsoft.com",
}


@dataclass
class BrowserJob:
    """Represents a background financial document retrieval job."""
    job_id: str
    symbol: str
    target_url: str
    period: str | None = None
    state: str = "QUEUED"  # QUEUED, FETCHING, PARSING, VALIDATING, CALCULATING, READY, FAILED, etc.
    progress_pct: int = 0
    message: str = "Job queued"
    downloaded_files: list[str] = field(default_factory=list)
    parsed_statement: dict[str, Any] | None = None
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    error: str | None = None


class BrowserWorkerManager:
    """Manages headless browser worker tasks, background job queue, and durable status tracking."""

    def __init__(self, root: Path | None = None) -> None:
        self.root = root or Path.cwd()
        self.jobs_dir = self.root / "data" / "jobs"
        self.jobs_dir.mkdir(parents=True, exist_ok=True)
        self.downloads_dir = self.root / "data" / "equities" / "downloads"
        self.downloads_dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._active_jobs: dict[str, BrowserJob] = {}
        self._max_concurrency = 2
        self._semaphore = threading.Semaphore(self._max_concurrency)

    def _save_job(self, job: BrowserJob) -> None:
        job.updated_at = datetime.now(timezone.utc).isoformat()
        job_file = self.jobs_dir / f"{job.job_id}.json"
        try:
            job_file.write_text(json.dumps(asdict(job), indent=2), encoding="utf-8")
        except Exception as exc:
            logger.warning("Failed to persist job status %s: %s", job.job_id, exc)

    def get_job(self, job_id: str) -> BrowserJob | None:
        with self._lock:
            if job_id in self._active_jobs:
                return self._active_jobs[job_id]
        job_file = self.jobs_dir / f"{job_id}.json"
        if job_file.exists():
            try:
                data = json.loads(job_file.read_text(encoding="utf-8"))
                return BrowserJob(**data)
            except Exception:
                pass
        return None

    def list_jobs(self, limit: int = 20) -> list[BrowserJob]:
        """Lists recent jobs sorted by creation time."""
        jobs: list[BrowserJob] = []
        for file in sorted(self.jobs_dir.glob("*.json"), reverse=True)[:limit]:
            try:
                data = json.loads(file.read_text(encoding="utf-8"))
                jobs.append(BrowserJob(**data))
            except Exception:
                pass
        return jobs

    def is_url_approved(self, url: str) -> bool:
        """Verifies that the target domain is on the approved financial source whitelist."""
        from urllib.parse import urlparse
        hostname = (urlparse(url).hostname or "").lower()
        if any(hostname == domain or hostname.endswith("." + domain) for domain in APPROVED_DOMAINS):
            return True
        return False

    def enqueue_retrieval(
        self,
        symbol: str,
        target_url: str,
        period: str | None = None,
        callback: Callable[[BrowserJob], None] | None = None,
    ) -> BrowserJob:
        """Enqueues a background document retrieval task."""
        job_id = f"job-{uuid.uuid4().hex[:12]}"
        clean_sym = symbol.strip().upper()

        if not self.is_url_approved(target_url):
            job = BrowserJob(
                job_id=job_id,
                symbol=clean_sym,
                target_url=target_url,
                period=period,
                state="BLOCKED_SOURCE",
                message=f"Domain {target_url} tidak ada dalam whitelist domain keuangan resmi yang diizinkan.",
            )
            self._save_job(job)
            return job

        job = BrowserJob(
            job_id=job_id,
            symbol=clean_sym,
            target_url=target_url,
            period=period,
            state="QUEUED",
            progress_pct=5,
            message="Tugas pengambilan dokumen masuk antrean latar belakang.",
        )
        with self._lock:
            self._active_jobs[job_id] = job
        self._save_job(job)

        thread = threading.Thread(
            target=self._run_job_worker,
            args=(job, callback),
            daemon=True,
            name=f"BrowserWorker-{job_id}",
        )
        thread.start()
        return job

    def _run_job_worker(
        self,
        job: BrowserJob,
        callback: Callable[[BrowserJob], None] | None = None,
    ) -> None:
        """Background thread executing Playwright Chromium automation."""
        acquired = self._semaphore.acquire(timeout=60)
        if not acquired:
            job.state = "FAILED"
            job.message = "Batas konkurensi browser tercapai. Coba beberapa saat lagi."
            self._save_job(job)
            return

        try:
            # Step 1: FETCHING
            job.state = "FETCHING"
            job.progress_pct = 20
            job.message = f"Membuka halaman laporan resmi di {job.target_url}..."
            self._save_job(job)

            dest_dir = self.downloads_dir / job.symbol
            dest_dir.mkdir(parents=True, exist_ok=True)

            from playwright.sync_api import sync_playwright

            with sync_playwright() as p:
                browser = p.chromium.launch(
                    headless=True,
                    args=["--no-sandbox", "--disable-dev-shm-usage", "--disable-gpu"],
                )
                context = browser.new_context(
                    user_agent="OpenBagus-FinancialResearch/1.0 (Headless Browser Assistant)",
                    accept_downloads=True,
                )
                page = context.new_page()
                page.set_default_timeout(30000)

                try:
                    logger.info("Browser navigating to %s", job.target_url)
                    page.goto(job.target_url, wait_until="domcontentloaded")
                    time.sleep(2.0)  # Allow initial JS hydration

                    # Locate downloadable reports (.pdf, .xlsx, .zip, .xbrl)
                    download_links = page.locator("a[href$='.pdf'], a[href$='.xlsx'], a[href$='.zip'], a[href$='.xbrl']").all()

                    found_files: list[str] = []
                    # Also look for links with text containing 'laporan' or 'financial'
                    if not download_links:
                        download_links = page.locator("a:has-text('Financial'), a:has-text('Laporan'), a:has-text('Keuangan')").all()

                    job.progress_pct = 40
                    job.message = f"Menemukan {len(download_links)} tautan laporan potensial. Memulai unduhan..."
                    self._save_job(job)

                    # Extract file metadata and download first available statement
                    for link in download_links[:3]:
                        href = link.get_attribute("href")
                        if not href:
                            continue
                        text = link.inner_text().strip()
                        # If link is direct download
                        if re.search(r"\.(pdf|xlsx|zip|xbrl)$", href, re.IGNORECASE):
                            try:
                                with page.expect_download(timeout=15000) as download_info:
                                    link.click()
                                download = download_info.value
                                safe_name = Path(download.suggested_filename).name
                                safe_name = re.sub(r"[^\w\.\-]", "_", safe_name)
                                target_path = (dest_dir / safe_name).resolve()
                                # Guard against path traversal
                                if dest_dir.resolve() not in target_path.parents and target_path.parent != dest_dir.resolve():
                                    logger.warning("Path traversal attempt detected: %s", download.suggested_filename)
                                    continue
                                download.save_as(str(target_path))
                                if target_path.exists() and target_path.stat().st_size > 50 * 1024 * 1024:
                                    logger.warning("File exceeds 50MB limit, deleting: %s", target_path)
                                    target_path.unlink(missing_ok=True)
                                    continue
                                found_files.append(str(target_path))
                                logger.info("Downloaded statement: %s", target_path)
                            except Exception as dl_err:
                                logger.debug("Direct click download fallback: %s", dl_err)

                    browser.close()

                    if found_files:
                        job.downloaded_files = found_files
                        # Step 2: PARSING
                        job.state = "PARSING"
                        job.progress_pct = 60
                        job.message = f"Mem-parsing berkas dokumen yang diunduh ({len(found_files)} berkas)..."
                        self._save_job(job)

                        parsed_stmt = None
                        parse_error = None
                        for file_str in found_files:
                            f_path = Path(file_str)
                            if f_path.exists() and f_path.stat().st_size > 50 * 1024 * 1024:
                                logger.warning("Skipping oversized file > 50MB: %s", f_path)
                                continue

                            ext = f_path.suffix.lower()
                            try:
                                if ext in {".zip", ".xbrl", ".xml"}:
                                    from openbagus.domains.equities.xbrl import IdxXbrlParser
                                    parser = IdxXbrlParser()
                                    parsed_stmt = parser.parse_file(f_path, ticker=job.symbol)
                                elif ext == ".xlsx":
                                    from openbagus.domains.equities.parsers.xlsx_parser import IdxXlsxParser
                                    parser = IdxXlsxParser()
                                    parsed_stmt = parser.parse_file(f_path, ticker=job.symbol)
                                elif ext == ".pdf":
                                    from openbagus.domains.equities.parsers.pdf_parser import IdxPdfParser
                                    parser = IdxPdfParser()
                                    parsed_stmt = parser.parse_file(f_path, ticker=job.symbol)

                                if parsed_stmt is not None:
                                    break
                            except Exception as p_err:
                                logger.warning("Failed parsing %s: %s", f_path, p_err)
                                parse_error = str(p_err)

                        if parsed_stmt is not None:
                            # Step 3: VALIDATING
                            job.state = "VALIDATING"
                            job.progress_pct = 75
                            job.message = "Memvalidasi invarian akuntansi neraca dan laba rugi..."
                            self._save_job(job)

                            parsed_stmt.validate_accounting_relationships()

                            # Persistence: Save statement and granular facts DB
                            from openbagus.domains.equities.storage import FinancialStatementStorage
                            storage = FinancialStatementStorage(self.root)
                            storage.store_statement(parsed_stmt)

                            try:
                                from openbagus.domains.equities.facts_db import FinancialFactsDatabase
                                facts_db = FinancialFactsDatabase(root=self.root)
                                fy_int = int(parsed_stmt.period[:4]) if (parsed_stmt.period and parsed_stmt.period[:4].isdigit()) else None
                                facts_db.record_filing(
                                    symbol=parsed_stmt.symbol,
                                    exchange="IDX",
                                    filing_type=parsed_stmt.period_type,
                                    period=parsed_stmt.period,
                                    fiscal_year=fy_int,
                                    period_end_date=parsed_stmt.period_end_date,
                                    filing_date=parsed_stmt.filing_date,
                                    source_provider="BROWSER_ACQUISITION",
                                    source_url=job.target_url,
                                    local_path=found_files[0],
                                )
                            except Exception as facts_err:
                                logger.debug("Facts database index notice: %s", facts_err)

                            # Step 4: CALCULATING
                            job.state = "CALCULATING"
                            job.progress_pct = 90
                            job.message = "Menghitung rasio fundamental dan model valuasi..."
                            self._save_job(job)

                            from openbagus.domains.equities.valuation import calculate_valuation_multiples
                            stmt_dict = parsed_stmt.to_dict()
                            job.parsed_statement = stmt_dict
                            calculate_valuation_multiples(
                                statement=stmt_dict,
                                price=None,
                                shares_outstanding=parsed_stmt.shares_outstanding,
                                sector="",
                            )

                            # Step 5: READY
                            job.state = "READY"
                            job.progress_pct = 100
                            job.message = f"Dokumen berhasil diunduh, divalidasi, dan dihitung: {Path(found_files[0]).name}"
                        else:
                            job.state = "PARTIAL_DATA"
                            job.progress_pct = 60
                            job.message = f"Berkas berhasil diunduh namun belum dapat diekstrak otomatis: {parse_error or 'Format dokumen belum didukung'}"
                    else:
                        job.state = "PARTIAL_DATA"
                        job.progress_pct = 50
                        job.message = "Halaman berhasil dibuka, namun tidak ditemukan tautan berkas langsung."

                    self._save_job(job)

                except Exception as page_exc:
                    browser.close()
                    raise page_exc

        except Exception as exc:
            logger.error("Browser job %s failed: %s", job.job_id, exc, exc_info=True)
            job.state = "FAILED"
            job.error = str(exc)
            job.message = f"Pengambilan browser gagal: {exc}"
            self._save_job(job)
        finally:
            self._semaphore.release()
            if callback:
                try:
                    callback(job)
                except Exception:
                    pass
