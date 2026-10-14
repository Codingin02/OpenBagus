"""Acceptance tests for Local AI FAST/DEEP Ollama integration, VRAM management, and CLI commands."""

from __future__ import annotations

import io
import unittest
from unittest.mock import MagicMock, patch

from openbagus.ai.harness.orchestrator import AgentHarness, AgentResponse
from openbagus.ai.memory.working_context import WorkingContext
from openbagus.ai.providers.base import (
    BaseModelProvider,
    ChatCompletionResponse,
    ChatMessage,
)
from openbagus.ai.providers.manager import ProviderManager
from openbagus.ai.providers.ollama import (
    OLLAMA_DEEP_MODEL,
    OLLAMA_FAST_MODEL,
    OllamaProvider,
)
from openbagus.ai.runtime.profiles import get_profile, list_profiles
from openbagus.cli import OpenBagusShell


class TestOllamaProviderConfiguration(unittest.TestCase):
    """Verifies Ollama provider thinking API, model identifiers, and VRAM management."""

    def test_fast_provider_configuration(self) -> None:
        p = OllamaProvider(model=OLLAMA_FAST_MODEL, think=False, context_window=2048)
        self.assertEqual(p.model, "qwen3.5:2b-q4_K_M")
        self.assertFalse(p.think)
        self.assertEqual(p.context_window, 2048)
        self.assertEqual(p.get_provider_name(), "OLLAMA_FAST")

        info = p.get_model_info()
        self.assertEqual(info["model_name"], "qwen3.5:2b-q4_K_M")
        self.assertFalse(info["think"])
        self.assertEqual(info["context_window"], 2048)
        self.assertEqual(info["keep_alive"], "30m")

    def test_deep_provider_configuration(self) -> None:
        p = OllamaProvider(model=OLLAMA_DEEP_MODEL, think=True, context_window=4096)
        self.assertEqual(p.model, "qwen3.5:4b")
        self.assertTrue(p.think)
        self.assertEqual(p.context_window, 4096)
        self.assertEqual(p.get_provider_name(), "OLLAMA_DEEP")

        info = p.get_model_info()
        self.assertEqual(info["model_name"], "qwen3.5:4b")
        self.assertTrue(info["think"])
        self.assertEqual(info["context_window"], 4096)

    def test_thinking_trace_separated_in_response(self) -> None:
        """Thinking trace must be stored separately and not mixed into content."""
        p = OllamaProvider(model=OLLAMA_DEEP_MODEL, think=True)
        # Mocking generate response from Ollama API
        mock_payload = {
            "model": "qwen3.5:4b",
            "message": {
                "role": "assistant",
                "content": "Valuasi DCF emiten berada di level Rp 9.500.",
                "thinking": "Pertama mari kita hitung FCFF dari EBITDA dan Capex...",
            },
        }

        with patch("urllib.request.urlopen") as mock_urlopen:
            mock_resp = MagicMock()
            mock_resp.read.return_value = json_encode(mock_payload)
            mock_resp.__enter__.return_value = mock_resp
            mock_urlopen.return_value = mock_resp

            resp = p.generate(messages=[ChatMessage(role="user", content="Hitung valuasi")])
            self.assertIsInstance(resp, ChatCompletionResponse)
            # User facing content must NOT contain the internal thinking trace
            self.assertEqual(resp.content, "Valuasi DCF emiten berada di level Rp 9.500.")
            self.assertNotIn("FCFF", resp.content)
            # Thinking trace is safely preserved in metadata attribute
            self.assertEqual(
                getattr(resp, "thinking_trace", ""),
                "Pertama mari kita hitung FCFF dari EBITDA dan Capex...",
            )


class TestProviderManagerSwitching(unittest.TestCase):
    """Verifies sequential VRAM offload when switching between FAST and DEEP models."""

    def setUp(self) -> None:
        self.mgr = ProviderManager.get_instance()

    def test_get_fast_and_deep_instances(self) -> None:
        fast = self.mgr.get_fast_provider()
        deep = self.mgr.get_deep_provider()
        self.assertFalse(fast.think)
        self.assertTrue(deep.think)
        self.assertEqual(fast.model, OLLAMA_FAST_MODEL)
        self.assertEqual(deep.model, OLLAMA_DEEP_MODEL)

    def test_switch_to_fast_unloads_deep_if_warm(self) -> None:
        deep = self.mgr.get_deep_provider()
        with patch.object(deep, "is_model_warm", return_value=True), \
             patch.object(deep, "unload_model") as mock_unload:
            fast_res = self.mgr.switch_to_fast()
            mock_unload.assert_called_once()
            self.assertEqual(fast_res.get_provider_name(), "OLLAMA_FAST")

    def test_switch_to_deep_unloads_fast_if_warm(self) -> None:
        fast = self.mgr.get_fast_provider()
        with patch.object(fast, "is_model_warm", return_value=True), \
             patch.object(fast, "unload_model") as mock_unload:
            deep_res = self.mgr.switch_to_deep()
            mock_unload.assert_called_once()
            self.assertEqual(deep_res.get_provider_name(), "OLLAMA_DEEP")


class TestRuntimeProfiles(unittest.TestCase):
    """Verifies runtime profiles contain think flag and proper token budgets."""

    def test_fast_profile(self) -> None:
        p = get_profile("FAST")
        self.assertEqual(p.name, "FAST")
        self.assertEqual(p.context_window, 2048)
        self.assertEqual(p.max_tokens, 512)
        self.assertFalse(p.think)

    def test_deep_reasoning_profile(self) -> None:
        p = get_profile("DEEP_REASONING")
        self.assertEqual(p.name, "DEEP_REASONING")
        self.assertEqual(p.context_window, 4096)
        self.assertEqual(p.max_tokens, 2048)
        self.assertTrue(p.think)

    def test_deep_research_alias(self) -> None:
        p = get_profile("DEEP_RESEARCH")
        self.assertTrue(p.think)


class TestAgentHarnessModeIntegration(unittest.TestCase):
    """Verifies AgentHarness mode parameter and submit_turn classmethod."""

    def test_submit_turn_factory(self) -> None:
        with patch.object(AgentHarness, "run") as mock_run:
            mock_run.return_value = AgentResponse(content="Halo dari test!")
            resp = AgentHarness.submit_turn(
                session_id="test_sess",
                text="Halo Bagus",
                mode="FAST",
                input_channel="TEXT",
            )
            mock_run.assert_called_once_with(user_query="Halo Bagus", mode="FAST")
            self.assertEqual(resp.content, "Halo dari test!")

    def test_agent_response_contains_thinking_trace_field(self) -> None:
        resp = AgentResponse(
            content="Jawaban final",
            thinking_trace="Internal reasoning step 1, 2, 3",
        )
        self.assertEqual(resp.content, "Jawaban final")
        self.assertEqual(resp.thinking_trace, "Internal reasoning step 1, 2, 3")


class TestCLINewCommands(unittest.TestCase):
    """Verifies new CLI commands (/mode, /model, /gpu, /hardware, /cancel, /show-openbagus)."""

    def setUp(self) -> None:
        self.shell = OpenBagusShell()

    def test_do_mode_fast_and_deep(self) -> None:
        self.shell.do_mode("fast")
        self.assertEqual(self.shell.current_mode, "FAST")
        self.assertEqual(self.shell.runtime_profile.name, "FAST")

        self.shell.do_mode("deep")
        self.assertEqual(self.shell.current_mode, "DEEP_REASONING")
        self.assertEqual(self.shell.runtime_profile.name, "DEEP_REASONING")

    def test_do_model_status_and_list(self) -> None:
        # Must execute without uncaught exceptions
        self.shell.do_model("status")
        self.shell.do_model("list")

    def test_do_gpu_and_hardware(self) -> None:
        self.shell.do_gpu("")
        self.shell.do_hardware("")

    def test_do_cancel(self) -> None:
        self.shell.do_cancel("")

    def test_do_data_freshness(self) -> None:
        self.shell.do_data("freshness")

    def test_do_show_openbagus_status(self) -> None:
        self.shell.do_show_openbagus("status")
        self.shell.do_show("status")


def json_encode(data: dict) -> bytes:
    import json
    return json.dumps(data).encode("utf-8")


if __name__ == "__main__":
    unittest.main()
