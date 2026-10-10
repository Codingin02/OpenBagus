# Contributing

Use a reproducible issue and regression test before changing behavior. Keep one canonical QuantEngine and language contract. Never change a decision or geometry to satisfy a narrative. New performance claims need a separate out-of-sample protocol including costs, funding, slippage and overfitting controls.

For feedback, review `/improve export`, remove personal details, and manually prepare an issue with expected behavior, actual behavior, version and a minimal sanitized reproduction. Do not publish raw prompts, API keys, SMTP/WhatsApp credentials, Puter tokens, recipients, wallets or local files. Security reports belong in the private channel in [SECURITY.md](SECURITY.md).

Run targeted tests during development, then canonical checks:

```powershell
python -m unittest discover -s tests
python scripts/check_repo_safety.py
python scripts/validate_openbagus_runtime.py
python -m pip check
git diff --check
```

Inspect staged files explicitly. User data, runtime reports, models and binaries stay outside Git. There is no automatic feedback submission or source modification.
