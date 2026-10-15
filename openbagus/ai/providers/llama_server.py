"""Native llama.cpp loopback provider with GPU acceleration."""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Iterator

from openbagus.ai.providers.base import (
    BaseModelProvider,
    ChatCompletionChunk,
    ChatCompletionResponse,
    ChatMessage,
    ToolCall,
    ToolDefinition,
)
from openbagus.intelligence.local_language import (
    LLAMA_SERVER_EXE,
    MODEL_FILE,
    MODEL_NAME,
    _ManagedLlamaServer,
)


class LlamaServerProvider(BaseModelProvider):
    """High-performance local loopback inference provider using llama-server with CUDA/CPU."""

    def __init__(
        self,
        server_bin: Path | None = None,
        model_path: Path | None = None,
    ) -> None:
        self.server_bin = server_bin or LLAMA_SERVER_EXE
        self.model_path = model_path or MODEL_FILE
        self._port: int | None = None
        self._backend: str = "UNKNOWN"

    def get_provider_name(self) -> str:
        backend = self._backend if self._backend != "UNKNOWN" else _ManagedLlamaServer.detect_backend(self.server_bin)
        return f"LLAMA_CPP_{backend}"

    def is_available(self) -> bool:
        return self.server_bin.is_file() and self.model_path.is_file()

    def get_model_info(self) -> dict[str, Any]:
        return {
            "model_name": self.model_path.name if self.model_path else MODEL_NAME,
            "model_path": str(self.model_path),
            "backend": self.get_provider_name(),
            "context_window": 16384,
            "quantization": "Q4_K_M",
            "local_loopback": True,
        }

    def _ensure_server(self, timeout: float = 60.0) -> int:
        if not self.is_available():
            raise RuntimeError(f"Llama server binary or model not found: bin={self.server_bin}, model={self.model_path}")
        res = _ManagedLlamaServer.ensure(self.server_bin, self.model_path, timeout=timeout)
        if not res:
            raise RuntimeError("Failed to initialize local llama-server loopback process")
        port, backend = res
        self._port = port
        self._backend = backend
        return port

    def check_health(self) -> dict[str, Any]:
        """Queries /health on the local llama-server instance."""
        if not self._port:
            try:
                self._ensure_server(timeout=5.0)
            except Exception as e:
                return {"status": "offline", "error": str(e)}
        url = f"http://127.0.0.1:{self._port}/health"
        try:
            req = urllib.request.Request(url, headers={"Accept": "application/json"})
            with urllib.request.urlopen(req, timeout=3.0) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except Exception as e:
            return {"status": "error", "error": str(e)}

    def check_slots(self) -> list[dict[str, Any]]:
        """Queries /slots on the local llama-server instance."""
        if not self._port:
            try:
                self._ensure_server(timeout=5.0)
            except Exception:
                return []
        url = f"http://127.0.0.1:{self._port}/slots"
        try:
            req = urllib.request.Request(url, headers={"Accept": "application/json"})
            with urllib.request.urlopen(req, timeout=3.0) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                return data if isinstance(data, list) else data.get("slots", [])
        except Exception:
            return []

    def generate(
        self,
        messages: list[ChatMessage],
        tools: list[ToolDefinition] | None = None,
        max_tokens: int = 1024,
        temperature: float = 0.2,
        stream: bool = False,
        timeout: float = 120.0,
    ) -> ChatCompletionResponse | Iterator[ChatCompletionChunk]:
        port = self._ensure_server(timeout=timeout)
        endpoint = f"http://127.0.0.1:{port}/v1/chat/completions"

        payload: dict[str, Any] = {
            "model": self.model_path.name,
            "messages": [m.to_dict() for m in messages],
            "max_tokens": max_tokens,
            "temperature": temperature,
            "stream": stream,
        }
        if tools:
            payload["tools"] = [t.to_dict() for t in tools]
            payload["tool_choice"] = "auto"

        body = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            endpoint,
            data=body,
            headers={"Content-Type": "application/json", "Accept": "application/json"},
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
            if e.code == 503:
                raise RuntimeError(f"Llama server slots busy/unavailable (HTTP 503): {err_body}") from e
            elif e.code == 400:
                raise RuntimeError(f"Llama server context/argument error (HTTP 400): {err_body}") from e
            raise RuntimeError(f"Llama server HTTP error {e.code}: {e.reason} - {err_body}") from e
        except (urllib.error.URLError, TimeoutError) as e:
            if "timed out" in str(e).lower() or isinstance(e, TimeoutError):
                raise TimeoutError(f"Llama server timed out after {timeout}s: {e}") from e
            raise RuntimeError(f"Llama server connection error: {e}") from e

        latency = (time.perf_counter() - t_start) * 1000
        choice = data.get("choices", [{}])[0]
        msg = choice.get("message", {})
        content = msg.get("content") or ""
        finish_reason = choice.get("finish_reason") or "stop"

        tool_calls: list[ToolCall] = []
        raw_tools = msg.get("tool_calls", [])
        for rt in raw_tools:
            fn = rt.get("function", {})
            name = fn.get("name", "")
            args_raw = fn.get("arguments", "{}")
            try:
                args = json.loads(args_raw) if isinstance(args_raw, str) else args_raw
            except Exception:
                args = {"raw": args_raw}
            tool_calls.append(ToolCall(
                id=rt.get("id", f"call_{len(tool_calls)}"),
                function_name=name,
                arguments=args if isinstance(args, dict) else {},
            ))

        return ChatCompletionResponse(
            content=content,
            tool_calls=tool_calls,
            finish_reason=finish_reason,
            model=data.get("model", self.model_path.name),
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
                        choice = chunk_json.get("choices", [{}])[0]
                        delta = choice.get("delta", {})
                        text = delta.get("content", "")
                        finish = choice.get("finish_reason")
                        if text or finish:
                            yield ChatCompletionChunk(delta_content=text, finish_reason=finish)
                    except Exception:
                        continue
        except Exception as e:
            yield ChatCompletionChunk(delta_content=f"\n[Kesalahan Streaming Model: {e}]", finish_reason="error")
