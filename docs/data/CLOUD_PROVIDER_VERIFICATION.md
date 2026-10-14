# OpenBagus — Cloud Provider Verification & Zero-Spend Guardrail Report
**Document ID:** DOC-DATA-CLOUD-20261015-06  
**Target Worktree:** `E:\Projects\OpenBagus-Data`  
**Execution Timestamp:** 2026-10-15T06:13:21Z / 2026-10-14T23:13:21 UTC  

---

## 1. Directive Objective

Cloud model integration in OpenBagus is strictly **optional**, **opt-in**, and constrained by a **$0.00 default spend guardrail**. This audit verifies:
1. No cloud inference costs are incurred by default.
2. Two-level verification protocol:
   - **Level 1 (Authentication Check):** Lightweight `GET /models` probe.
   - **Level 2 (Execution Check):** Minimal generation probe (`1+1=2`, max 5 tokens).
3. No credentials are treated as verified simply because a string was saved.
4. Privacy reality: truthful disclosure of vendor data retention policies (`store=false` nuance).

---

## 2. Empirical Verification Results

### A. OpenAI Provider (`OpenAIProvider`)
- **Configured Status:** `NOT_CONFIGURED`
- **Environment Variable:** `OPENAI_API_KEY` is empty / unset.
- **Level 1 Check:** Aborted cleanly with `success: False`, `status: "NOT_CONFIGURED"`.
- **Level 2 Check:** Skipped.
- **Spend:** **$0.00**

### B. Google Gemini Provider (`GeminiProvider`)
- **Configured Status:** Stored key present in `CredentialManager` (`d1d...d80c`).
- **Level 1 Live Network Execution:**
  - Endpoint: `https://generativelanguage.googleapis.com/v1beta/models`
  - Header: `x-goog-api-key: d1d...d80c`
  - HTTP Status: **400 Bad Request**
  - Error Payload: `{"error": {"code": 400, "message": "API key not valid. Please pass a valid API key.", "status": "INVALID_ARGUMENT"}}`
  - Latency: 278.9 ms
- **Level 1 Outcome:** `success: False`, status: `INVALID_CREDENTIALS`.
- **Level 2 Check:** Automatically blocked by failure of Level 1.
- **Spend:** **$0.00**

---

## 3. Cost-Aware Router & Spend Ledger Verification

The `CostAwareModelRouter` enforces strict budget controls:
- **Default Budget:** `$0.00`
- **Default Cloud Enablement:** `False`
- **Routing Decision:** When `budget == 0.00` or `enable_cloud == False`, all requests are routed exclusively to local runtimes:
  - `LLAMA_CPP_CUDA` (llama.cpp server running on local NVIDIA RTX 3050)
  - `OLLAMA_FAST` / `OLLAMA_DEEP`
  - `DETERMINISTIC_FALLBACK`
- **Hard Spend Limit:** Tested and verified in `test_j_cost_aware_router_budget`. If budget is depleted to $0.00, cloud routing is instantly disabled.

---

## 4. Privacy Reality & Vendor Retention Nuances

OpenBagus explicitly informs users of vendor data retention policies:
1. **OpenAI API `store=false`:**
   - Setting `store=false` in the API payload disables the generation of persistent stored completions in the OpenAI dashboard.
   - **However**, under OpenAI's business data policy, requests and responses are retained for up to 30 days for abuse and misuse monitoring (unless the organization has an approved Zero Data Retention agreement).
   - Therefore, OpenBagus does **not** claim `store=false` equals "instant zero retention".
2. **Audio & PII Guardrail:**
   - Microphone audio buffers are processed 100% locally with Faster-Whisper and Silero VAD. Raw audio bytes are **never** transmitted to cloud providers.
   - Local financial database contents and system file paths are never sent to external LLMs without explicit user command.
