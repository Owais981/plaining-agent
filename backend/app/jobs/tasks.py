"""Async solve execution (build doc section 3/33): FastAPI -> Celery ->
Redis -> solver worker in production. A solver run on a realistic problem
takes 10-120 seconds and must never block an HTTP request.

This module provides two execution paths behind the same job-status
contract:
  * `solve_schedule_task` -- a real Celery task, used when CELERY_BROKER
    (redis) is reachable. This is the documented production path.
  * `run_job_inprocess` -- an asyncio-based fallback used by the API layer
    when no broker is reachable (e.g. local dev without Redis running).
    It updates the same JOB_STORE so the polling contract is identical.

Job state lives in JOB_STORE, an in-memory dict. This is fine for a single
backend process (dev/demo); a production deployment with multiple API
workers should read job state from Celery's result backend instead --
noted in README as a known limitation of the in-process fallback.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from app.database import SessionLocal
from app.jobs.celery_app import celery_app
from app.services import plan_service

JOB_STORE: dict[str, dict] = {}


def _set_job(job_id: str, **fields):
    JOB_STORE.setdefault(job_id, {}).update(fields)


async def _execute(job_id: str, project_id: str, task_ids, objective_profile, locked_assignments, max_solve_seconds, user_id):
    _set_job(job_id, status="running", stage="validating_planning_data", updated_at=datetime.now(timezone.utc).isoformat())
    db = SessionLocal()
    try:
        _set_job(job_id, stage="building_travel_matrix")
        result = await plan_service.run_optimize(db, project_id, task_ids, objective_profile, locked_assignments, max_solve_seconds, user_id)
        plan_id = result["plan_id"]
        _set_job(job_id, stage="verifying_conflicts", plan_id=plan_id)
        if result["status"] in ("OPTIMAL", "FEASIBLE"):
            _set_job(job_id, stage="assessing_risks")
            await plan_service.assess_risks_for_plan(db, plan_id)
        _set_job(job_id, status="done", stage="complete", result=result, updated_at=datetime.now(timezone.utc).isoformat())
    except Exception as e:  # noqa: BLE001
        _set_job(job_id, status="error", stage="failed", error=str(e), updated_at=datetime.now(timezone.utc).isoformat())
    finally:
        db.close()


async def run_job_inprocess(job_id: str, project_id: str, task_ids, objective_profile, locked_assignments, max_solve_seconds, user_id):
    await _execute(job_id, project_id, task_ids, objective_profile, locked_assignments, max_solve_seconds, user_id)


@celery_app.task(name="planning_agent.solve_schedule")
def solve_schedule_task(job_id: str, project_id: str, task_ids, objective_profile, locked_assignments, max_solve_seconds, user_id):
    asyncio.run(_execute(job_id, project_id, task_ids, objective_profile, locked_assignments, max_solve_seconds, user_id))
    return JOB_STORE.get(job_id)


def broker_is_reachable() -> bool:
    try:
        conn = celery_app.connection()
        conn.ensure_connection(max_retries=1, timeout=0.5)
        conn.close()
        return True
    except Exception:  # noqa: BLE001
        return False
