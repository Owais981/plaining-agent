"""The orchestration loop (build doc section 8/31):

    User message -> Claude -> tool call -> backend tool execution ->
    tool result -> Claude -> (more tool calls) -> final human-readable
    response.

The backend executes every tool; the frontend and the LLM never touch the
database or the solver directly."""
from __future__ import annotations

import json
from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from app.ai.base import AIProvider
from app.ai.tools import TOOLS, execute_tool
from app.prompts.planning_agent_v1 import PLANNING_AGENT_SYSTEM_PROMPT

MAX_TOOL_ITERATIONS = 8


@dataclass
class AgentTurnResult:
    final_text: str
    tool_trace: list[dict] = field(default_factory=list)  # [{tool, input, output}], for status display only


class PlanningAgent:
    def __init__(self, provider: AIProvider):
        self.provider = provider

    async def handle_message(self, user_message: str, history: list[dict], db: Session, user_id: str | None = None) -> AgentTurnResult:
        messages = list(history) + [{"role": "user", "content": user_message}]
        tool_trace: list[dict] = []

        for _ in range(MAX_TOOL_ITERATIONS):
            response = await self.provider.create_message(
                system=PLANNING_AGENT_SYSTEM_PROMPT, messages=messages, tools=TOOLS,
            )

            if response.stop_reason != "tool_use" or not response.tool_calls:
                return AgentTurnResult(final_text=response.text, tool_trace=tool_trace)

            messages.append({"role": "assistant", "content": response.raw_content})

            tool_result_blocks = []
            for call in response.tool_calls:
                output = await execute_tool(call.name, call.input, db, user_id)
                tool_trace.append({"tool": call.name, "input": call.input, "output": output})
                tool_result_blocks.append({
                    "type": "tool_result",
                    "tool_use_id": call.id,
                    "content": json.dumps(output, default=str),
                })
            messages.append({"role": "user", "content": tool_result_blocks})

        return AgentTurnResult(
            final_text="I ran out of tool iterations before reaching a final answer. Please narrow the request (fewer tasks or a shorter date range) and try again.",
            tool_trace=tool_trace,
        )
