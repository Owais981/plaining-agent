"""Tests for the agent's tool dispatch layer (build doc section 31: 'Do not
trust LLM-generated tool arguments blindly') and the orchestration loop
mechanics (build doc section 8/31). These test OUR harness code, not the
model's judgement -- verifying the model itself never invents facts
requires live API calls against ANTHROPIC_API_KEY and is a manual/CI-with-
key check (see README known limitations)."""
import asyncio

import pytest

from app.ai.base import AIProvider, ProviderResponse, ToolCall
from app.ai.agent import PlanningAgent
from app.ai.tools import execute_tool


def test_invalid_tool_arguments_are_rejected_not_crashed(db_session=None):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from app.database import Base

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()

    result = asyncio.run(execute_tool("optimize_schedule", {"objective_profile": "not_a_real_profile"}, db))
    assert result["error"] == "invalid_tool_arguments"


def test_unknown_tool_name_returns_error_not_exception():
    result = asyncio.run(execute_tool("delete_everything", {}, db=None))
    assert result["error"] == "unknown tool: delete_everything"


class _StubProviderCallsToolThenStops(AIProvider):
    """Simulates: Claude calls check_data_completeness, gets a result, then
    answers in plain text without calling optimize_schedule (e.g. because
    the project has no tasks yet) -- verifying the loop terminates cleanly
    and never fabricates a schedule of its own."""

    def __init__(self):
        self.calls = 0

    async def create_message(self, system, messages, tools, max_tokens=4096):
        self.calls += 1
        if self.calls == 1:
            return ProviderResponse(
                stop_reason="tool_use", text="",
                tool_calls=[ToolCall(id="call-1", name="check_data_completeness", input={"project_id": "does-not-exist"})],
                raw_content=[{"type": "tool_use", "id": "call-1", "name": "check_data_completeness", "input": {"project_id": "does-not-exist"}}],
            )
        return ProviderResponse(stop_reason="end_turn", text="I need a valid project before I can plan anything.", tool_calls=[])


def test_agent_loop_calls_tool_then_returns_final_text():
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from app.database import Base

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()

    agent = PlanningAgent(_StubProviderCallsToolThenStops())
    result = asyncio.run(agent.handle_message("Plan my project", [], db))

    assert result.final_text == "I need a valid project before I can plan anything."
    assert len(result.tool_trace) == 1
    assert result.tool_trace[0]["tool"] == "check_data_completeness"
    assert result.tool_trace[0]["output"]["complete"] is False


class _StubProviderNeverStopsCallingTools(AIProvider):
    """Adversarial case: a provider that never terminates the tool loop.
    The orchestrator must bail out after MAX_TOOL_ITERATIONS rather than
    looping forever or crashing."""

    async def create_message(self, system, messages, tools, max_tokens=4096):
        return ProviderResponse(
            stop_reason="tool_use", text="",
            tool_calls=[ToolCall(id="x", name="check_data_completeness", input={"project_id": "p"})],
            raw_content=[{"type": "tool_use", "id": "x", "name": "check_data_completeness", "input": {"project_id": "p"}}],
        )


def test_agent_loop_terminates_even_if_model_never_stops():
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from app.database import Base

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()

    agent = PlanningAgent(_StubProviderNeverStopsCallingTools())
    result = asyncio.run(agent.handle_message("Plan forever", [], db))
    assert "ran out of tool iterations" in result.final_text
