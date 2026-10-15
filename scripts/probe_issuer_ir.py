#!/usr/bin/env python3
"""Probe official Issuer Investor Relations (IR) portals.

Targets:
- TLKM: https://www.telkom.co.id/sites/hubungan-investor/id_ID/page/laporan-1025
- BBCA: https://www.bca.co.id/id/tentang-bca/hubungan-investor/laporan-presentasi/laporan-keuangan
- RATU: https://rec.co.id/id/general-meeting-of-shareholders
"""

import json
import logging
import re
import ssl
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("probe_ir")

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "id-ID,id;q=0.9,en-US;q=0.8,en;q=0.7",
}

ctx = ssl.create_default_context()

TARGETS = [
    ("TLKM", "https://www.telkom.co.id/sites/hubungan-investor/id_ID/page/laporan-1025"),
    ("BBCA", "https://www.bca.co.id/id/tentang-bca/hubungan-investor/laporan-presentasi/laporan-keuangan"),
    ("RATU", "https://rec.co.id/id/general-meeting-of-shareholders"),
]


def probe_ir():
    results = []
    for sym, url in TARGETS:
        logger.info("Probing %s IR: %s", sym, url)
        req = urllib.request.Request(url, headers=HEADERS)
        entry = {
            "symbol": sym,
            "url": url,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "http_status": None,
            "content_type": None,
            "size_bytes": 0,
            "links": [],
            "error": None,
        }
        try:
            with urllib.request.urlopen(req, timeout=12, context=ctx) as resp:
                entry["http_status"] = resp.status
                entry["content_type"] = resp.headers.get("Content-Type", "")
                html = resp.read().decode("utf-8", errors="replace")
                entry["size_bytes"] = len(html)

                # Find document links
                raw_links = re.findall(r'href=["\']([^"\']+\.(?:pdf|xlsx|zip))["\']', html, re.IGNORECASE)
                # Normalize links
                clean_links = []
                for l in raw_links:
                    full_l = urllib.parse.urljoin(url, l)
                    clean_links.append(full_l)
                entry["links"] = list(dict.fromkeys(clean_links))
                logger.info("%s: HTTP %d, Size: %d, Found %d document links", sym, resp.status, len(html), len(clean_links))
                for cl in clean_links[:5]:
                    logger.info("  Link: %s", cl)
        except urllib.error.HTTPError as e:
            entry["http_status"] = e.code
            entry["error"] = f"HTTPError {e.code}: {e.reason}"
            logger.warning("%s: HTTPError %d: %s", sym, e.code, e.reason)
        except Exception as ex:
            entry["error"] = f"{type(ex).__name__}: {ex}"
            logger.warning("%s: Exception %s", sym, ex)

        results.append(entry)

    out_file = Path("data/issuer_ir_probe.json")
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2)
    logger.info("Saved probe results to %s", out_file)


if __name__ == "__main__":
    probe_ir()
