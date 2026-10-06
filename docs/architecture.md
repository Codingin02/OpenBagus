# Architecture

OpenBagus is a modular, domain-neutral research platform. Crypto is the only active domain in the current release.

## Runtime Flow

```text
public data providers
  -> ingestion and normalization
  -> freshness and source health
  -> quantitative analysis
  -> risk and macro intelligence
  -> reports and local storage
  -> optional SMTP email or official Meta WhatsApp Cloud API
```

Python is the numerical decision core. Optional LLM processing is limited to criticism, summarization, contradiction checks, and report prose.

## Packages

- `openbagus.core`: contracts, environment loading, generic guards, and market structure.
- `openbagus.domains.crypto`: crypto microstructure and order-flow logic.
- `openbagus.data`: public provider ingestion and optional DuckDB persistence.
- `openbagus.analysis`: quantitative synthesis and data-quality handling.
- `openbagus.risk`: portfolio and risk metrics.
- `openbagus.intelligence`: macro, news, sentiment, and optional local Qwen3-4B language context served on loopback by llama.cpp.
- `openbagus.reporting`: briefs, email content, PDF/HTML output, and dashboard rendering.
- `openbagus.delivery`: safety scanning, local outbox, MIME, guarded SMTP, and official WhatsApp Cloud API transport.
- `openbagus.storage`: historical and spreadsheet exports.
- `openbagus.runtime`: pipeline orchestration and scheduling policy.

`openbagus.cli` is the canonical interface. `python -m openbagus`, the installed `openbagus` command, and the compatibility script all delegate to it.

## Supported Boundaries

- CLI is mandatory; email and WhatsApp delivery are optional and locally disabled by default.
- Equities are disabled and guarded.
- The default delivery mode is `NO_SEND_FILE_ONLY`.
- No broker order, exchange order, wallet transaction, or fund transfer is implemented.
