# OPENBAGUS — V5.1 ENGLISH TUTOR LOCAL SETUP & ARCHITECTURE

**Domain Module:** `openbagus/domains/english_tutor/`  
**Model Architecture:** Local Qwen3-4B Q4_K_M (Shared Weights) + Piper US Norman Male TTS  
**Date:** 2026-10-15  
**Directive:** Master Directive V5.1  

---

## 1. Overview & Architectural Principles

In accordance with Section 9 of Master Directive V5.1:
1. **Zero Weight Duplication:** English Tutor reuses the local 4B GGUF model (`models/llm/fast/Qwen3-4B-Q4_K_M.gguf`), applying dedicated system instructions and prompt engineering rather than loading a secondary large model into the 6 GB VRAM envelope.
2. **Namespace Isolation:** The conversation state is divided into two mutually exclusive namespaces:
   - `FINANCIAL_RESEARCH`: Indonesian equities (IDX), technical analysis, crypto order flow, and risk calculations.
   - `ENGLISH_TUTOR`: Natural conversational English practice, grammar feedback, and vocabulary explanations.
3. **No Financial Hallucinations in Tutor Mode:** Ticker symbols and financial keywords are isolated; speaking in English does not trigger stock queries.
4. **Bilingual Audio Generation:**
   - English conversational responses: Spoken by Piper US Norman male voice (`en_US-norman-medium.onnx`, $F_0 = 106.5\text{ Hz}$).
   - Indonesian pedagogical notes and grammar corrections: Spoken by Bagusmax Indonesian voice (`id_ID-news_tts-medium.onnx`).

---

## 2. Interaction Flow & Turn Examples

### 2.1 Mode Activation
User speaks:
> *"Aku mau belajar bahasa Inggris."*

OpenBagus responds (with single transition acknowledgement):
> *"Siap! Kita beralih ke mode English Tutor. Hello! I am Bagusmax, your English speaking companion. What would you like to talk about today?"*

### 2.2 ESL Grammar Diagnostics
If user says:
> *"Yesterday I go to market and buy fruit."*

English Tutor analyzes common Indonesian-to-English language transfer errors:
1. **Past Tense Transfer:** Recognizes temporal marker (*yesterday*) with base verb (*go* $\to$ *went*, *buy* $\to$ *bought*).
2. **Subject-Verb Agreement:** Checks third-person singular markers (*he works*, *she likes*).
3. **Preposition Patterns:** Checks collocations (*listen to*, *in the morning*).

Output delivered to user:
```text
Great effort! Here is a more natural way to say that:
"Yesterday I went to the market and bought some fruit."

Catatan Tata Bahasa:
- 'went' & 'bought': Gunakan kata kerja bentuk lampau (past tense) karena kalimat diawali dengan keterangan waktu kemarin (yesterday).
- 'the market': Tambahkan artikel 'the' untuk merujuk ke tempat tertentu.

What kind of fruit did you buy?
```

### 2.3 Pronunciation Assessment & Disclaimer
Pronunciation alignment is scored using local `faster-whisper-large-v3` token-level acoustic timestamps:
- Metric: Normalized Levenshtein token similarity + acoustic confidence weights.
- Categories:
  - $\ge 90\%$: Sangat Baik (Excellent fluency)
  - $75\% - 89\%$: Baik (Good articulation)
  - $< 75\%$: Perlu Latihan (Needs practice)
- **Mandatory Transparency Disclaimer:**
  ```text
  Disclaimer: Skor pengucapan dihitung secara lokal berbasis Faster-Whisper Large-v3 
  Acoustic Alignment dan dimaksudkan sebagai panduan latihan kelancaran percakapan, 
  bukan sertifikasi fonetik resmi.
  ```

### 2.4 Mode Deactivation
User speaks:
> *"Bagusmax, kembali ke saham."*

OpenBagus confirms:
> *"Baik, kita kembali ke mode Riset Finansial. Ada emiten atau topik pasar modal yang ingin dianalisis?"*
*(Namespace reverts to `FINANCIAL_RESEARCH`; stock catalog and financial tools re-engage immediately).*
