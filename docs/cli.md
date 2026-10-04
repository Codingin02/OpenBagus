# CLI Reference

OpenBagus exposes one unified CLI implementation through both `openbagus` and `python -m openbagus`.

## Prompt-First Interactive Research Terminal

Run `openbagus` in an interactive terminal to enter the coin-centric research shell.

Users can directly enter natural coin queries without needing commands:

| Query Example | Quantitative Research Intent |
| --- | --- |
| `ETH` or `SOL` | Comprehensive market snapshot, levels, pivots, and provider evidence |
| `open position ARB` | Trade setup view: directional bias, candidate zone, invalidation level, scenarios |
| `risk DOGE` | Risk profile: volatility regime, drawdown, distance to invalidation, liquidity proxy |
| `support resistance AVAX` | Market structure map: Floor Trader Pivots (P, R1/R2, S1/S2) |
| `BTC vs ETH` | Side-by-side comparative quantitative snapshot |

### Shell Slash Commands

| Command | Purpose |
| --- | --- |
| `/help` or `help` | Show supported slash commands and query patterns |
| `/status` or `status` | Show runtime status, active domains, provider counts, and target |
| `/providers` | View all public providers and API keys coverage status |
| `/providers --check` | Run live reachability and latency ping tests on public providers |
| `/assets [query]` | Search dynamic asset universe or filter by sector (e.g. `/assets defi`) |
| `/categories` | List all taxonomy sectors and asset counts (DeFi, Layer 1, AI, Memecoin, etc.) |
| `/doctor [network]` | Run environment diagnostics; add `network` for live provider latency checks |
| `/setup` | Launch interactive wizard to configure API keys, email, and intent models |
| `/config` | Show safe redacted configuration status |
| `/email draft\|check\|send` | Local delivery artifact generation or safe check |
| `/crypto` | Run standard core crypto pipeline (BTC/USD, ETH/USD, SOL/USD) |
| `/version` | Show OpenBagus package version |
| `/clear` | Clear the terminal screen |
| `/exit` or `exit` | Exit the shell safely |

Set `NO_COLOR=1` for plain monochrome output.

## Direct Command-Line Execution

Run ad-hoc queries directly from the command line:

```powershell
# Direct coin research
openbagus ETH
openbagus "open position ETH"
openbagus "risk DOGE"
openbagus "support resistance AVAX"
openbagus "BTC vs ETH"

# Catalog & discovery
openbagus assets
openbagus assets defi
openbagus categories

# Diagnostics & providers
openbagus status
openbagus providers
openbagus doctor
openbagus doctor --network

# Pipeline & delivery
openbagus crypto-daily
openbagus manual-desk --query "OpenBagus review BTC ETH"
openbagus email --email-action draft
openbagus email --email-action check
```

`manual-desk` requires the exact trigger `OpenBagus`. The spaced form `Open Bagus` is invalid.

Successful operations return exit code `0`. Runtime failures return `1`; blocked or incomplete requested operations return `2`. Interactive errors do not terminate the shell.

## Disabled Commands

`idx-daily` remains available only as a compatibility guard and returns `EQUITY_DOMAIN_DISABLED`. WhatsApp and OpenClaw have no active CLI delivery command.
