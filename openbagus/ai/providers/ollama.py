"""Ollama local model provider adapter."""

from __future__ import annotations

import json
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


class OllamaProvider(BaseModelProvider):
    """Adapter for Ollama running at http://127.0.0.1:11434."""

    def __init__(
        self,
        base_url: str = "http://127.0.0.1:11434",
        model: str = "qwen2.5:3b",
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model

    def get_provider_name(self) -> str:
        return "OLLAMA"

    def is_available(self) -> bool:
        try:
            req = urllib.request.Request(f"{self.base_url}/api/tags", method="GET")
            with urllib.request.urlopen(req, timeout=1.5) as resp:
                return resp.status == 200
        except Exception:
            return False

    def get_model_info(self) -> dict[str, Any]:
        return {
            "model_name": self.model,
            "provider": "Ollama",
            "base_url": self.base_url,
            "local_loopback": True,
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
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": [m.to_dict() for m in messages],
            "options": {"temperature": temperature, "num_predict": max_tokens},
            "stream": stream,
        }
        if tools:
            payload["tools"] = [t.to_dict() for t in tools]

        body = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(endpoint, data=body, headers={"Content-Type": "application/json"}, method="POST")

        t_start = time.perf_counter()
        if stream:
            return self._stream_response(req, timeout)

        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except Exception as e:
            raise RuntimeError(f"Ollama request error: {e}") from e

        latency = (time.perf_counter() - t_start) * 1000
        msg = data.get("message", {})
        content = msg.get("content", "")
        raw_tools = msg.get("tool_calls", [])
        tool_calls: list[ToolCall] = []
        for i, rt in enumerate(raw_tools):
            fn = rt.get("function", {})
            tool_calls.append(ToolCall(
                id=f"ollama_call_{i}",
                function_name=fn.get("name", ""),
                arguments=fn.get("arguments", {}),
            ))

        return ChatCompletionResponse(
            content=content,
            tool_calls=tool_calls,
            finish_reason="stop",
            model=data.get("model", self.model),
            provider_name=self.get_provider_name(),
            latency_ms=round(latency, 1),
        )

    def _stream_response(self, req: urllib.request.Request, timeout: float) -> Iterator[ChatCompletionChunk]:
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                for line in resp:
                    decoded = line.decode("utf-8").strip()
                    if not decoded:
                        continue
                    data = json.loads(decoded)
                    chunk_text = data.get("message", {}).get("content", "")
                    done = data.get("done", False)
                    if chunk_text or done:
                        yield ChatCompletionChunk(delta_content=chunk_text, finish_reason="stop" if done else None)
        except Exception as e:
            yield ChatCompletionChunk(delta_content=f"\n[Kesalahan Ollama: {e}]", finish_reason="error")
