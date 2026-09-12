from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass
class ToolCall:
    id: str
    name: str
    input: dict


@dataclass
class ProviderResponse:
    stop_reason: str  # "tool_use" | "end_turn" | "max_tokens" | ...
    text: str
    tool_calls: list[ToolCall] = field(default_factory=list)
    raw_content: Any = None


class AIProvider(ABC):
    """Abstraction so a different LLM vendor can be swapped in later
    (build doc section 3: AIProvider -> AnthropicProvider)."""

    @abstractmethod
    async def create_message(
        self,
        system: str,
        messages: list[dict],
        tools: list[dict],
        max_tokens: int = 4096,
    ) -> ProviderResponse:
        raise NotImplementedError
