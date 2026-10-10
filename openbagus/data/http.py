"""OpenBagus Centralized Secure Network Client and Host Policy."""

from __future__ import annotations

import json
import math
import re
import socket
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

DEFAULT_USER_AGENT = "OpenBagus-Research"
DEFAULT_TIMEOUT_SECONDS = 3.5
DEFAULT_MAX_RESPONSE_BYTES = 5 * 1024 * 1024

ALLOWED_PROVIDER_HOSTS: frozenset[str] = frozenset({
    # Zero-Key Market & Derivatives Providers
    "data-api.binance.vision",
    "api.gateio.ws",
    "api.coingecko.com",
    "www.coingecko.com",
    "api.geckoterminal.com",
    "api.coinlore.net",
    "api.alternative.me",
    "stablecoins.llama.fi",
    "www.okx.com",
    "api.bybit.com",
    "api.kucoin.com",
    "api-futures.kucoin.com",
    "api.kraken.com",
    "query1.finance.yahoo.com",
    # Optional Keyed Providers
    "api.stlouisfed.org",
    "fred.stlouisfed.org",
    "pro-api.coinmarketcap.com",
    "min-api.cryptocompare.com",
    "api.coinalyze.net",
    "www.alphavantage.co",
    # FX & Reference Providers
    "api.frankfurter.dev",
    # Macro & Public Feeds
    "www.coindesk.com",
    "cointelegraph.com",
    "decrypt.co",
    "theblock.co",
    "apnews.com",
    "www.cnbc.com",
    "www.reuters.com",
    "www.federalreserve.gov",
    "www.imf.org",
    "www.worldbank.org",
})

SECRET_QUERY_PATTERNS = [
    re.compile(r"((?:api[_-]?key|apikey|key|secret|token|auth)=)[^&]+", re.IGNORECASE),
]


def sanitize_url(url: str) -> str:
    sanitized = url
    for pat in SECRET_QUERY_PATTERNS:
        sanitized = pat.sub(r"\1***", sanitized)
    return sanitized


def validate_finite_number(
    val: Any,
    min_val: float | None = None,
    max_val: float | None = None,
) -> float | None:
    if val is None:
        return None
    try:
        f = float(val)
        if math.isnan(f) or math.isinf(f):
            return None
        if min_val is not None and f < min_val:
            return None
        if max_val is not None and f > max_val:
            return None
        return f
    except (ValueError, TypeError):
        return None


class DisallowedHostError(ValueError):
    pass


class InsecureSchemeError(ValueError):
    pass


class ResponseSizeExceededError(ValueError):
    pass


class SafeRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(
        self,
        req: urllib.request.Request,
        fp: Any,
        code: int,
        msg: str,
        headers: Any,
        newurl: str,
    ) -> urllib.request.Request | None:
        parsed = urllib.parse.urlparse(newurl)
        if parsed.scheme.lower() != "https":
            return None
        host = (parsed.hostname or "").lower()
        if host not in ALLOWED_PROVIDER_HOSTS:
            return None
        return super().redirect_request(req, fp, code, msg, headers, newurl)


class SecureHttpClient:
    def __init__(
        self,
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
        max_response_bytes: int = DEFAULT_MAX_RESPONSE_BYTES,
        user_agent: str = DEFAULT_USER_AGENT,
    ) -> None:
        self.timeout = timeout
        self.max_response_bytes = max_response_bytes
        self.user_agent = user_agent
        self.ssl_context = ssl.create_default_context()
        self.opener = urllib.request.build_opener(
            urllib.request.HTTPSHandler(context=self.ssl_context),
            SafeRedirectHandler(),
        )

    def validate_target_url(self, url: str) -> urllib.parse.ParseResult:
        parsed = urllib.parse.urlparse(url)
        if parsed.scheme.lower() != "https":
            raise InsecureSchemeError(f"Rejected non-HTTPS scheme: {parsed.scheme}")
        host = (parsed.hostname or "").lower()
        if not host or host not in ALLOWED_PROVIDER_HOSTS:
            raise DisallowedHostError(f"Host '{host}' is not in allowed provider list")
        return parsed

    def fetch_with_metadata(
        self,
        url: str,
        headers: dict[str, str] | None = None,
        timeout: float | None = None,
        max_bytes: int | None = None,
    ) -> tuple[str | None, str, float, dict[str, str]]:
        t0 = time.time()
        try:
            self.validate_target_url(url)
        except (InsecureSchemeError, DisallowedHostError):
            return None, "DISALLOWED_HOST", round((time.time() - t0) * 1000, 1), {}

        req_headers = {
            "User-Agent": self.user_agent,
            "Accept": "application/json, */*",
        }
        if headers:
            req_headers.update(headers)

        req = urllib.request.Request(url, headers=req_headers)
        call_timeout = timeout or self.timeout
        call_limit = max_bytes or self.max_response_bytes

        try:
            with self.opener.open(req, timeout=call_timeout) as resp:
                resp_headers = {k: v for k, v in resp.headers.items()}
                chunks: list[bytes] = []
                total = 0
                while True:
                    chunk = resp.read(65536)
                    if not chunk:
                        break
                    total += len(chunk)
                    if total > call_limit:
                        return None, "PAYLOAD_TOO_LARGE", round((time.time() - t0) * 1000, 1), resp_headers
                    chunks.append(chunk)

                raw = b"".join(chunks).decode("utf-8", errors="replace")
                elapsed_ms = round((time.time() - t0) * 1000, 1)
                return raw, "REACHABLE", elapsed_ms, resp_headers

        except ssl.SSLError:
            return None, "SECURITY_REJECTED", round((time.time() - t0) * 1000, 1), {}
        except (TimeoutError, socket.timeout):
            return None, "TIMEOUT", round((time.time() - t0) * 1000, 1), {}
        except urllib.error.HTTPError as exc:
            elapsed_ms = round((time.time() - t0) * 1000, 1)
            err_headers = {k: v for k, v in exc.headers.items()} if exc.headers else {}
            if exc.code == 304:
                return None, "NOT_MODIFIED", elapsed_ms, err_headers
            if exc.code == 429:
                return None, "RATE_LIMITED", elapsed_ms, err_headers
            if exc.code in (401, 403):
                return None, "AUTHENTICATION_FAILED", elapsed_ms, err_headers
            return None, f"HTTP_{exc.code}", elapsed_ms, err_headers
        except urllib.error.URLError as exc:
            elapsed_ms = round((time.time() - t0) * 1000, 1)
            r_str = str(exc.reason).lower()
            if "timeout" in r_str or "timed out" in r_str:
                return None, "TIMEOUT", elapsed_ms, {}
            if any(k in r_str for k in ("connection reset", "refused", "10054", "10061", "10013", "forbidden")):
                return None, "BLOCKED", elapsed_ms, {}
            return None, "UNREACHABLE", elapsed_ms, {}
        except Exception:
            return None, "UNREACHABLE", round((time.time() - t0) * 1000, 1), {}

    def fetch_raw(
        self,
        url: str,
        headers: dict[str, str] | None = None,
        timeout: float | None = None,
        max_bytes: int | None = None,
    ) -> tuple[str | None, str, float]:
        raw, status, elapsed_ms, _ = self.fetch_with_metadata(
            url, headers=headers, timeout=timeout, max_bytes=max_bytes
        )
        return raw, status, elapsed_ms

    def get_json(
        self,
        url: str,
        headers: dict[str, str] | None = None,
        timeout: float | None = None,
    ) -> Any | None:
        raw, status, _ = self.fetch_raw(url, headers=headers, timeout=timeout)
        if not raw or status != "REACHABLE":
            return None
        try:
            return json.loads(raw)
        except (json.JSONDecodeError, ValueError):
            return None
