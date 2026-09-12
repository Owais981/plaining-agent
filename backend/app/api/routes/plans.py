import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status, BackgroundTasks
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import get_db
from app.models import Plan, PlanAssignment, PlanTravelLeg, PlanConflict, PlanRisk
from app.jobs.tasks import JOB_STORE, run_job_inprocess, solve_schedule_task, broker_is_reachable
from app.services import plan_service, scenario_service, change_management
from app.security.deps import get_current_user, require_role

router = APIRouter(prefix="/api/v1", tags=["plans"])


class OptimizeRequest(BaseModel):
    project_id: str
    task_ids: list[str] | None = None
    objective_profile: str = "balanced"
    locked_assignments: dict = {}
    max_solve_seconds: int | None = None


@router.post("/plans/optimize", status_code=202)
async def submit_optimization(body: OptimizeRequest, background_tasks: BackgroundTasks, db: Session = Depends(get_db), user=Depends(get_current_user)):
    completeness = await plan_service.check_data_completeness(db, body.project_id)
    if not completeness["complete"]:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail={
            "error": "incomplete_data", "message": completeness["message"], "details": {"missing": completeness["missing"]},
        })

    job_id = str(uuid.uuid4())
    JOB_STORE[job_id] = {"status": "queued", "stage": "queued", "created_at": datetime.now(timezone.utc).isoformat()}

    settings = get_settings()
    if settings.celery_enabled and broker_is_reachable():
        solve_schedule_task.delay(job_id, body.project_id, body.task_ids, body.objective_profile, body.locked_assignments, body.max_solve_seconds, user.id)
        dispatch = "celery"
    else:
        background_tasks.add_task(run_job_inprocess, job_id, body.project_id, body.task_ids, body.objective_profile, body.locked_assignments, body.max_solve_seconds, user.id)
        dispatch = "in_process"

    return {"job_id": job_id, "status": "queued", "dispatch": dispatch, "poll_url": f"/api/v1/jobs/{job_id}"}


@router.get("/jobs/{job_id}")
def get_job(job_id: str):
    job = JOB_STORE.get(job_id)
    if job is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail={"error": "NOT_FOUND", "message": "Job not found"})
    return job


def _get_plan_or_404(db: Session, plan_id: str) -> Plan:
    plan = db.get(Plan, plan_id)
    if plan is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail={"error": "NOT_FOUND", "message": "Plan not found"})
    return plan


@router.get("/plans/{plan_id}")
def get_plan(plan_id: str, db: Session = Depends(get_db)):
    plan = _get_plan_or_404(db, plan_id)
    return {
        "id": plan.id, "project_id": plan.project_id, "version": plan.version,
        "scenario_label": plan.scenario_label, "status": plan.status, "solver_status": plan.solver_status,
        "objective_value": float(plan.objective_value) if plan.objective_value else None,
        "total_cost": float(plan.total_cost) if plan.total_cost else None,
        "total_travel_km": float(plan.total_travel_km) if plan.total_travel_km else None,
        "total_overtime_hrs": float(plan.total_overtime_hrs) if plan.total_overtime_hrs else None,
        "solve_seconds": float(plan.solve_seconds) if plan.solve_seconds else None,
        "parent_plan_id": plan.parent_plan_id, "stale": plan.stale, "created_at": plan.created_at.isoformat(),
    }


@router.get("/plans/{plan_id}/schedule")
def get_schedule(plan_id: str, db: Session = Depends(get_db)):
    _get_plan_or_404(db, plan_id)
    rows = db.query(PlanAssignment).filter(PlanAssignment.plan_id == plan_id).all()
    return [{
        "task_id": r.task_id, "crew_member_id": r.crew_member_id, "equipment_id": r.equipment_id,
        "scheduled_start": r.scheduled_start.isoformat(), "scheduled_end": r.scheduled_end.isoformat(),
        "is_overtime": r.is_overtime, "overtime_minutes": r.overtime_minutes, "assignment_reason": r.assignment_reason,
    } for r in rows]


@router.get("/plans/{plan_id}/crew")
def get_crew_allocation(plan_id: str, db: Session = Depends(get_db)):
    _get_plan_or_404(db, plan_id)
    rows = db.query(PlanAssignment).filter(PlanAssignment.plan_id == plan_id, PlanAssignment.crew_member_id.isnot(None)).all()
    by_crew: dict[str, list] = {}
    for r in rows:
        by_crew.setdefault(r.crew_member_id, []).append({
            "task_id": r.task_id, "start": r.scheduled_start.isoformat(), "end": r.scheduled_end.isoformat(),
            "is_overtime": r.is_overtime, "overtime_minutes": r.overtime_minutes,
        })
    return by_crew


@router.get("/plans/{plan_id}/equipment")
def get_equipment_allocation(plan_id: str, db: Session = Depends(get_db)):
    _get_plan_or_404(db, plan_id)
    rows = db.query(PlanAssignment).filter(PlanAssignment.plan_id == plan_id, PlanAssignment.equipment_id.isnot(None)).all()
    by_equip: dict[str, list] = {}
    for r in rows:
        by_equip.setdefault(r.equipment_id, []).append({
            "task_id": r.task_id, "start": r.scheduled_start.isoformat(), "end": r.scheduled_end.isoformat(),
        })
    return by_equip


@router.get("/plans/{plan_id}/travel")
def get_travel(plan_id: str, db: Session = Depends(get_db)):
    _get_plan_or_404(db, plan_id)
    rows = db.query(PlanTravelLeg).filter(PlanTravelLeg.plan_id == plan_id).all()
    return [{
        "crew_member_id": r.crew_member_id, "from_location_id": r.from_location_id, "to_location_id": r.to_location_id,
        "departure_time": r.departure_time.isoformat(), "arrival_time": r.arrival_time.isoformat(),
        "distance_km": float(r.distance_km), "transport_mode": r.transport_mode,
        "estimated_cost": float(r.estimated_cost) if r.estimated_cost else None,
        "data_source": r.data_source, "confidence": r.confidence,
    } for r in rows]


@router.get("/plans/{plan_id}/costs")
async def get_costs(plan_id: str, db: Session = Depends(get_db)):
    _get_plan_or_404(db, plan_id)
    return await plan_service.calculate_cost_for_plan(db, plan_id)


@router.get("/plans/{plan_id}/conflicts")
def get_conflicts(plan_id: str, db: Session = Depends(get_db)):
    _get_plan_or_404(db, plan_id)
    rows = db.query(PlanConflict).filter(PlanConflict.plan_id == plan_id).all()
    return [{
        "severity": r.severity, "conflict_type": r.conflict_type, "entity_type": r.entity_type,
        "entity_id": r.entity_id, "description": r.description, "suggested_fix": r.suggested_fix,
    } for r in rows]


@router.get("/plans/{plan_id}/risks")
def get_risks(plan_id: str, db: Session = Depends(get_db)):
    _get_plan_or_404(db, plan_id)
    rows = db.query(PlanRisk).filter(PlanRisk.plan_id == plan_id).all()
    return [{
        "risk_type": r.risk_type, "severity": r.severity, "entity_type": r.entity_type,
        "entity_id": r.entity_id, "description": r.description, "mitigation": r.mitigation,
    } for r in rows]


@router.post("/plans/{plan_id}/approve")
def approve(plan_id: str, db: Session = Depends(get_db), user=Depends(require_role("approver"))):
    try:
        return plan_service.approve_plan(db, plan_id, user.id)
    except ValueError as e:
        raise HTTPException(status.HTTP_409_CONFLICT, detail={"error": "APPROVAL_BLOCKED", "message": str(e)})


class ChangeRequest(BaseModel):
    changes: list[dict]


@router.post("/plans/{plan_id}/changes")
async def post_change(plan_id: str, body: ChangeRequest, db: Session = Depends(get_db), user=Depends(require_role("editor"))):
    try:
        return await change_management.apply_change(db, plan_id, body.changes, user.id)
    except ValueError as e:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail={"error": "NOT_FOUND", "message": str(e)})


class ScenarioRequest(BaseModel):
    scenario_label: str = "scenario"
    changes: list[dict]


@router.post("/plans/{plan_id}/scenarios")
async def post_scenario(plan_id: str, body: ScenarioRequest, db: Session = Depends(get_db), user=Depends(require_role("editor"))):
    try:
        return await scenario_service.run_what_if(db, plan_id, body.scenario_label, body.changes, user.id)
    except ValueError as e:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail={"error": "NOT_FOUND", "message": str(e)})


@router.get("/plans/{plan_id}/compare/{other_id}")
def compare(plan_id: str, other_id: str, db: Session = Depends(get_db)):
    try:
        return scenario_service.compare_plans(db, plan_id, other_id)
    except ValueError as e:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail={"error": "NOT_FOUND", "message": str(e)})
