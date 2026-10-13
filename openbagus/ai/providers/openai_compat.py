"""Generic OpenAI-compatible completions provider adapter."""

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


class OpenAICompatibleProvider(BaseModelProvider):
    """Generic OpenAI-compatible REST API client."""

    def __init__(
        self,
        base_url: str = "http://127.0.0.1:8000/v1",
        model: str = "default",
        api_key: str | None = None,
        provider_label: str = "OPENAI_COMPATIBLE",
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.api_key = api_key
        self.provider_label = provider_label

    def get_provider_name(self) -> str:
        return self.provider_label

    def is_available(self) -> bool:
        try:
            req = urllib.request.Request(f"{self.base_url}/models", method="GET")
            if self.api_key:
                req.add_header("Authorization", f"Bearer {self.api_key}")
            with urllib.request.urlopen(req, timeout=2.0) as resp:
                return resp.status == 200
        except Exception:
            return False

    def get_model_info(self) -> dict[str, Any]:
        return {
            "model_name": self.model,
            "provider": self.provider_label,
            "base_url": self.base_url,
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
        endpoint = f"{self.base_url}/chat/completions"
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": [m.to_dict() for m in messages],
            "max_tokens": max_tokens,
            "temperature": temperature,
            "stream": stream,
        }
        if tools:
            payload["tools"] = [t.to_dict() for t in tools]
            payload["tool_choice"] = "auto"

        body = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(endpoint, data=body, headers={"Content-Type": "application/json"}, method="POST")
        if self.api_key:
            req.add_header("Authorization", f"Bearer {self.api_key}")

        t_start = time.perf_counter()
        if stream:
            return self._stream_response(req, timeout)

        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except Exception as e:
            raise RuntimeError(f"OpenAI-compatible request error: {e}") from e

        latency = (time.perf_counter() - t_start) * 1000
        choice = data.get("choices", [{}])[0]
        msg = choice.get("message", {})
        content = msg.get("content") or ""
        tool_calls: list[ToolCall] = []
        for rt in msg.get("tool_calls", []):
            fn = rt.get("function", {})
            args_raw = fn.get("arguments", "{}")
            try:
                args = json.loads(args_raw) if isinstance(args_raw, str) else args_raw
            except Exception:
                args = {"raw": args_raw}
            tool_calls.append(ToolCall(
                id=rt.get("id", f"call_{len(tool_calls)}"),
                function_name=fn.get("name", ""),
                arguments=args if isinstance(args, dict) else {},
            ))

        return ChatCompletionResponse(
            content=content,
            tool_calls=tool_calls,
            finish_reason=choice.get("finish_reason", "stop"),
            model=data.get("model", self.model),
            usage=data.get("usage", {}),
            provider_name=self.get_provider_name(),
            latency_ms=round(latency, 1),
        )

    def _stream_response(self, req: urllib.request.Request, timeout: float) -> Iterator[ChatCompletionChunk]:
        req.add_header("Accept", "text/event-stream")
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                for line in resp:
                    decoded = line.decode("utf-8").strip()
                    if not decoded or not decoded.startswith("data: "):
                        continue
                    data_str = decoded[6:]
                    if data_str == "[DONE]":
                        break
                    try:
                        chunk_json = json.loads(data_str)
                        delta = chunk_json.get("choices", [{}])[0].get("delta", {})
                        text = delta.get("content", "")
                        finish = chunk_json.get("choices", [{}])[0].get("finish_reason")
                        if text or finish:
                            yield ChatCompletionChunk(delta_content=text, finish_reason=finish)
                    except Exception:
                        continue
        except Exception as e:
            yield ChatCompletionChunk(delta_content=f"\n[Kesalahan Streaming: {e}]", finish_reason="error")
