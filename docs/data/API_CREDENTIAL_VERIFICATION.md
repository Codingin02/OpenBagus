# OPENBAGUS — API CREDENTIAL VERIFICATION & COST CONTROL

## 1. Zero-Leak Credential Security Model
1. **User-Scoped Storage:** Credentials are saved strictly under the user's home directory (`~/.openbagus/credentials.json`) with restricted OS permissions, NEVER in the project repository, git commits, or temporary files.
2. **Log Redaction:** All API keys (`sk-...`, `AIza...`) are stripped from log streams, terminal transcripts, and exception traces using `redact_secrets()`.
3. **Key Masking:** Diagnostic screens and CLI commands display only masked identifiers (`sk-...1234`, `AIza...bcde`).

---

## 2. Two-Level Verification Protocol

For each configured cloud provider (OpenAI, Gemini), OpenBagus enforces a strict 2-level test before routing any user prompts:

### Level 1: Authentication & Scope Verification (Free)
- **OpenAI:** `GET https://api.openai.com/v1/models`
- **Gemini:** `GET https://generativelanguage.googleapis.com/v1beta/models`
- **Cost:** $0.00 (Read-only metadata query).
- **Validation:** Verifies HTTP 200, checks that target models (`gpt-4o-mini`, `gemini-2.5-flash`) exist and the key is valid.

### Level 2: Model Execution & Quota Verification (Minimal Spend)
- **OpenAI:** `POST /v1/chat/completions` with 1-word generation (`"OK"`) and `store: False` to guarantee privacy.
- **Gemini:** `POST /v1beta/models/{model}:generateContent` with 1-word generation (`"OK"`).
- **Cost:** < $0.00001 (1 token).
- **Validation:** Verifies that project billing is enabled, quota is unblocked, and tokens can be generated.

---

## 3. Cost-Aware Model Router & $0 Default Guardrail

- **Default Cloud Spend Limit:** **$0.00 / month**.
- **Local-First Mandate:** Out-of-the-box, OpenBagus exclusively runs local inference (Ollama `qwen3.5:2b`, `qwen3.5:4b`, or local `llama-server` with CUDA).
- **User Authorization:** Cloud routing is only activated when:
  1. The user explicitly sets an API key via `/provider add <p> <key>`.
  2. The user explicitly sets a budget via `/ai budget <amount>` (e.g. `/ai budget 5.0`).
- **Exceeding Budget:** If the monthly spend ledger reaches the user budget, the router immediately blocks cloud calls and gracefully downgrades queries to local models.
