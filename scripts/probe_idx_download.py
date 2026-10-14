#!/usr/bin/env python3
"""Probe authentic IDX attachment download URLs.

Tests downloading real financial report attachments (xlsx, zip, pdf) for:
- BBCA (TW1 2023)
- TLKM (TW1 2023)
- DATA (TW1 2024)
"""

import hashlib
import json
import logging
import ssl
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("download_probe")

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Referer": "https://idx.id/id/perusahaan-tercatat/laporan-keuangan-dan-tahunan",
}
ctx = ssl.create_default_context()

# Test candidate download patterns
# 1. https://idx.id/files/ListedCompany/GetFinancialReport/File_ID/File_Name
# 2. https://idx.id/primary/ListedCompany/DownloadFinancialReport?fileId=...
# 3. https://www.idx.co.id/Portals/0/StaticData/ListedCompanies/PerformanceSummary/...
# 4. Direct StaticData or attachment endpoints

def probe_download_candidates():
    # Let's first test what GetFinancialReport returns for BBCA TW1 2023
    api_url = "https://idx.id/primary/ListedCompany/GetFinancialReport?indexFrom=1&pageSize=10&year=2023&reportType=rdf&kodeEmiten=BBCA"
    req = urllib.request.Request(api_url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=10, context=ctx) as resp:
        data = json.loads(resp.read().decode("utf-8"))

    results = data.get("Results", [])
    if not results:
        logger.error("No results returned for BBCA 2023")
        return

    first_item = results[0]
    attachments = first_item.get("Attachments", [])
    logger.info("Found %d attachments for %s", len(attachments), first_item.get("NamaEmiten"))

    target_att = next((a for a in attachments if a.get("File_Name", "").endswith(".xlsx")), attachments[0])
    file_id = target_att.get("File_ID")
    file_name = target_att.get("File_Name")
    file_size = target_att.get("File_Size")
    logger.info("Testing download for attachment: %s (ID: %s, Reported size: %s)", file_name, file_id, file_size)

    candidates = [
        f"https://idx.id/primary/ListedCompany/DownloadFinancialReport?fileId={file_id}",
        f"https://idx.id/primary/ListedCompany/DownloadFile?fileId={file_id}",
        f"https://idx.id/files/ListedCompany/FinancialReport/{file_id}/{file_name}",
        f"https://idx.id/primary/ListedCompany/GetFinancialReportFile?fileId={file_id}",
        f"https://www.idx.co.id/primary/ListedCompany/DownloadFinancialReport?fileId={file_id}",
    ]

    outcomes = []
    for cand_url in candidates:
        logger.info("Testing URL: %s", cand_url)
        creq = urllib.request.Request(cand_url, headers=HEADERS)
        try:
            with urllib.request.urlopen(creq, timeout=10, context=ctx) as cresp:
                cdata = cresp.read()
                h = hashlib.sha256(cdata).hexdigest()
                ct = cresp.headers.get("Content-Type", "")
                logger.info("--> SUCCESS HTTP %d, Type: %s, Size: %d, SHA256: %s", cresp.status, ct, len(cdata), h)
                outcomes.append({
                    "url": cand_url,
                    "http_status": cresp.status,
                    "content_type": ct,
                    "downloaded_bytes": len(cdata),
                    "sha256": h,
                    "success": True,
                })
        except urllib.error.HTTPError as e:
            server = e.headers.get("Server", "")
            logger.info("--> HTTP %d: %s (Server: %s)", e.code, e.reason, server)
            outcomes.append({
                "url": cand_url,
                "http_status": e.code,
                "reason": e.reason,
                "server": server,
                "success": False,
            })
        except Exception as ex:
            logger.info("--> Failed: %s", ex)
            outcomes.append({
                "url": cand_url,
                "error": str(ex),
                "success": False,
            })

    out_file = Path("data/idx_download_probe.json")
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump({
            "attachment": target_att,
            "outcomes": outcomes,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }, f, indent=2)


if __name__ == "__main__":
    probe_download_candidates()
