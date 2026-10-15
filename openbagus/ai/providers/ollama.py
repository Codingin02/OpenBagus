"""Ollama local model provider adapter with thinking/DEEP_REASONING mode support.

Supports Ollama 0.35.0+ with:
  - think: bool parameter (Qwen3.5 supported thinking levels: false, true)
  - keep_alive: model VRAM retention duration
  - num_gpu: GPU layer offload count
  - Thinking trace separation (stored separately, never exposed to TTS)
"""

from __future__ import annotations

import json
import logging
import os
import time
import urllib.error
import urllib.request
from typing import Any, Iterator

from openbagus.ai.providers.base import (
    BaseModelProvider,
    ChatCompletionChunk,
    ChatCompletionResponse,
    ChatMessage,
    ToolCall,
    ToolDefinition,
)

logger = logging.getLogger(__name__)

# Official FAST and DEEP model identifiers for RTX 3050 6GB
OLLAMA_FAST_MODEL = "qwen3.5:2b-q4_K_M"
OLLAMA_DEEP_MODEL = "qwen3.5:4b"


class OllamaProvider(BaseModelProvider):
    """Adapter for Ollama running at http://127.0.0.1:11434.

    Supports FAST (think=False) and DEEP_REASONING (think=True) modes
    with automatic VRAM-resident model keep-alive.
    """

    def __init__(
        self,
        base_url: str | None = None,
        model: str = OLLAMA_FAST_MODEL,
        think: bool = False,
        keep_alive: str = "30m",
        num_gpu: int = 99,
        context_window: int = 4096,
    ) -> None:
        self.base_url = (base_url or os.environ.get("OLLAMA_HOST") or "http://127.0.0.1:11434").rstrip("/")
        if "://" not in self.base_url:
            self.base_url = "http://" + self.base_url
        self.model = model
        self.think = think
        self.keep_alive = keep_alive
        self.num_gpu = num_gpu
        self.context_window = context_window

    def get_provider_name(self) -> str:
        return "OLLAMA_DEEP" if self.think else "OLLAMA_FAST"

    def is_available(self) -> bool:
        try:
            req = urllib.request.Request(f"{self.base_url}/api/tags", method="GET")
            with urllib.request.urlopen(req, timeout=2.0) as resp:
                return resp.status == 200
        except Exception:
            return False

    def is_model_warm(self) -> bool:
        """Check if the model is currently loaded in VRAM via /api/ps."""
        try:
            req = urllib.request.Request(f"{self.base_url}/api/ps", method="GET")
            with urllib.request.urlopen(req, timeout=2.0) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                running = data.get("models", [])
                return any(m.get("name", "") == self.model for m in running)
        except Exception:
            return False

    def unload_model(self) -> None:
        """Unload this model from VRAM to free GPU memory for the other mode."""
        if not self.is_available():
            return
        try:
            payload = {"model": self.model, "keep_alive": "0"}
            body = json.dumps(payload).encode("utf-8")
            req = urllib.request.Request(
                f"{self.base_url}/api/generate",
                data=body,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=5.0) as resp:
                resp.read()  # consume response
            logger.info("Unloaded model %s from VRAM", self.model)
        except Exception as e:
            logger.debug("Unload model request failed (benign): %s", e)

    def get_model_info(self) -> dict[str, Any]:
        return {
            "model_name": self.model,
            "provider": "Ollama",
            "base_url": self.base_url,
            "local_loopback": True,
            "think": self.think,
            "keep_alive": self.keep_alive,
            "gpu_layers": self.num_gpu,
            "context_window": self.context_window,
            "is_warm": self.is_model_warm(),
        }

    def generate(
        self,
        messages: list[ChatMessage],
        tools: list[ToolDefinition] | None = None,
        max_tokens: int = 1024,
        temperature: float = 0.2,
        stream: bool = False,
        timeout: float = 60.0,
    ) -> ChatCompletionResponse | Iterator[ChatCompletionChunk]:
        endpoint = f"{self.base_url}/api/chat"
        ollama_messages: list[dict[str, Any]] = []
        for m in messages:
            md = m.to_dict()
            if "tool_calls" in md:
                for tc_dict in md["tool_calls"]:
                    fn = tc_dict.get("function", {})
                    # Ollama expects function.arguments as a JSON object (dict), NOT a stringified JSON
                    if isinstance(fn.get("arguments"), str):
                        try:
                            fn["arguments"] = json.loads(fn["arguments"])
                        except Exception:
                            pass
            ollama_messages.append(md)

        payload: dict[str, Any] = {
            "model": self.model,
            "messages": ollama_messages,
            "think": self.think,
            "keep_alive": self.keep_alive,
            "options": {
                "temperature": temperature,
                "num_predict": max_tokens,
                "num_gpu": self.num_gpu,
                "num_ctx": self.context_window,
            },
            "stream": stream,
        }
        if tools:
            payload["tools"] = [t.to_dict() for t in tools]

        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(
            endpoint,
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        t_start = time.perf_counter()
        if stream:
            return self._stream_response(req, timeout)

        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            err_body = e.read().decode("utf-8", errors="replace")
            logger.error("Ollama HTTPError %d: %s (payload: %s)", e.code, err_body, body[:300])
            # If Ollama failed with a tool syntax/parsing error from model output (e.g. unclosed JSON object),
            # retry without tools so the model can generate a natural text reply without failing
            if tools and ("can't find closing" in err_body or "tool" in err_body.lower() or e.code == 400):
                logger.warning("Ollama tool parsing error from model output (%s). Retrying without tools...", err_body)
                payload_no_tools = dict(payload)
                payload_no_tools.pop("tools", None)
                body_no_tools = json.dumps(payload_no_tools, ensure_ascii=False).encode("utf-8")
                req_retry = urllib.request.Request(
                    endpoint,
                    data=body_no_tools,
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                try:
                    with urllib.request.urlopen(req_retry, timeout=timeout) as resp_retry:
                        data = json.loads(resp_retry.read().decode("utf-8"))
                except Exception as retry_err:
                    raise RuntimeError(f"Ollama request error {e.code}: {err_body}") from retry_err
            else:
                raise RuntimeError(f"Ollama request error {e.code}: {err_body}") from e
        except Exception as e:
            raise RuntimeError(f"Ollama request error: {e}") from e

        latency = (time.perf_counter() - t_start) * 1000
        msg = data.get("message", {})

        # Keep thinking trace separate; do NOT mix into user-facing content
        content = msg.get("content", "")
        thinking_trace = msg.get("thinking", "")

        raw_tools = msg.get("tool_calls", [])
        tool_calls: list[ToolCall] = []
        for i, rt in enumerate(raw_tools):
            fn = rt.get("function", {})
            tool_calls.append(ToolCall(
                id=f"ollama_call_{i}",
                function_name=fn.get("name", ""),
                arguments=fn.get("arguments", {}),
            ))

        response = ChatCompletionResponse(
            content=content,
            tool_calls=tool_calls,
            finish_reason="stop",
            model=data.get("model", self.model),
            provider_name=self.get_provider_name(),
            latency_ms=round(latency, 1),
        )
        # Store thinking trace as extra metadata attribute
        response.thinking_trace = thinking_trace  # type: ignore[attr-defined]
        return response

    def _stream_response(
        self, req: urllib.request.Request, timeout: float
    ) -> Iterator[ChatCompletionChunk]:
        """Stream response, suppressing thinking content from user-facing chunks."""
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                for line in resp:
                    decoded = line.decode("utf-8").strip()
                    if not decoded:
                        continue
                    try:
                        data = json.loads(decoded)
                    except json.JSONDecodeError:
                        continue

                    msg = data.get("message", {})
                    # Skip thinking chunks entirely — they are internal reasoning
                    if msg.get("thinking"):
                        continue

                    chunk_text = msg.get("content", "")
                    done = data.get("done", False)
                    if chunk_text or done:
                        yield ChatCompletionChunk(
                            delta_content=chunk_text,
                            finish_reason="stop" if done else None,
                        )
        except Exception as e:
            yield ChatCompletionChunk(
                delta_content=f"\n[Kesalahan Ollama: {e}]",
                finish_reason="error",
            )
