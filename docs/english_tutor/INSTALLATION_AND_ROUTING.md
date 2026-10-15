# OPENBAGUS — ENGLISH TUTOR ARCHITECTURE & ROUTING SPECIFICATION

**Module:** `openbagus/domains/english_tutor/`  
**Integration:** Harness Orchestrator & Local TTS Engine  
**Worktree:** `E:\Projects\OpenBagus-Voice`  
**Branch:** `feat/openbagus-local-voice-live`  
**Status:** **ACTIVE / VERIFIED**  

---

## 1. Overview

The English Learning Mode provides conversational English practice, real-time grammar diagnostics, and pronunciation assessment for Indonesian ESL learners without requiring external cloud APIs or polluting OpenBagus's core financial research domain.

### Key Architectural Requirements:
1. **Namespace Isolation:** Strict separation between `FINANCIAL_RESEARCH` and `ENGLISH_TUTOR` working contexts.
2. **Grammar & Transfer Error Diagnostics:** Specific detection of Indonesian-to-English language transfer errors (e.g., past tense omission, third-person singular `-s`, missing prepositions).
3. **Bilingual Multi-Voice Streaming:** English conversation sentences are synthesized with the Norman American male voice (`en_US-norman-medium`, F0 ~ 106.5 Hz), while Indonesian pedagogical explanations and grammar feedback use the Bagusmax voice (`id_ID-news_tts-medium`).
4. **Honest Acoustic Pronunciation Scoring:** Word-level alignment scoring accompanied by an explicit disclaimer regarding ASR phonetic limitations.

---

## 2. Namespace & Context Routing

In `openbagus/ai/memory/working_context.py`:
- `context_namespace`: `"FINANCIAL_RESEARCH"` | `"ENGLISH_TUTOR"`
- `tutor_level`: `"beginner"` | `"intermediate"` | `"advanced"`
- `tutor_memory`: Stores conversation topics, recurring grammar mistakes, and target vocabulary.

### Transition Triggers (in `AgentHarness.run`):
- **Switch to English Tutor:** User utterances containing `"belajar bahasa inggris"`, `"english tutor"`, `"practice english"`, `"speak english"`.
  - Action: Sets `context.context_namespace = "ENGLISH_TUTOR"`. Injects `ENGLISH_TUTOR_SYSTEM_PROMPT`. Clears active ticker symbols to prevent financial tool hallucination.
- **Switch to Financial Research:** User utterances containing `"kembali ke saham"`, `"selesai belajar"`, `"mode riset"`, `"crypto"`.
  - Action: Reverts `context.context_namespace = "FINANCIAL_RESEARCH"`. Restores financial research harness prompts.

---

## 3. Bilingual Streaming TTS Engine

In `openbagus/voice/tts_engine.py`:
- Multiple ONNX models are loaded into memory:
  - Indonesian: `id_ID-news_tts-medium.onnx`
  - English: `en_US-norman-medium.onnx`
- `detect_sentence_language(sentence: str) -> str`:
  - Uses lexical heuristics and word frequency analysis to tag individual sentences as `en-US` or `id-ID`.
- `synthesize_stream(text: str)`:
  - Splits output into sentences.
  - Generates audio chunks using the matching language model.
  - Ensures seamless audio transitions without clicking, popping, or device reset.

---

## 4. Grammar Diagnostic Engine

In `openbagus/domains/english_tutor/tutor.py`:
The `EnglishTutor` class inspects user inputs for common transfer errors:
1. **Past Tense Transfer:** Indicated by temporal markers (`yesterday`, `last night`, `ago`) paired with base verbs (`go` -> `went`, `buy` -> `bought`).
2. **Third-Person Singular `-s`:** Subject-verb agreement errors (`he like` -> `he likes`, `she work` -> `she works`).
3. **Preposition Errors:** Incorrect prepositions (`in morning` -> `in the morning`, `listen music` -> `listen to music`).

### Output Format Example:
```text
Great effort! Here is a natural way to say it:
"Yesterday I went to the market."

Catatan Tata Bahasa:
- 'went': Gunakan bentuk lampau (past tense) dari 'go' karena percakapan merujuk ke kejadian kemarin (yesterday).

Now, what did you buy at the market?
```

---

## 5. Acoustic Pronunciation Assessment & Disclaimer

The tutor evaluates user pronunciation by comparing phoneme/word timestamps from `faster-whisper-large-v3`:
```python
PRONUNCIATION_DISCLAIMER = (
    "Disclaimer: Skor pengucapan dihitung secara lokal berbasis Faster-Whisper Large-v3 "
    "Acoustic Alignment dan dimaksudkan sebagai panduan latihan kelancaran percakapan, "
    "bukan sertifikasi fonetik resmi."
)
```
- Accuracy scoring: Levenshtein distance on normalized tokens + word confidence weights.
- Categories: Sangat Baik (>= 90%), Baik (75-89%), Perlu Latihan (< 75%).
- Zero external network dependencies.
