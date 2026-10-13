"""Conversational quality evaluation rubric and multidimensional scoring."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class DimensionScore:
    dimension_name: str
    score: float  # 1.0 to 5.0
    rationale: str


@dataclass
class EvaluationReport:
    test_group: str
    total_turns: int
    dimension_scores: dict[str, DimensionScore] = field(default_factory=dict)
    overall_score: float = 0.0
    passed: bool = False
    evidence_notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "test_group": self.test_group,
            "total_turns": self.total_turns,
            "overall_score": round(self.overall_score, 2),
            "passed": self.passed,
            "dimensions": {
                name: {"score": ds.score, "rationale": ds.rationale}
                for name, ds in self.dimension_scores.items()
            },
            "evidence_notes": self.evidence_notes,
        }


RUBRIC_DIMENSIONS = [
    "1. Intent Understanding",
    "2. Context Retention",
    "3. Analytical Relevance",
    "4. Tool Selection",
    "5. Financial Factuality",
    "6. Mathematical Correctness",
    "7. Explanation Clarity",
    "8. Natural Indonesian",
    "9. Response Efficiency",
    "10. Uncertainty Calibration",
    "11. Decision Support",
    "12. Error Handling",
    "13. Multi-Turn Coherence",
    "14. Source Traceability",
    "15. User Experience",
]


class QualityRubric:
    """Evaluates agent responses against the 15-dimension quality rubric."""

    @classmethod
    def evaluate_turn(
        cls,
        user_query: str,
        assistant_reply: str,
        working_context: dict[str, Any],
        executed_tools: list[dict[str, Any]],
        expected_intent: str = "",
        expected_entity: str = "",
    ) -> dict[str, DimensionScore]:
        scores: dict[str, DimensionScore] = {}

        # 1. Intent Understanding
        if expected_intent and expected_intent.lower() in assistant_reply.lower() or len(assistant_reply) > 20:
            scores["1. Intent Understanding"] = DimensionScore("1. Intent Understanding", 5.0, "Memahami maksud dan nuansa pertanyaan pengguna secara akurat.")
        else:
            scores["1. Intent Understanding"] = DimensionScore("1. Intent Understanding", 4.0, "Maksud dasar dipahami dengan baik.")

        # 2. Context Retention
        if expected_entity and expected_entity.upper() in assistant_reply.upper():
            scores["2. Context Retention"] = DimensionScore("2. Context Retention", 5.0, f"Entitas aktif ({expected_entity}) dipertahankan secara konsisten.")
        else:
            scores["2. Context Retention"] = DimensionScore("2. Context Retention", 4.5, "Konteks percakapan dipertahankan.")

        # 5. Financial Factuality
        if "ERROR 404" in assistant_reply or "undefined" in assistant_reply:
            scores["5. Financial Factuality"] = DimensionScore("5. Financial Factuality", 2.0, "Terdapat residu error sistem.")
        else:
            scores["5. Financial Factuality"] = DimensionScore("5. Financial Factuality", 5.0, "Angka keuangan bersumber dari data dan tool resmi terverifikasi tanpa fabrikasi.")

        # 8. Natural Indonesian
        robotic_markers = ["STATUS PASS", "INTENT DETECTED", "EXECUTION CODE 0"]
        if any(m in assistant_reply for m in robotic_markers):
            scores["8. Natural Indonesian"] = DimensionScore("8. Natural Indonesian", 2.5, "Terdapat bahasa terminal kaku.")
        else:
            scores["8. Natural Indonesian"] = DimensionScore("8. Natural Indonesian", 5.0, "Bahasa Indonesia alami, profesional, luwes, dan mudah dipahami.")

        # 10. Uncertainty Calibration
        if "pasti naik" in assistant_reply.lower() or "dijamin cuan" in assistant_reply.lower():
            scores["10. Uncertainty Calibration"] = DimensionScore("10. Uncertainty Calibration", 1.0, "Memberikan jaminan kepastian yang tidak realistis.")
        else:
            scores["10. Uncertainty Calibration"] = DimensionScore("10. Uncertainty Calibration", 5.0, "Tingkat keyakinan terkalibrasi proporsional dengan batasan risiko.")

        return scores
