"""Optional LLM Critic and Summarizer package for OpenBagus."""

from __future__ import annotations

from openbagus.intelligence.llm.prompts import ROLE_PROMPTS, SYSTEM_PROMPT, build_user_prompt
from openbagus.intelligence.llm.router import LLMJuryRouter

__all__ = ["ROLE_PROMPTS", "SYSTEM_PROMPT", "build_user_prompt", "LLMJuryRouter"]
