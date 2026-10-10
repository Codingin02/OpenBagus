# OpenBagus

A unified financial research CLI for cryptocurrency and Indonesian equities, with deterministic Python analysis and optional local or cloud language assistance. One installation and conversation; no market selector.

## Core Features

- Public spot/perpetual quotes, OHLCV, order books, trade flow, funding and basis; online asset and DEX-pool discovery.
- Indonesian equities, IDX-IC sector taxonomy, technical/fundamental analysis and macro/commodity context through verified, permitted local imports. Authorized automatic live IDX prices are not yet available.
- One QuantEngine owns decisions, structural entry/stop/target geometry and reward:risk. Missing or stale evidence blocks active setups.
- Asset/timeframe continuity, explicit research-context switching, comparisons and cached explanatory follow-ups in Indonesian or English.
- Optional confluence appears when material, not as a fixed indicator checklist.
- Local reports/dashboard and optional SMTP or official WhatsApp Cloud API delivery.

See [Crypto Capabilities](docs/CRYPTO_CAPABILITIES.md) for sources, formulas and limitations. Quality categories are not calibrated probabilities. No out-of-sample win rate or profitability is claimed.
See [Indonesian Equities](docs/INDONESIAN_EQUITIES_CAPABILITIES.md) for source rights, import formats, coverage and conditional trade scenarios. Foreign equities remain outside scope.

## Quick Start

Requires Python 3.11+. On Windows, run `setup.bat`; optional setup questions can all be declined. Core market research needs internet access but no provider API key or AI account.

```powershell
git clone https://github.com/Codingin02/openbagus.git
cd openbagus
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e .
.\.venv\Scripts\openbagus.exe doctor
.\.venv\Scripts\openbagus.exe
```

On Linux/macOS, use `.venv/bin/python` and `.venv/bin/openbagus`. Without a language model, deterministic routing and explanations remain available. Offline market data is a gap, not a live signal.

## Example Queries

```text
BTC H1 sekarang gimana?
Kalau open long BTC H1?
Kenapa belum long?
Kalau OI naik tapi funding negatif?
Kalau resistance tadi ditembus?
Jelaskan lebih sederhana.
Gunakan bahasa Indonesia.
BTC vs ETH
1 BTC berapa dolar?
1 USD berapa IDR?
/chart ETH
BBCA daily
ANTM pengaruh nikel bagaimana?
Banking Indonesia
IDX sektor energi
BTC vs BBCA
/chart BBCA
```

`/help`, `/assets`, `/categories`, `/status`, `/providers`, `/harness` and `/switch ETH` expose existing CLI functions. The manual trigger is exactly `OpenBagus`.

## Local / Cloud AI

Local inference uses **Qwen3-4B Q4_K_M**, one loopback llama.cpp server, CUDA when available and CPU fallback. Models/binaries stay outside Git. Setup provisions them only when requested.

Optional **Puter** uses the official Node.js SDK and browser login, not a manually pasted model API key. It requires Windows and Node.js 24+ for this bridge. `/setup` asks separately for cloud enablement and permission to transmit sanitized questions and Quant facts. The SDK is installed in local user data only after consent; activation requires a successful authorized smoke response. Allowances are limited and additional usage may incur charges. [Official Node guide](https://developer.puter.com/tutorials/puter-js-node-js/), [usage model](https://docs.puter.com/user-pays-model/).

Cloud errors/quota limits immediately fall back to local Qwen. Both backends use the same numeric/semantic guard, retry unsupported wording once, then use deterministic prose. Neither may change Quant decisions or levels.

## Optional Providers and Delivery

`/setup` configures optional providers and delivery locally. No SMTP, WhatsApp or optional API credentials are required for core research. `/email draft` stages a draft; `/send email` or `/send whatsapp` uses existing locally enabled transports and confirmation behavior. Sending is not enabled by adding an AI backend.

OpenBagus does not execute trades/payments, connect private trading APIs, or manage wallets. All setups are research views, not broker orders.

## Privacy & Security

Feedback is **OFF by default** and separate from cloud consent. After opting in through `/setup`, `/feedback intent <explicit correction>` records only sanitized corrections and minimal metadata locally. Types: `intent`, `interpretation`, `asset`, `provider`, `geometry`, `contradiction`, `suggestion`.

`/improve status`, `/improve off`, `/improve clear` and `/improve export` let you inspect, stop, delete or review a local export. Nothing is automatically submitted to GitHub or a telemetry service. Session context is ephemeral adaptation, not model training.

Read [Privacy](PRIVACY.md), [Security](SECURITY.md), and [Contributing](CONTRIBUTING.md). Secrets, models, reports, cache, feedback and chat history must not be committed.

## License

[Apache License 2.0](LICENSE). Copyright Ahmad Bagus Idkholus Surur. Third-party components retain their own licenses; model/runtime provisioning does not transfer ownership or guarantee freedom from legal disputes.
