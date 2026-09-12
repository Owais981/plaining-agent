from __future__ import annotations

from app.ai.base import AIProvider, ProviderResponse, ToolCall
from app.config import get_settings


class AnthropicProvider(AIProvider):
    def __init__(self, api_key: str | None = None, model: str | None = None):
        settings = get_settings()
        self.api_key = api_key or settings.anthropic_api_key
        self.model = model or settings.anthropic_model
        self._client = None
        if self.api_key:
            import anthropic
            self._client = anthropic.AsyncAnthropic(api_key=self.api_key)

    @property
    def is_configured(self) -> bool:
        return self._client is not None

    async def create_message(self, system, messages, tools, max_tokens=4096) -> ProviderResponse:
        if not self._client:
            raise RuntimeError(
                "ANTHROPIC_API_KEY is not configured. Set it in the environment to enable the "
                "conversational planning agent; all other functionality (CRUD, solver, conflicts, "
                "costs, risks) works without it."
            )
        response = await self._client.messages.create(
            model=self.model,
            max_tokens=max_tokens,
            system=system,
            tools=tools,
            messages=messages,
        )
        text_parts = []
        tool_calls = []
        for block in response.content:
            if block.type == "text":
                text_parts.append(block.text)
            elif block.type == "tool_use":
                tool_calls.append(ToolCall(id=block.id, name=block.name, input=block.input))
        return ProviderResponse(
            stop_reason=response.stop_reason,
            text="\n".join(text_parts),
            tool_calls=tool_calls,
            raw_content=response.content,
        )
