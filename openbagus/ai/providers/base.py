"""Base abstractions and schemas for unified model providers."""

from __future__ import annotations

import json
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Iterator


@dataclass
class ToolCall:
    id: str
    function_name: str
    arguments: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "type": "function",
            "function": {
                "name": self.function_name,
                "arguments": json.dumps(self.arguments, ensure_ascii=False) if isinstance(self.arguments, dict) else str(self.arguments),
            },
        }


@dataclass
class ChatMessage:
    role: str  # "system" | "user" | "assistant" | "tool"
    content: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    tool_call_id: str | None = None
    name: str | None = None

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {"role": self.role, "content": self.content}
        if self.tool_calls:
            d["tool_calls"] = [tc.to_dict() for tc in self.tool_calls]
        if self.tool_call_id:
            d["tool_call_id"] = self.tool_call_id
        if self.name:
            d["name"] = self.name
        return d


@dataclass
class ToolDefinition:
    name: str
    description: str
    parameters: dict[str, Any]  # JSON Schema

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }


@dataclass
class ChatCompletionResponse:
    content: str
    tool_calls: list[ToolCall] = field(default_factory=list)
    finish_reason: str = "stop"
    model: str = ""
    usage: dict[str, int] = field(default_factory=dict)
    provider_name: str = ""
    latency_ms: float = 0.0


@dataclass
class ChatCompletionChunk:
    delta_content: str = ""
    delta_tool_calls: list[ToolCall] = field(default_factory=list)
    finish_reason: str | None = None


class BaseModelProvider(ABC):
    """Abstract interface for local and remote model providers."""

    @abstractmethod
    def get_provider_name(self) -> str:
        """Returns provider identifier (e.g. 'LLAMA_CPP_CUDA', 'OLLAMA', 'DETERMINISTIC_FALLBACK')."""
        ...

    @abstractmethod
    def is_available(self) -> bool:
        """Checks if the provider runtime is ready for inference."""
        ...

    @abstractmethod
    def get_model_info(self) -> dict[str, Any]:
        """Returns model metadata, context window, and quantization details."""
        ...

    @abstractmethod
    def generate(
        self,
        messages: list[ChatMessage],
        tools: list[ToolDefinition] | None = None,
        max_tokens: int = 1024,
        temperature: float = 0.2,
        stream: bool = False,
        timeout: float = 60.0,
    ) -> ChatCompletionResponse | Iterator[ChatCompletionChunk]:
        """Generates conversational completion with optional tool calls."""
        ...
