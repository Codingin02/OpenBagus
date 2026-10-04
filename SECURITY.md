# OpenBagus Security Policy

OpenBagus is a local, read-only quantitative research terminal. It enforces strict network boundaries, outbound host allowlisting, TLS certificate validation, and local-only secret handling.

---

## 1. Outbound Network Policy

OpenBagus only connects outbound via standard HTTPS (port 443) to known, public market data endpoints. It never opens inbound server ports and never executes remote code.

### Expected Outbound Domains

| Domain | Purpose | Access Type |
| --- | --- | --- |
| `data-api.binance.vision` | Spot ticker, candlestick history, order book depth, public trade flow | Zero-Key Public |
| `api.gateio.ws` | Spot ticker, order book, perpetual futures mark price, funding rates | Zero-Key Public |
| `api.coingecko.com` / `www.coingecko.com` | Public quote discovery, fallback spot price, derivatives list | Zero-Key Public |
| `api.geckoterminal.com` | DEX pool search, on-chain liquidity reserves, 24h DEX volume | Zero-Key Public |
| `api.coinlore.net` | Global cryptocurrency metadata & asset discovery | Zero-Key Public |
| `api.alternative.me` | Crypto Fear & Greed market sentiment index | Zero-Key Public |
| `stablecoins.llama.fi` | Global stablecoin market cap and DeFi TVL aggregate metrics | Zero-Key Public |
| `www.okx.com` | Optional public spot ticker & funding fallback | Zero-Key Public |
| `api.bybit.com` | Optional public spot ticker fallback | Zero-Key Public |
| `api.kucoin.com` / `api-futures.kucoin.com` | Optional public spot ticker fallback | Zero-Key Public |
| `api.kraken.com` | Optional public spot ticker fallback | Zero-Key Public |
| `api.stlouisfed.org` / `fred.stlouisfed.org` | Macroeconomic series (FRED) | Optional Keyed |
| `pro-api.coinmarketcap.com` | Specialized cryptocurrency metadata | Optional Keyed |
| `min-api.cryptocompare.com` | Redundant price reference | Optional Keyed |
| `api.coinalyze.net` | Futures open interest metrics | Optional Keyed |
| `www.alphavantage.co` | Financial market indicators | Optional Keyed |

---

## 2. Antivirus & Firewall Compatibility

OpenBagus **never** requires users to disable antivirus, Windows Defender, McAfee, or firewall protection.

- Connections to public APIs (such as `api.gateio.ws` or `data-api.binance.vision`) are normal Zero-Key public market feeds.
- If a local firewall, antivirus filter, or ISP blocks a specific provider, OpenBagus marks that provider as `BLOCKED` or `UNREACHABLE` and automatically falls back to alternative reachable providers.
- Terminal sessions continue uninterrupted without crashes or scary tracebacks.

---

## 3. Strict TLS & Host Allowlist

- **TLS Verification**: All outbound traffic strictly uses verified TLS (`ssl.create_default_context()`) with mandatory certificate and hostname verification. Disabling certificate verification (`CERT_NONE`, unverified contexts) is strictly forbidden in production.
- **Host Allowlist**: Requests are validated against `ALLOWED_PROVIDER_HOSTS`. Any attempt to fetch from private IP addresses (`127.0.0.1`, RFC1918), non-HTTPS schemes (`http://`, `file://`), or unauthorized domains is immediately rejected.
- **Redirect Protection**: Cross-host redirects to unapproved domains or insecure schemes are strictly blocked.
- **Bounded Responses**: Responses are bounded to 5 MB max to protect against memory exhaustion.

---

## 4. Secret & Credential Handling

- **Zero-Key Core**: Core crypto analysis functions fully without any private API keys.
- **Local-Only Storage**: Optional API keys live exclusively in your local `.env` file, which is excluded from Git via `.gitignore` and never committed or uploaded.
- **Secret Sanitization**: OpenBagus never logs private API keys, authorization tokens, or query strings containing credentials. All credential query parameters are masked (e.g. `api_key=***`).
- **Pre-Push Safety Verification**: Contributors and users can verify that no local configuration, `.env` file, databases, or secrets are staged or tracked by running:
  ```powershell
  python scripts/check_repo_safety.py
  ```


---

## 5. What OpenBagus Never Does

- **No Remote Code Execution**: API responses are parsed strictly as untrusted JSON data. OpenBagus never calls `eval()`, `exec()`, or executes downloaded scripts or binaries.
- **No Private Keys or Wallets**: OpenBagus has no wallet integrations, does not manage private keys, and cannot sign or broadcast transactions.
- **No Telemetry or User Tracking**: OpenBagus does not send telemetry, analytics, user queries, or prompt logs to external servers.

---

## 6. Reporting a Vulnerability

If you discover a potential security vulnerability in OpenBagus, please report it privately:

- **Email**: `codingindong02@gmail.com`
- **Subject**: `[SECURITY] OpenBagus Vulnerability Report`

Please include a description of the issue and reproduction steps. We will review and address valid reports promptly.
