"""Tool schemas + dispatcher (build doc section 21-29 / 31). The agent
decides WHICH tool to call; every tool body here is plain deterministic
Python calling into app.services / app.optimization / app.conflicts /
app.costs / app.risks. Inputs are validated with Pydantic before any
service function runs -- tool arguments from the LLM are never trusted
blindly."""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, ValidationError
from sqlalchemy.orm import Session

from app.services import plan_service, change_management, scenario_service

TOOLS: list[dict] = [
    {
        "name": "check_data_completeness",
        "description": (
            "Check whether the request contains enough information to run optimization. "
            "Always call this FIRST, before any optimization. Returns the minimum set of "
            "missing items needed to produce a useful plan."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "project_id": {"type": "string"},
                "date_range": {"type": "object", "properties": {"start": {"type": "string"}, "end": {"type": "string"}}},
                "location_ids": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["project_id"],
        },
    },
    {
        "name": "query_resources",
        "description": (
            "Query REAL crew and equipment availability from the database. This is the ONLY "
            "source of truth for availability, skills, certifications, rates and maintenance "
            "windows. Never state availability that did not come from this tool."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "resource_type": {"type": "string", "enum": ["crew", "equipment"]},
                "date_range": {"type": "object", "properties": {"start": {"type": "string"}, "end": {"type": "string"}}, "required": ["start", "end"]},
                "required_skills": {"type": "array", "items": {"type": "string"}},
                "required_certifications": {"type": "array", "items": {"type": "string"}},
                "near_location_id": {"type": "string"},
                "max_distance_km": {"type": "number"},
            },
            "required": ["resource_type", "date_range"],
        },
    },
    {
        "name": "optimize_schedule",
        "description": (
            "Run the CP-SAT constraint solver to produce an optimal assignment of crew, "
            "equipment and travel. Returns a plan, or an infeasibility report naming the "
            "constraints that clash. Never construct a schedule yourself -- always call this."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "project_id": {"type": "string"},
                "task_ids": {"type": "array", "items": {"type": "string"}},
                "objective_profile": {"type": "string", "enum": ["balanced", "minimize_cost", "minimize_travel", "minimize_overtime", "earliest_finish"]},
                "locked_assignments": {"type": "object"},
                "max_solve_seconds": {"type": "integer"},
            },
            "required": ["project_id"],
        },
    },
    {
        "name": "detect_conflicts",
        "description": "Run the independent conflict-detection pass over a plan. Must be run on every plan before it is presented.",
        "input_schema": {"type": "object", "properties": {"plan_id": {"type": "string"}}, "required": ["plan_id"]},
    },
    {
        "name": "calculate_cost",
        "description": "Compute the full deterministic cost breakdown for a plan: labour, overtime, equipment, fuel, transport, tolls, accommodation.",
        "input_schema": {"type": "object", "properties": {"plan_id": {"type": "string"}}, "required": ["plan_id"]},
    },
    {
        "name": "run_what_if",
        "description": "Create a scenario branch from an existing plan with a change applied, re-solve it, and return a comparison against the baseline.",
        "input_schema": {
            "type": "object",
            "properties": {
                "base_plan_id": {"type": "string"},
                "scenario_label": {"type": "string"},
                "changes": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "change_type": {"type": "string", "enum": ["remove_crew", "remove_equipment", "shift_dates", "change_budget", "add_location", "change_deadline", "set_objective"]},
                            "target_id": {"type": "string"},
                            "value": {"type": "string"},
                        },
                    },
                },
            },
            "required": ["base_plan_id", "changes"],
        },
    },
    {
        "name": "apply_change",
        "description": "Apply a change to an approved plan and re-solve ONLY the affected portion, preserving unaffected assignments.",
        "input_schema": {
            "type": "object",
            "properties": {
                "plan_id": {"type": "string"},
                "changes": {"type": "array", "items": {"type": "object"}},
            },
            "required": ["plan_id", "changes"],
        },
    },
    {
        "name": "assess_risks",
        "description": "Identify operational risks in a plan: single points of failure, resource shortages, deadline exposure, budget exposure, maintenance risk.",
        "input_schema": {"type": "object", "properties": {"plan_id": {"type": "string"}}, "required": ["plan_id"]},
    },
]


class CheckCompletenessInput(BaseModel):
    project_id: str
    date_range: dict | None = None
    location_ids: list[str] | None = None


class QueryResourcesInput(BaseModel):
    resource_type: Literal["crew", "equipment"]
    date_range: dict
    required_skills: list[str] = Field(default_factory=list)
    required_certifications: list[str] = Field(default_factory=list)
    near_location_id: str | None = None
    max_distance_km: float | None = None


class OptimizeInput(BaseModel):
    project_id: str
    task_ids: list[str] | None = None
    objective_profile: str = "balanced"
    locked_assignments: dict = Field(default_factory=dict)
    max_solve_seconds: int | None = None


class PlanIdInput(BaseModel):
    plan_id: str


class WhatIfInput(BaseModel):
    base_plan_id: str
    scenario_label: str = "scenario"
    changes: list[dict] = Field(default_factory=list)


class ApplyChangeInput(BaseModel):
    plan_id: str
    changes: list[dict] = Field(default_factory=list)


async def execute_tool(name: str, raw_input: dict, db: Session, user_id: str | None = None) -> dict[str, Any]:
    try:
        if name == "check_data_completeness":
            args = CheckCompletenessInput(**raw_input)
            return await plan_service.check_data_completeness(db, args.project_id, args.date_range, args.location_ids)

        if name == "query_resources":
            args = QueryResourcesInput(**raw_input)
            return {"resources": plan_service.query_resources(
                db, args.resource_type, args.date_range, args.required_skills,
                args.required_certifications, args.near_location_id, args.max_distance_km,
            )}

        if name == "optimize_schedule":
            args = OptimizeInput(**raw_input)
            return await plan_service.run_optimize(
                db, args.project_id, args.task_ids, args.objective_profile,
                args.locked_assignments, args.max_solve_seconds, user_id,
            )

        if name == "detect_conflicts":
            args = PlanIdInput(**raw_input)
            conflicts = await plan_service.detect_conflicts_for_plan(db, args.plan_id)
            return {"plan_id": args.plan_id, "conflicts": conflicts, "critical_count": sum(1 for c in conflicts if c["severity"] == "critical")}

        if name == "calculate_cost":
            args = PlanIdInput(**raw_input)
            return await plan_service.calculate_cost_for_plan(db, args.plan_id)

        if name == "run_what_if":
            args = WhatIfInput(**raw_input)
            return await scenario_service.run_what_if(db, args.base_plan_id, args.scenario_label, args.changes, user_id)

        if name == "apply_change":
            args = ApplyChangeInput(**raw_input)
            return await change_management.apply_change(db, args.plan_id, args.changes, user_id)

        if name == "assess_risks":
            args = PlanIdInput(**raw_input)
            return {"plan_id": raw_input.get("plan_id"), "risks": await plan_service.assess_risks_for_plan(db, raw_input["plan_id"])}

        return {"error": f"unknown tool: {name}"}
    except ValidationError as e:
        return {"error": "invalid_tool_arguments", "details": e.errors()}
    except Exception as e:  # noqa: BLE001
        return {"error": "tool_execution_failed", "message": str(e)}
