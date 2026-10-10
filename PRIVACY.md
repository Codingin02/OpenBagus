# Privacy

OpenBagus has no telemetry backend. Session asset, language, timeframe, scenarios and recent turns stay in memory and are cleared on exit; this is context adaptation, not training. Public data providers receive market requests such as asset symbols, not the full conversation. Existing user-requested delivery sends report content to the configured recipient.

## Optional Cloud

Puter is OFF until you explicitly approve enablement and transmission in setup. Browser sign-in and a real authorized smoke response are required before activation. The bridge sends a bounded sanitized question and deterministic narrative facts, not raw provider responses, files, credentials or full history. Puter processes content under its [privacy policy](https://puter.com/privacy) and [user-pays terms](https://docs.puter.com/user-pays-model/); OpenBagus cannot control retention or guarantee free usage.

Settings, SDK and encrypted browser-auth token live under `%LOCALAPPDATA%\OpenBagus\cloud`, outside the repository. Windows DPAPI binds the token to the current Windows user. Authentication uses the official SDK's temporary callback listener. The child exits when login completes; do not expose the login callback port to untrusted networks. Runtime does not launch a new login automatically. Disable cloud through `/setup` by answering N. Delete `puter-auth.dpapi.txt` there to remove the stored token.

Cloud errors/quotas fall back to Qwen; local inference communicates only with the managed loopback server. Both paths treat generated language as untrusted and preserve Quant facts.

## Optional Feedback

Collection defaults to OFF and has its own setup consent. Only `/feedback <type> <explicit correction>` writes an entry: correction, category, asset/timeframe and recording time. Raw prompts, every turn, private files and credentials are not collected automatically.

Feedback lives under `%LOCALAPPDATA%\OpenBagus\feedback` (or `~/.openbagus/feedback` without LOCALAPPDATA). Sanitization removes recognized credential patterns, configured process secrets, recipients, private paths and common wallet identifiers. It is not a guarantee that arbitrary prose contains no personal information: review and redact before sharing.

`/improve status` shows collection status. `/improve off` stops future collection; `/improve clear` deletes entries and reviewed exports. `/improve export` displays content and requires approval to write a local export. External sharing is a separate manual decision; no background upload, public issue, Git commit, retraining or self-modification occurs.
