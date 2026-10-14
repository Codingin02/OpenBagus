#!/usr/bin/env python3
"""Probe official IDX financial report and filing endpoints.

Tests authentic endpoints for BBCA, RATU, TLKM, and DATA across:
1. https://www.idx.co.id
2. https://idx.id
3. Primary API endpoints
Records exact HTTP status, response headers, access restrictions, and payload.
Outputs structured findings for docs/data/AUTHENTIC_FILINGS_ACCEPTANCE.md.
"""

import json
import logging
import ssl
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("idx_probe")

TICKERS = ["BBCA", "RATU", "TLKM", "DATA"]

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Accept": "application/json, text/html, */*",
    "Accept-Language": "id-ID,id;q=0.9,en-US;q=0.8,en;q=0.7",
}

ctx = ssl.create_default_context()


def probe_endpoint(name: str, url: str) -> dict:
    req = urllib.request.Request(url, headers=HEADERS)
    ts = datetime.now(timezone.utc).isoformat()
    try:
        with urllib.request.urlopen(req, timeout=12, context=ctx) as resp:
            body = resp.read()
            ct = resp.headers.get("Content-Type", "")
            server = resp.headers.get("Server", "")
            cf_ray = resp.headers.get("CF-RAY", "")
            return {
                "name": name,
                "url": url,
                "timestamp": ts,
                "http_status": resp.status,
                "server": server,
                "cf_ray": cf_ray,
                "content_type": ct,
                "size_bytes": len(body),
                "is_json": "application/json" in ct,
                "error": None,
                "body_preview": body[:500].decode("utf-8", errors="replace"),
            }
    except urllib.error.HTTPError as e:
        server = e.headers.get("Server", "")
        cf_ray = e.headers.get("CF-RAY", "")
        body = e.read() if hasattr(e, "read") else b""
        return {
            "name": name,
            "url": url,
            "timestamp": ts,
            "http_status": e.code,
            "reason": e.reason,
            "server": server,
            "cf_ray": cf_ray,
            "content_type": e.headers.get("Content-Type", ""),
            "size_bytes": len(body),
            "is_json": False,
            "error": f"HTTPError {e.code}: {e.reason}",
            "body_preview": body[:300].decode("utf-8", errors="replace"),
        }
    except Exception as ex:
        return {
            "name": name,
            "url": url,
            "timestamp": ts,
            "http_status": None,
            "error": f"{type(ex).__name__}: {ex}",
            "server": "",
            "cf_ray": "",
            "content_type": "",
            "size_bytes": 0,
            "is_json": False,
            "body_preview": "",
        }


def main():
    results = []

    # 1. Official web pages
    web_targets = [
        ("IDX www Web Laporan Keuangan", "https://www.idx.co.id/id/perusahaan-tercatat/laporan-keuangan-dan-tahunan"),
        ("IDX short Web Laporan Keuangan", "https://idx.id/id/perusahaan-tercatat/laporan-keuangan-dan-tahunan"),
        ("IDX www XBRL", "https://www.idx.co.id/id/perusahaan-tercatat/xbrl"),
        ("IDX short XBRL", "https://idx.id/id/perusahaan-tercatat/xbrl"),
    ]
    for name, url in web_targets:
        logger.info("Probing %s...", name)
        results.append(probe_endpoint(name, url))

    # 2. Per-ticker API probes
    for sym in TICKERS:
        for yr in ["2023", "2024"]:
            for host in ["idx.id", "www.idx.co.id"]:
                url = f"https://{host}/primary/ListedCompany/GetFinancialReport?indexFrom=1&pageSize=10&year={yr}&reportType=rdf&kodeEmiten={sym}"
                name = f"IDX API LK {sym} {yr} ({host})"
                logger.info("Probing %s...", name)
                results.append(probe_endpoint(name, url))

    out_file = Path("data/idx_probe_audit.json")
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)
    logger.info("Probe completed. Saved %d results to %s", len(results), out_file)


if __name__ == "__main__":
    main()
