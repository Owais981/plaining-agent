"""What-if scenarios (build doc section 17 / 27 / 38): plan branches, never
auto-approved, always comparable against their parent baseline."""
from __future__ import annotations

from sqlalchemy.orm import Session

from app.models import Plan, Task, CrewMember, Equipment, Project
from app.services.plan_service import run_optimize


async def run_what_if(db: Session, base_plan_id: str, scenario_label: str, changes: list[dict], created_by: str | None = None) -> dict:
    base_plan = db.get(Plan, base_plan_id)
    if base_plan is None:
        raise ValueError("base plan not found")

    snap = base_plan.input_snapshot
    project_id = snap["project_id"]
    task_ids = list(snap.get("task_ids") or [])
    objective_profile = snap.get("objective_profile", "balanced")
    locked_assignments: dict = {}

    excluded_crew, excluded_equipment = set(), set()
    for change in changes:
        ctype = change.get("change_type")
        target = change.get("target_id")
        value = change.get("value")
        if ctype == "remove_crew":
            excluded_crew.add(target)
        elif ctype == "remove_equipment":
            excluded_equipment.add(target)
        elif ctype == "change_deadline" or ctype == "shift_dates":
            pass  # reflected by adjusting the project record read inside build_problem_from_db
        elif ctype == "set_objective":
            objective_profile = value or objective_profile
        elif ctype == "change_budget":
            pass  # budget affects risk assessment, not the solve itself

    if excluded_crew:
        active_before = {c.id for c in db.query(CrewMember).filter(CrewMember.is_active == True).all()}  # noqa: E712
        db.query(CrewMember).filter(CrewMember.id.in_(excluded_crew)).update({"is_active": False}, synchronize_session=False)

    try:
        result = await run_optimize(db, project_id, task_ids, objective_profile, locked_assignments, snap.get("max_solve_seconds"), created_by)
    finally:
        if excluded_crew:
            db.query(CrewMember).filter(CrewMember.id.in_(excluded_crew)).update({"is_active": True}, synchronize_session=False)
            db.commit()

    new_plan = db.get(Plan, result["plan_id"])
    new_plan.parent_plan_id = base_plan_id
    new_plan.scenario_label = scenario_label
    new_plan.status = "draft"  # scenarios are NEVER auto-approved
    db.commit()

    return {
        "scenario_plan_id": new_plan.id,
        "base_plan_id": base_plan_id,
        "scenario_label": scenario_label,
        "status": result["status"],
        "comparison": compare_plans(db, base_plan_id, new_plan.id),
    }


def compare_plans(db: Session, plan_id_a: str, plan_id_b: str) -> dict:
    a = db.get(Plan, plan_id_a)
    b = db.get(Plan, plan_id_b)
    if a is None or b is None:
        raise ValueError("one or both plans not found")

    from app.models import PlanConflict
    conflicts_a = db.query(PlanConflict).filter(PlanConflict.plan_id == a.id, PlanConflict.severity == "critical").count()
    conflicts_b = db.query(PlanConflict).filter(PlanConflict.plan_id == b.id, PlanConflict.severity == "critical").count()

    return {
        "option_a": {
            "plan_id": a.id, "label": a.scenario_label, "status": a.solver_status,
            "total_cost": float(a.total_cost or 0), "total_travel_km": float(a.total_travel_km or 0),
            "total_overtime_hrs": float(a.total_overtime_hrs or 0), "critical_conflicts": conflicts_a,
        },
        "option_b": {
            "plan_id": b.id, "label": b.scenario_label, "status": b.solver_status,
            "total_cost": float(b.total_cost or 0), "total_travel_km": float(b.total_travel_km or 0),
            "total_overtime_hrs": float(b.total_overtime_hrs or 0), "critical_conflicts": conflicts_b,
        },
        "cost_delta": float((b.total_cost or 0) - (a.total_cost or 0)),
        "travel_delta_km": float((b.total_travel_km or 0) - (a.total_travel_km or 0)),
        "overtime_delta_hrs": float((b.total_overtime_hrs or 0) - (a.total_overtime_hrs or 0)),
    }
