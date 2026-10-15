"""Local English Language Tutor & Conversational Learning Engine for OpenBagus.

Features:
- Conversational English dialogue adapted to learner proficiency (BEGINNER, INTERMEDIATE, ADVANCED).
- Grammatical correction, sentence structure improvements, and vocabulary enrichment.
- Grammatical explanations delivered in Indonesian for clear conceptual understanding.
- Pronunciation alignment estimates based on Faster-Whisper acoustic evidence with mandatory disclaimer labeling.
- Strict namespace isolation from FINANCIAL_RESEARCH domain.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)

PRONUNCIATION_DISCLAIMER = (
    "[Estimasi ASR: Faster-Whisper Large-v3 Acoustic Alignment — "
    "Estimasi berbasis transkripsi akustik, bukan penilai fonetik bersertifikat]"
)


class ProficiencyLevel(str, Enum):
    BEGINNER = "BEGINNER"
    INTERMEDIATE = "INTERMEDIATE"
    ADVANCED = "ADVANCED"


@dataclass
class TutorCorrection:
    original_segment: str
    corrected_segment: str
    category: str  # "GRAMMAR" | "VOCABULARY" | "STRUCTURE" | "TENSE"
    explanation_id: str


@dataclass
class TutorAssessment:
    english_response: str
    corrections: list[TutorCorrection] = field(default_factory=list)
    vocabulary_notes: list[str] = field(default_factory=list)
    pronunciation_estimate: str | None = None
    level: ProficiencyLevel = ProficiencyLevel.INTERMEDIATE
    full_spoken_reply: str = ""

    def format_text_output(self) -> str:
        parts = [self.english_response.strip()]
        if self.corrections:
            corr_text = ["\n[Koreksi & Penjelasan]:"]
            for c in self.corrections:
                corr_text.append(f"- Kalimat: \"{c.original_segment}\" -> Sebaiknya: \"{c.corrected_segment}\"")
                corr_text.append(f"  Penjelasan: {c.explanation_id}")
            parts.append("\n".join(corr_text))
        if self.vocabulary_notes:
            parts.append("\n[Kosakata Baru]: " + ", ".join(self.vocabulary_notes))
        if self.pronunciation_estimate:
            parts.append(f"\n{PRONUNCIATION_DISCLAIMER}\n{self.pronunciation_estimate}")
        return "\n\n".join(parts)


class EnglishTutor:
    """Manages conversational learning, grammar diagnostics, and bilingual teaching."""

    def __init__(self, default_level: ProficiencyLevel = ProficiencyLevel.INTERMEDIATE) -> None:
        self.level = default_level
        self.vocabulary_bank: list[str] = []
        self.mistake_history: list[dict[str, Any]] = []

    def set_level(self, level: str | ProficiencyLevel) -> ProficiencyLevel:
        if isinstance(level, str):
            clean = level.upper().strip()
            if clean in ("BEGINNER", "BASIC", "PEMULA"):
                self.level = ProficiencyLevel.BEGINNER
            elif clean in ("ADVANCED", "MAHIR"):
                self.level = ProficiencyLevel.ADVANCED
            else:
                self.level = ProficiencyLevel.INTERMEDIATE
        else:
            self.level = level
        logger.info("English Tutor proficiency level set to: %s", self.level.value)
        return self.level

    def analyze_grammar_rules(self, text: str) -> list[TutorCorrection]:
        """Detects common ESL/Indonesian grammatical transfer errors."""
        corrections: list[TutorCorrection] = []
        low = text.lower().strip()

        # 1. Past tense markers with present verb ("yesterday I go", "last week I buy")
        if re.search(r"\b(yesterday|last\s+(?:week|month|year|night)|ago)\b", low):
            if re.search(r"\b(?:i|he|she|we|they)\s+go\b", low):
                corrections.append(TutorCorrection(
                    original_segment="go",
                    corrected_segment="went",
                    category="TENSE",
                    explanation_id="Karena kejadian berlangsung di masa lampau (ada kata 'yesterday/last week'), gunakan past tense 'went' bukan present 'go'."
                ))
            if re.search(r"\b(?:i|he|she|we|they)\s+buy\b", low):
                corrections.append(TutorCorrection(
                    original_segment="buy",
                    corrected_segment="bought",
                    category="TENSE",
                    explanation_id="Untuk menceritakan masa lampau, kata kerja 'buy' berubah menjadi bentuk kedua (V2) yaitu 'bought'."
                ))

        # 2. Missing third person singular 's' ("he go", "she want")
        m_s = re.search(r"\b(he|she|it)\s+(like|want|need|think|know)\b", low)
        if m_s:
            subj = m_s.group(1)
            verb = m_s.group(2)
            corrections.append(TutorCorrection(
                original_segment=f"{subj} {verb}",
                corrected_segment=f"{subj} {verb}s",
                category="GRAMMAR",
                explanation_id=f"Dalam simple present tense, subjek tunggal orang ketiga ({subj}) membutuhkan akhiran '-s' pada kata kerja: '{subj} {verb}s'."
            ))

        # 3. Literal preposition transfer ("join with", "explain about")
        if "join with" in low:
            corrections.append(TutorCorrection(
                original_segment="join with",
                corrected_segment="join",
                category="STRUCTURE",
                explanation_id="Dalam bahasa Inggris, kata 'join' adalah transitive verb yang langsung diikuti objek tanpa preposisi 'with' (misal: 'join us', bukan 'join with us')."
            ))
        if "discuss about" in low:
            corrections.append(TutorCorrection(
                original_segment="discuss about",
                corrected_segment="discuss",
                category="STRUCTURE",
                explanation_id="Kata 'discuss' sudah bermakna 'membahas tentang', sehingga tidak memerlukan preposisi 'about' (misal: 'discuss this topic')."
            ))

        # 4. Redundant double comparison ("more better")
        if "more better" in low:
            corrections.append(TutorCorrection(
                original_segment="more better",
                corrected_segment="better",
                category="GRAMMAR",
                explanation_id="'Better' sudah merupakan bentuk komparatif dari 'good', jadi tidak perlu menambahkan 'more'."
            ))

        return corrections

    def evaluate_pronunciation(self, target_phrase: str, asr_transcript: str) -> str:
        """Compares target practice phrase against transcribed ASR output."""
        clean_target = re.sub(r"[^\w\s]", "", target_phrase.lower()).split()
        clean_asr = re.sub(r"[^\w\s]", "", asr_transcript.lower()).split()

        matches = [w for w in clean_target if w in clean_asr]
        accuracy = (len(matches) / max(1, len(clean_target))) * 100.0

        if accuracy >= 90.0:
            rating = "Sangat Baik (Artikulasi jernih dan tepat)"
        elif accuracy >= 70.0:
            rating = "Cukup Baik (Sebagian besar kata terdengar jelas)"
        else:
            rating = "Perlu Latihan (Coba perlambat tempo dan pertegas konsonan akhir)"

        missed = [w for w in clean_target if w not in clean_asr]
        missed_note = f", kata yang perlu dipertegas: {', '.join(missed)}" if missed else ""

        return f"Akurasi Akustik: {accuracy:.0f}% — {rating}{missed_note}."

    def generate_tutor_response(
        self,
        user_input: str,
        recent_history: list[dict[str, str]] | None = None,
        provider: Any = None,
    ) -> TutorAssessment:
        """Generates an instructional English reply with Indonesian grammar corrections."""
        corrections = self.analyze_grammar_rules(user_input)

        # Level-specific conversational prompting
        if provider is not None and hasattr(provider, "generate"):
            try:
                system_prompt = (
                    "You are Bagusmax, a friendly, supportive, and engaging native English tutor. "
                    f"The learner's proficiency level is {self.level.value}. "
                    "Instructions: "
                    "1. Respond directly and naturally in English to continue the conversation (2-3 sentences). "
                    "2. Adjust your vocabulary and sentence length to match the learner's level. "
                    "3. Ask an engaging follow-up question to encourage the user to speak more. "
                    "4. If the user asked in Indonesian or made grammar mistakes, address them politely. "
                    "Do NOT discuss stock tickers or finance unless the user explicitly brings it up."
                )
                from openbagus.ai.providers.base import ChatMessage
                messages = [
                    ChatMessage(role="system", content=system_prompt),
                ]
                if recent_history:
                    for h in recent_history[-4:]:
                        messages.append(ChatMessage(role=h["role"], content=h["content"]))
                messages.append(ChatMessage(role="user", content=user_input))

                res = provider.generate(messages, max_tokens=3072 if getattr(provider, "think", False) else 512, temperature=0.3, timeout=120.0)
                reply_text = getattr(res, "content", "").strip()
                if not reply_text:
                    reply_text = "Model tidak menghasilkan jawaban tutor. Pesan dan konteks Anda tetap tersimpan; coba ulangi atau gunakan mode FAST."
            except Exception as e:
                logger.warning("English Tutor provider failed: %s", type(e).__name__)
                reply_text = f"Inferensi tutor gagal ({type(e).__name__}). Pesan dan konteks Anda tetap tersimpan; coba ulangi atau gunakan mode FAST."
        else:
            reply_text = self._fallback_dialogue(user_input)

        # Assemble full spoken reply
        spoken_parts = [reply_text]
        if corrections:
            for c in corrections:
                spoken_parts.append(f"Catatan tata bahasa: kata {c.original_segment} sebaiknya diucapkan {c.corrected_segment}. {c.explanation_id}")

        full_spoken = " ".join(spoken_parts)

        return TutorAssessment(
            english_response=reply_text,
            corrections=corrections,
            level=self.level,
            full_spoken_reply=full_spoken,
        )

    def _fallback_dialogue(self, user_input: str) -> str:
        low = user_input.lower()
        if any(w in low for w in ("hello", "hi", "halo", "morning", "afternoon", "evening")):
            return "Hello! It is wonderful to practice English with you today. How has your day been so far?"
        elif any(w in low for w in ("hobby", "free time", "weekend", "activity")):
            return "Talking about free time is always exciting! In my digital routine, I enjoy learning new words. What do you usually like to do on weekends?"
        elif any(w in low for w in ("work", "job", "office", "study", "college")):
            return "That sounds productive! Balancing work and daily learning can be challenging. How do you usually manage your schedule?"
        else:
            return "That is an interesting thought! Could you tell me a little more about that, or share an example?"
