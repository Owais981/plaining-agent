"""Localized re-solving (build doc section 10 / 28 / 37). A change ripples
outward from its seed task to dependents and anyone sharing a resource or a
travel chain with it; everything outside that affected set is pinned via
`locked_assignments` and the solver is warm-started from the previous plan
so it converges fast and produces a plan that looks similar to the old one."""
from __future__ import annotations

from sqlalchemy.orm import Session

from app.models import Plan, PlanAssignment, TaskDependency
from app.services.plan_service import run_optimize, rebuild_problem_and_result
from app.conflicts.engine import detect_conflicts as run_conflict_rules


def compute_affected_set(db: Session, plan: Plan, changes: list[dict]) -> set[str]:
    assignments = db.query(PlanAssignment).filter(PlanAssignment.plan_id == plan.id).all()
    by_task = {a.task_id: a for a in assignments}
    task_ids = list(by_task.keys())

    deps = db.query(TaskDependency).filter(
        TaskDependency.predecessor_id.in_(task_ids) | TaskDependency.successor_id.in_(task_ids)
    ).all()
    successors: dict[str, list[str]] = {}
    for d in deps:
        successors.setdefault(d.predecessor_id, []).append(d.successor_id)

    seed = set()
    for change in changes:
        target = change.get("target_task_id") or change.get("target_id")
        if target:
            seed.add(target)

    affected = set(seed)
    frontier = set(seed)
    while frontier:
        nxt = set()
        for task_id in frontier:
            nxt |= set(successors.get(task_id, []))
            assignment = by_task.get(task_id)
            if assignment:
                for other in assignments:
                    if other.task_id == task_id:
                        continue
                    if assignment.crew_member_id and other.crew_member_id == assignment.crew_member_id:
                        nxt.add(other.task_id)
                    if assignment.equipment_id and other.equipment_id == assignment.equipment_id:
                        nxt.add(other.task_id)
        nxt -= affected
        frontier = nxt
        affected |= nxt
    return affected


async def apply_change(db: Session, plan_id: str, changes: list[dict], created_by: str | None = None) -> dict:
    plan = db.get(Plan, plan_id)
    if plan is None:
        raise ValueError("plan not found")

    affected = compute_affected_set(db, plan, changes)
    assignments = db.query(PlanAssignment).filter(PlanAssignment.plan_id == plan.id).all()

    locked_assignments = {}
    for a in assignments:
        if a.task_id in affected:
            continue
        locked_assignments[a.task_id] = {"crew_member_id": a.crew_member_id, "equipment_id": a.equipment_id}

    for change in changes:
        if change.get("change_type") == "remove_crew":
            locked_assignments = {k: v for k, v in locked_assignments.items() if v.get("crew_member_id") != change.get("target_id")}

    snap = plan.input_snapshot
    task_ids = snap.get("task_ids")

    new_result = await run_optimize(
        db, plan.project_id, task_ids, snap.get("objective_profile", "balanced"),
        locked_assignments, snap.get("max_solve_seconds"), created_by,
    )
    new_plan_id = new_result["plan_id"]
    new_assignments = db.query(PlanAssignment).filter(PlanAssignment.plan_id == new_plan_id).all()

    old_by_task = {a.task_id: (a.crew_member_id, a.equipment_id) for a in assignments}
    new_by_task = {a.task_id: (a.crew_member_id, a.equipment_id) for a in new_assignments}
    changed_tasks = [tid for tid in new_by_task if old_by_task.get(tid) != new_by_task.get(tid)]

    new_plan = db.get(Plan, new_plan_id)
    cost_delta = float((new_plan.total_cost or 0) - (plan.total_cost or 0))

    return {
        "what_changed": changes,
        "affected_tasks": sorted(affected),
        "new_plan_id": new_plan_id,
        "changed_assignments": changed_tasks,
        "unchanged_task_count": len(new_by_task) - len(changed_tasks),
        "cost_delta": cost_delta,
        "status": new_result["status"],
    }
