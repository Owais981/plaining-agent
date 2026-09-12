"""Deterministic services backing both the REST API and the agent's tools.
Nothing in this module is LLM-driven -- it is the "VALIDATION / ROUTING /
OR-TOOLS / CONFLICT DETECTION / COST + RISK" spine of the architecture
diagram at the end of the build prompt."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.models import (
    Project, Task, TaskCrewRequirement, TaskEquipmentRequirement, CrewMember, CrewSkill,
    CrewCertification, CrewAvailability, Equipment, EquipmentAvailability, Plan, PlanAssignment,
    PlanTravelLeg, PlanConflict, PlanRisk, Location,
)
from app.optimization.build_problem import build_problem_from_db, _as_utc
from app.optimization.solver import solve_with_explanation, SolveResult
from app.optimization.problem import SchedulingProblem
from app.conflicts.engine import detect_conflicts as run_conflict_rules
from app.costs.engine import calculate_cost as run_cost_calc
from app.risks.engine import assess_risks as run_risk_rules


class DataIncompleteError(Exception):
    def __init__(self, missing: list[str], message: str):
        self.missing = missing[:4]
        self.message = message
        super().__init__(message)


async def check_data_completeness(db: Session, project_id: str, date_range: dict | None = None, location_ids: list[str] | None = None) -> dict:
    project = db.get(Project, project_id)
    if project is None:
        return {"complete": False, "missing": ["a valid project_id"], "warnings": []}

    missing, warnings = [], []
    tasks = db.query(Task).filter(Task.project_id == project_id).all()
    if not tasks:
        missing.append("at least one task for this project")
    else:
        no_duration = [t.id for t in tasks if not t.duration_minutes]
        no_window = [t.id for t in tasks if not t.earliest_start or not t.latest_finish]
        no_crew_req = [t.id for t in tasks if not db.query(TaskCrewRequirement).filter(TaskCrewRequirement.task_id == t.id).first()]
        if no_duration:
            missing.append(f"task durations for {len(no_duration)} task(s)")
        if no_window:
            missing.append(f"earliest_start/latest_finish windows for {len(no_window)} task(s)")
        if no_crew_req:
            warnings.append(f"{len(no_crew_req)} task(s) have no crew requirement defined")

    active_crew = db.query(CrewMember).filter(CrewMember.is_active == True).count()  # noqa: E712
    if active_crew == 0:
        missing.append("at least one active crew member in the system")

    active_equipment = db.query(Equipment).filter(Equipment.is_active == True).count()  # noqa: E712
    if active_equipment == 0 and any(
        db.query(TaskEquipmentRequirement).filter(TaskEquipmentRequirement.task_id == t.id).first() for t in tasks
    ):
        missing.append("at least one active equipment asset for the equipment requirements defined")

    complete = len(missing) == 0
    message = "Ready to optimize." if complete else "Missing information required before optimization can run."
    return {"complete": complete, "missing": missing[:4], "warnings": warnings, "message": message}


def query_resources(
    db: Session,
    resource_type: str,
    date_range: dict,
    required_skills: list[str] | None = None,
    required_certifications: list[str] | None = None,
    near_location_id: str | None = None,
    max_distance_km: float | None = None,
) -> list[dict]:
    """THE source of truth for availability/skills/certs/rates/maintenance.
    Every fact returned here came straight from the database -- never from
    model reasoning (build doc section 23)."""
    start = datetime.fromisoformat(date_range["start"]).replace(tzinfo=timezone.utc)
    end = datetime.fromisoformat(date_range["end"]).replace(tzinfo=timezone.utc)

    if resource_type == "crew":
        q = db.query(CrewMember).filter(CrewMember.is_active == True)  # noqa: E712
        out = []
        for c in q.all():
            windows = db.query(CrewAvailability).filter(
                CrewAvailability.crew_member_id == c.id,
                CrewAvailability.availability_type == "available",
                CrewAvailability.starts_at <= end, CrewAvailability.ends_at >= start,
            ).all()
            if not windows:
                continue
            skill_ids = {s.skill_id for s in db.query(CrewSkill).filter(CrewSkill.crew_member_id == c.id).all()}
            if required_skills and not set(required_skills).issubset(skill_ids):
                continue
            certs = db.query(CrewCertification).filter(CrewCertification.crew_member_id == c.id).all()
            cert_map = {cert.certification_id: cert.expiry_date for cert in certs}
            if required_certifications:
                ok = all(cid in cert_map and (cert_map[cid] is None or cert_map[cid] >= end.date()) for cid in required_certifications)
                if not ok:
                    continue
            out.append({
                "id": c.id, "employee_code": c.employee_code, "full_name": c.full_name,
                "role_id": c.primary_role_id, "standard_rate": float(c.standard_rate),
                "overtime_rate": float(c.overtime_rate), "skills": list(skill_ids),
                "certifications": [{"id": cid, "expiry": str(exp) if exp else None} for cid, exp in cert_map.items()],
                "available_windows": [[str(w.starts_at), str(w.ends_at)] for w in windows],
            })
        return out

    if resource_type == "equipment":
        q = db.query(Equipment).filter(Equipment.is_active == True)  # noqa: E712
        out = []
        for e in q.all():
            windows = db.query(EquipmentAvailability).filter(
                EquipmentAvailability.equipment_id == e.id,
                EquipmentAvailability.availability_type == "available",
                EquipmentAvailability.starts_at <= end, EquipmentAvailability.ends_at >= start,
            ).all()
            if not windows:
                continue
            out.append({
                "id": e.id, "asset_code": e.asset_code, "name": e.name, "category_id": e.category_id,
                "capacity_value": float(e.capacity_value) if e.capacity_value else None,
                "daily_operating_cost": float(e.daily_operating_cost or 0),
                "ownership": e.ownership,
                "available_windows": [[str(w.starts_at), str(w.ends_at)] for w in windows],
            })
        return out

    raise ValueError(f"unknown resource_type: {resource_type}")


async def run_optimize(
    db: Session, project_id: str, task_ids: list[str] | None, objective_profile: str = "balanced",
    locked_assignments: dict | None = None, max_solve_seconds: int | None = None, created_by: str | None = None,
) -> dict:
    problem = await build_problem_from_db(db, project_id, task_ids, objective_profile, locked_assignments, max_solve_seconds)
    result, infeasibility = solve_with_explanation(problem)

    version = (db.query(Plan).filter(Plan.project_id == project_id).count()) + 1
    plan = Plan(
        project_id=project_id, version=version, scenario_label="baseline" if version == 1 else f"v{version}",
        status="draft", solver_status=result.status,
        objective_value=result.objective_value, solve_seconds=result.solve_seconds,
        input_snapshot={
            "project_id": project_id, "task_ids": task_ids or [t.id for t in problem.tasks],
            "objective_profile": objective_profile, "locked_assignments": locked_assignments or {},
            "max_solve_seconds": problem.max_solve_seconds, "solver_seed": problem.random_seed,
            "generated_at": datetime.now(timezone.utc).isoformat(),
        },
        created_by=created_by,
    )
    db.add(plan)
    db.flush()

    if result.status in ("OPTIMAL", "FEASIBLE"):
        _persist_assignments(db, plan, problem, result)
        cost = run_cost_calc(problem, result)
        plan.total_cost = cost.total
        plan.total_overtime_hrs = round(sum((result.overtime_minutes or {}).values()) / 60, 2)
        plan.total_travel_km = round(sum(leg.distance_km for leg in problem.travel_matrix.legs.values()), 2)
        db.flush()
        _persist_conflicts(db, plan, problem, result)
        db.commit()
        return {
            "plan_id": plan.id, "status": result.status, "objective_value": result.objective_value,
            "solve_seconds": result.solve_seconds, "total_cost": cost.total,
            "schedule": _schedule_dict(problem, result),
        }

    db.commit()
    return {
        "plan_id": plan.id, "status": result.status,
        "blocking_constraints": result.blocking_constraints or [],
        "suggestions": infeasibility.suggestions() if infeasibility else [],
    }


def _schedule_dict(problem: SchedulingProblem, result: SolveResult) -> list[dict]:
    out = []
    for task in problem.tasks:
        sched = result.task_schedule.get(task.id) if result.task_schedule else None
        if not sched:
            continue
        start, end = sched
        out.append({
            "task_id": task.id,
            "start_offset_minutes": start, "end_offset_minutes": end,
            "start": (problem.horizon_start + timedelta(minutes=start)).isoformat(),
            "end": (problem.horizon_start + timedelta(minutes=end)).isoformat(),
            "crew": (result.crew_assignments or {}).get(task.id, []),
            "equipment": (result.equipment_assignments or {}).get(task.id, []),
        })
    return out


def _persist_assignments(db: Session, plan: Plan, problem: SchedulingProblem, result: SolveResult):
    crew_by_id = {c.id: c for c in problem.crew}
    overtime_by_crew_day: dict[str, int] = dict(result.overtime_minutes or {})
    for task in problem.tasks:
        sched = result.task_schedule.get(task.id)
        if not sched:
            continue
        start, end = sched
        start_dt = problem.horizon_start + timedelta(minutes=start)
        end_dt = problem.horizon_start + timedelta(minutes=end)
        crew_ids = (result.crew_assignments or {}).get(task.id, []) or [None]
        equip_ids = (result.equipment_assignments or {}).get(task.id, []) or [None]
        for cid in crew_ids:
            reason_parts = []
            if cid:
                crew = crew_by_id.get(cid)
                if crew:
                    reason_parts.append(f"role matches task requirement ({crew.role_id})")
                    reason_parts.append("available during the task window")
                    if crew.certifications:
                        reason_parts.append("holds required certification(s), valid through the task date")
            is_ot = bool(cid and overtime_by_crew_day.get(cid, 0) > 0)
            db.add(PlanAssignment(
                plan_id=plan.id, task_id=task.id, crew_member_id=cid,
                equipment_id=equip_ids[0] if equip_ids else None,
                scheduled_start=start_dt, scheduled_end=end_dt,
                is_overtime=is_ot, overtime_minutes=overtime_by_crew_day.get(cid, 0) if cid else 0,
                assignment_reason="; ".join(reason_parts) or "assigned by solver as optimal for stated constraints",
            ))
        for eid in equip_ids[1:] if len(equip_ids) > 1 else []:
            db.add(PlanAssignment(
                plan_id=plan.id, task_id=task.id, crew_member_id=None, equipment_id=eid,
                scheduled_start=start_dt, scheduled_end=end_dt,
                assignment_reason="additional equipment unit assigned by solver",
            ))

    _persist_travel_legs(db, plan, problem, result)


def _persist_travel_legs(db: Session, plan: Plan, problem: SchedulingProblem, result: SolveResult):
    """Derive one travel leg per crew member per consecutive pair of
    different-location tasks, straight from the same travel matrix the
    solver used for its C9 feasibility constraint -- never recomputed or
    guessed independently."""
    by_crew: dict[str, list] = {}
    for task in problem.tasks:
        sched = result.task_schedule.get(task.id)
        if not sched:
            continue
        for cid in (result.crew_assignments or {}).get(task.id, []):
            by_crew.setdefault(cid, []).append((task, sched))

    for cid, items in by_crew.items():
        ordered = sorted(items, key=lambda x: x[1][0])
        for (task_a, (_, end_a)), (task_b, (start_b, _)) in zip(ordered, ordered[1:]):
            if task_a.location_id == task_b.location_id:
                continue
            try:
                leg = problem.travel_matrix.get(task_a.location_id, task_b.location_id)
            except KeyError:
                continue
            db.add(PlanTravelLeg(
                plan_id=plan.id, crew_member_id=cid, equipment_id=None,
                from_location_id=task_a.location_id, to_location_id=task_b.location_id,
                departure_time=problem.horizon_start + timedelta(minutes=end_a),
                arrival_time=problem.horizon_start + timedelta(minutes=start_b),
                distance_km=leg.distance_km, transport_mode="road",
                estimated_cost=leg.cost, data_source=leg.data_source, confidence=leg.confidence,
            ))


def _persist_conflicts(db: Session, plan: Plan, problem: SchedulingProblem, result: SolveResult):
    conflicts = run_conflict_rules(problem, result)
    for c in conflicts:
        db.add(PlanConflict(
            plan_id=plan.id, severity=c.severity, conflict_type=c.conflict_type,
            entity_type=c.entity_type, entity_id=c.entity_id, description=c.description,
            suggested_fix=c.suggested_fix,
        ))
    db.commit()


async def rebuild_problem_and_result(db: Session, plan: Plan) -> tuple[SchedulingProblem, SolveResult]:
    """Reconstruct the exact problem from a Plan's input_snapshot (build doc
    section 4: reproducibility via input_snapshot) and replay its
    persisted assignments as the "result" for conflict/cost/risk re-checks."""
    snap = plan.input_snapshot
    problem = await build_problem_from_db(
        db, snap["project_id"], snap.get("task_ids"), snap.get("objective_profile", "balanced"),
        snap.get("locked_assignments"), snap.get("max_solve_seconds"),
    )
    assignments = db.query(PlanAssignment).filter(PlanAssignment.plan_id == plan.id).all()
    task_schedule, crew_assignments, equipment_assignments = {}, {}, {}
    for a in assignments:
        start_off = int((_as_utc(a.scheduled_start) - _as_utc(problem.horizon_start)).total_seconds() // 60)
        end_off = int((_as_utc(a.scheduled_end) - _as_utc(problem.horizon_start)).total_seconds() // 60)
        task_schedule[a.task_id] = (start_off, end_off)
        # A task with N crew and M equipment units (N != M) produces one
        # PlanAssignment row per crew member, each carrying the same
        # equipment_id (see _persist_assignments) -- so the same crew or
        # equipment id can legitimately repeat across rows for one task.
        # Dedupe here so it reconstructs back to "used once", not an
        # inflated count that reads as a double-booking to the conflict engine.
        if a.crew_member_id and a.crew_member_id not in crew_assignments.setdefault(a.task_id, []):
            crew_assignments[a.task_id].append(a.crew_member_id)
        if a.equipment_id and a.equipment_id not in equipment_assignments.setdefault(a.task_id, []):
            equipment_assignments[a.task_id].append(a.equipment_id)
    overtime = {}
    for a in assignments:
        if a.crew_member_id and a.overtime_minutes:
            overtime[a.crew_member_id] = overtime.get(a.crew_member_id, 0) + a.overtime_minutes
    result = SolveResult(
        status=plan.solver_status or "FEASIBLE", objective_value=float(plan.objective_value) if plan.objective_value else None,
        task_schedule=task_schedule, crew_assignments=crew_assignments,
        equipment_assignments=equipment_assignments, overtime_minutes=overtime,
        solve_seconds=float(plan.solve_seconds or 0),
    )
    return problem, result


async def detect_conflicts_for_plan(db: Session, plan_id: str) -> list[dict]:
    plan = db.get(Plan, plan_id)
    if plan is None:
        raise ValueError("plan not found")
    problem, result = await rebuild_problem_and_result(db, plan)
    conflicts = run_conflict_rules(problem, result)
    db.query(PlanConflict).filter(PlanConflict.plan_id == plan_id).delete()
    for c in conflicts:
        db.add(PlanConflict(
            plan_id=plan_id, severity=c.severity, conflict_type=c.conflict_type,
            entity_type=c.entity_type, entity_id=c.entity_id, description=c.description,
            suggested_fix=c.suggested_fix,
        ))
    db.commit()
    return [c.__dict__ for c in conflicts]


async def calculate_cost_for_plan(db: Session, plan_id: str) -> dict:
    plan = db.get(Plan, plan_id)
    if plan is None:
        raise ValueError("plan not found")
    problem, result = await rebuild_problem_and_result(db, plan)
    breakdown = run_cost_calc(problem, result)
    plan.total_cost = breakdown.total
    db.commit()
    return breakdown.__dict__


async def assess_risks_for_plan(db: Session, plan_id: str) -> list[dict]:
    plan = db.get(Plan, plan_id)
    if plan is None:
        raise ValueError("plan not found")
    problem, result = await rebuild_problem_and_result(db, plan)
    project = db.get(Project, plan.project_id)
    breakdown = run_cost_calc(problem, result)
    risks = run_risk_rules(problem, result, float(project.budget_total) if project and project.budget_total else None, breakdown.total)
    db.query(PlanRisk).filter(PlanRisk.plan_id == plan_id).delete()
    for r in risks:
        db.add(PlanRisk(
            plan_id=plan_id, risk_type=r.risk_type, severity=r.severity,
            entity_type=r.entity_type, entity_id=r.entity_id, description=r.description, mitigation=r.mitigation,
        ))
    db.commit()
    return [r.__dict__ for r in risks]


def has_critical_conflicts(db: Session, plan_id: str) -> bool:
    return db.query(PlanConflict).filter(PlanConflict.plan_id == plan_id, PlanConflict.severity == "critical").count() > 0


def approve_plan(db: Session, plan_id: str, user_id: str | None) -> dict:
    """Rule 4 (build doc section 51): no critical conflict means no
    approval. Enforced here in application logic AND via a DB CHECK-style
    guard (see approved_plans_no_critical_conflicts note in the Alembic
    migration) so this can never be bypassed by a direct DB write alone."""
    plan = db.get(Plan, plan_id)
    if plan is None:
        raise ValueError("plan not found")
    if plan.solver_status == "INFEASIBLE":
        raise ValueError("cannot approve an infeasible plan")
    if has_critical_conflicts(db, plan_id):
        raise ValueError("cannot approve a plan with unresolved critical conflicts")
    plan.status = "approved"
    plan.approved_by = user_id
    plan.approved_at = datetime.now(timezone.utc)
    db.query(Plan).filter(
        Plan.project_id == plan.project_id, Plan.id != plan.id, Plan.status == "approved"
    ).update({"status": "superseded"})
    db.commit()
    return {"plan_id": plan.id, "status": plan.status, "approved_at": plan.approved_at.isoformat()}
