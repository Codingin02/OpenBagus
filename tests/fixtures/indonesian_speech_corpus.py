"""Indonesian speech evaluation corpus for ASR accuracy, barge-in, and hallucination rejection benchmarks."""

from __future__ import annotations

from dataclasses import dataclass
from typing import List


@dataclass(frozen=True)
class SpeechCorpusItem:
    id: str
    target_text: str
    category: str
    is_genuine_speech: bool
    should_reject_as_outro: bool = False
    expected_tickers: tuple[str, ...] = ()


INDONESIAN_SPEECH_CORPUS: List[SpeechCorpusItem] = [
    # 12 Core Required Directive Sentences
    SpeechCorpusItem(
        id="CORP-01",
        target_text="Halo Bagusmax, apakah kamu mendengar suara saya?",
        category="GREETING",
        is_genuine_speech=True,
    ),
    SpeechCorpusItem(
        id="CORP-02",
        target_text="Saya ingin berbicara bahasa Indonesia.",
        category="CONVERSATIONAL",
        is_genuine_speech=True,
    ),
    SpeechCorpusItem(
        id="CORP-03",
        target_text="Tolong analisis saham BBCA untuk satu hari.",
        category="FINANCIAL_ANALYSIS",
        is_genuine_speech=True,
        expected_tickers=("BBCA",),
    ),
    SpeechCorpusItem(
        id="CORP-04",
        target_text="Bandingkan saham BBRI dengan BMRI.",
        category="FINANCIAL_COMPARISON",
        is_genuine_speech=True,
        expected_tickers=("BBRI", "BMRI"),
    ),
    SpeechCorpusItem(
        id="CORP-05",
        target_text="Berapa harga terakhir saham RATU?",
        category="FINANCIAL_PRICE",
        is_genuine_speech=True,
        expected_tickers=("RATU",),
    ),
    SpeechCorpusItem(
        id="CORP-06",
        target_text="Saya mau tahu perkembangan pasar kripto.",
        category="FINANCIAL_CRYPTO",
        is_genuine_speech=True,
    ),
    SpeechCorpusItem(
        id="CORP-07",
        target_text="Sebentar, saya belum selesai berbicara.",
        category="HESITATION_PAUSE",
        is_genuine_speech=True,
    ),
    SpeechCorpusItem(
        id="CORP-08",
        target_text="Bukan itu maksud pertanyaan saya.",
        category="CORRECTION",
        is_genuine_speech=True,
    ),
    SpeechCorpusItem(
        id="CORP-09",
        target_text="Saya sedang berpikir, tunggu sebentar.",
        category="HESITATION_THINKING",
        is_genuine_speech=True,
    ),
    SpeechCorpusItem(
        id="CORP-10",
        target_text="Terima kasih.",
        category="COURTESY_GENUINE",
        is_genuine_speech=True,
        should_reject_as_outro=False,
    ),
    SpeechCorpusItem(
        id="CORP-11",
        target_text="Terima kasih telah menonton.",
        category="OUTRO_PHRASE",
        is_genuine_speech=True,
        should_reject_as_outro=True,
    ),
    SpeechCorpusItem(
        id="CORP-12",
        target_text="Bagusmax, berhenti dulu.",
        category="INTERRUPT_STOP",
        is_genuine_speech=True,
    ),
    # 8 Additional Natural Indonesian Conversational & Market Phrases
    SpeechCorpusItem(
        id="CORP-13",
        target_text="Berapa target harga saham Telkom untuk minggu depan?",
        category="FINANCIAL_TARGET",
        is_genuine_speech=True,
        expected_tickers=("TLKM",),
    ),
    SpeechCorpusItem(
        id="CORP-14",
        target_text="Apakah saham ASII masih layak untuk investasi jangka panjang?",
        category="FINANCIAL_INVESTMENT",
        is_genuine_speech=True,
        expected_tickers=("ASII",),
    ),
    SpeechCorpusItem(
        id="CORP-15",
        target_text="Tolong cek valuasi PER dan PBV saham BBNI.",
        category="FINANCIAL_VALUATION",
        is_genuine_speech=True,
        expected_tickers=("BBNI",),
    ),
    SpeechCorpusItem(
        id="CORP-16",
        target_text="Coba jelaskan prospek dividen Antam tahun ini.",
        category="FINANCIAL_DIVIDEND",
        is_genuine_speech=True,
        expected_tickers=("ANTM",),
    ),
    SpeechCorpusItem(
        id="CORP-17",
        target_text="Tolong ulangi jawabanmu yang tadi.",
        category="CONVERSATIONAL_REPEAT",
        is_genuine_speech=True,
    ),
    SpeechCorpusItem(
        id="CORP-18",
        target_text="Ganti topik, mari kita bahas pasar modal hari ini.",
        category="TOPIC_SWITCH",
        is_genuine_speech=True,
    ),
    SpeechCorpusItem(
        id="CORP-19",
        target_text="Stop, jangan lanjutkan dulu.",
        category="INTERRUPT_STOP",
        is_genuine_speech=True,
    ),
    SpeechCorpusItem(
        id="CORP-20",
        target_text="Siap, terima kasih banyak atas penjelasannya.",
        category="COURTESY_COMPLEX",
        is_genuine_speech=True,
    ),
]
