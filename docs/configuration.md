# Configuration

OpenBagus resolves configuration in the following order:

1. Process environment variables (`os.environ`)
2. `config/openbagus_runtime_local.env`
3. `.env`
4. `.env.local`
5. Ignored local JSON files (`config/openbagus_runtime_local.json`, etc.)

Copy `.env.example` to `.env` (or `config/openbagus_runtime_local.env.example` to `config/openbagus_runtime_local.env`) to configure local overrides. Local override files and private secrets are ignored by Git.

## Requirements Breakdown

### Required for Basic CLI
- Python 3.11 or newer
- Outbound network connectivity for public market APIs
- **Zero API keys or credentials required** for core crypto research.

### Optional
- **FRED API Key (`FRED_API_KEY`)**: Enables official Federal Reserve Economic Data series. If omitted, Yahoo Finance public proxies provide macro context.
- **SMTP Email (`OPENBAGUS_EMAIL_*`)**: Enables outbound email delivery. If omitted, reports are saved locally to disk as text, HTML, and EML files without error. See [email.md](email.md).
- **LLM Critic (`OPENROUTER_API_KEY`, `OPENBAGUS_LLM_JURY_ENABLED=true`)**: Optional qualitative narrative summarizer/critic. Numerical scores and risk metrics remain strictly deterministic in Python.

### Disabled Subsystems
- **Equities (`idx-daily`)**: Disabled. OpenBagus active domain is crypto.
- **WhatsApp / OpenClaw**: Disabled.
- **Live Trading**: Not implemented. OpenBagus is strictly research-only and has no broker or exchange order execution capabilities.

## Data Providers Summary

| Provider | Credential | Status | Role |
| --- | --- | --- | --- |
| Binance | None | Active | Primary crypto price and volume data |
| CoinGecko | None | Active | Fallback crypto market data |
| Yahoo Finance | None | Active | Public macro proxy chart data |
| DefiLlama | None | Active | Stablecoin liquidity metrics |
| FRED | `FRED_API_KEY` | Optional | Official US macro interest and inflation series |

Provider failures or data gaps remain explicit; OpenBagus never fabricates missing market data.

## Configuration Inspection

Check configuration and provider readiness at any time without exposing sensitive secrets:

```powershell
openbagus doctor
openbagus config
```

These commands display only status indicators (`configured`, `not configured`, `optional`, or `disabled`). Secret values, prefixes, and lengths are never displayed.
