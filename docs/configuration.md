# Configuration

OpenBagus loads values in this order:

1. Process environment
2. `config/openbagus_runtime_local.env`
3. `.env`
4. `.env.local`
5. Ignored local JSON configuration

Use `config/openbagus_runtime_local.env.example` as the local template. Local files and secrets are ignored by Git.

## Data Providers

| Provider | Credential | Status |
| --- | --- | --- |
| Binance public market data | None | Active primary crypto source |
| CoinGecko public API | None | Active crypto fallback |
| Yahoo Finance public chart | None | Active macro proxy |
| DefiLlama public API | None | Active stablecoin liquidity source |
| FRED | `FRED_API_KEY` | Optional official US macro source |

No key is required for the default public-data pipeline. Provider failures remain explicit as source gaps or degraded data; OpenBagus does not fabricate replacements.

## Optional LLM Critic

`OPENROUTER_API_KEY` and `OPENBAGUS_LLM_JURY_ENABLED=true` enable the existing optional critic/summarizer. It does not own quantitative scores or trading decisions.

## Email

Email variables are documented in [email.md](email.md). SMTP is optional and does not affect the health of the core CLI.

## Verification

```powershell
openbagus doctor
openbagus config
```

These commands report only `configured`, `not configured`, `optional`, or `disabled`; secret values and prefixes are not displayed.
