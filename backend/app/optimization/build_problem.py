from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.models import (
    Task, TaskDependency, TaskCrewRequirement, TaskEquipmentRequirement,
    CrewMember, CrewSkill, CrewCertification, CrewAvailability,
    Equipment, EquipmentAvailability, EquipmentMaintenance, Location, Project,
)
from app.optimization.problem import (
    SchedulingProblem, TaskDef, CrewDef, EquipmentDef, Dependency,
    CrewRequirement, EquipmentRequirement, Certification, TravelMatrix, TravelLeg,
    weights_for_profile,
)
from app.optimization.weights import load_default_weights
from app.routing.base import Coordinate
from app.routing.service import RoutingService


def _as_utc(dt: datetime) -> datetime:
    """SQLite does not preserve tzinfo on TIMESTAMPTZ-equivalent columns
    (values come back naive), while PostgreSQL does. Normalize every
    datetime to UTC-aware immediately so offset arithmetic never mixes
    naive and aware values regardless of which database is in use."""
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)


def _offset_minutes(dt: datetime, horizon_start: datetime) -> int:
    return int((_as_utc(dt) - _as_utc(horizon_start)).total_seconds() // 60)


async def build_problem_from_db(
    db: Session,
    project_id: str,
    task_ids: list[str] | None,
    objective_profile: str = "balanced",
    locked_assignments: dict | None = None,
    max_solve_seconds: int | None = None,
) -> SchedulingProblem:
    project = db.get(Project, project_id)
    if project is None:
        raise ValueError(f"project {project_id} not found")

    query = db.query(Task).filter(Task.project_id == project_id)
    if task_ids:
        query = query.filter(Task.id.in_(task_ids))
    tasks_rows = query.all()
    if not tasks_rows:
        raise ValueError("no tasks found for the given project/task_ids")

    all_starts = [_as_utc(t.earliest_start) for t in tasks_rows if t.earliest_start]
    all_ends = [_as_utc(t.latest_finish) for t in tasks_rows if t.latest_finish]
    horizon_start = min(all_starts) if all_starts else datetime.now(timezone.utc)
    horizon_end = max(all_ends) if all_ends else horizon_start
    horizon_minutes = max(_offset_minutes(horizon_end, horizon_start) + 1440, 1440)

    location_ids = {t.location_id for t in tasks_rows}
    crew_rows = db.query(CrewMember).filter(CrewMember.is_active == True).all()  # noqa: E712
    equip_rows = db.query(Equipment).filter(Equipment.is_active == True).all()  # noqa: E712
    location_ids |= {c.home_location_id for c in crew_rows if c.home_location_id}
    location_ids |= {e.current_location_id for e in equip_rows if e.current_location_id}
    location_rows = db.query(Location).filter(Location.id.in_(location_ids)).all()
    loc_by_id = {loc.id: loc for loc in location_rows}

    # --- travel matrix (real routing service, cached, provenance-tagged) ---
    coords = [Coordinate(l.id, l.latitude, l.longitude) for l in location_rows]
    routing_service = RoutingService()
    raw_matrix = await routing_service.build_matrix(coords, departure_time=horizon_start)
    legs = {
        (fid, tid): TravelLeg(
            distance_km=r.distance_km, duration_minutes=r.duration_minutes,
            cost=r.cost, data_source=r.data_source, confidence=r.confidence,
        )
        for (fid, tid), r in raw_matrix.items()
    }
    travel_matrix = TravelMatrix(legs)

    # --- tasks + requirements + dependencies ---
    task_defs = []
    for t in tasks_rows:
        crew_reqs = db.query(TaskCrewRequirement).filter(TaskCrewRequirement.task_id == t.id).all()
        equip_reqs = db.query(TaskEquipmentRequirement).filter(TaskEquipmentRequirement.task_id == t.id).all()
        earliest = _offset_minutes(t.earliest_start, horizon_start) if t.earliest_start else 0
        latest = _offset_minutes(t.latest_finish, horizon_start) if t.latest_finish else horizon_minutes
        task_defs.append(TaskDef(
            id=t.id, location_id=t.location_id, duration_minutes=t.duration_minutes,
            earliest_start=max(0, earliest), latest_finish=max(latest, earliest + t.duration_minutes),
            priority=t.priority,
            crew_requirements=tuple(
                CrewRequirement(role_id=r.role_id, quantity=r.quantity,
                                 required_skill_ids=tuple(r.required_skill_ids or []),
                                 required_cert_ids=tuple(r.required_cert_ids or []))
                for r in crew_reqs
            ),
            equipment_requirements=tuple(
                EquipmentRequirement(category_id=r.category_id, quantity=r.quantity, min_capacity=r.min_capacity)
                for r in equip_reqs
            ),
        ))

    task_id_set = {t.id for t in tasks_rows}
    dep_rows = db.query(TaskDependency).filter(
        TaskDependency.predecessor_id.in_(task_id_set), TaskDependency.successor_id.in_(task_id_set)
    ).all()
    dependencies = [Dependency(d.predecessor_id, d.successor_id, d.lag_minutes, d.dependency_type) for d in dep_rows]

    # --- crew ---
    crew_defs = []
    for c in crew_rows:
        skills = {cs.skill_id for cs in db.query(CrewSkill).filter(CrewSkill.crew_member_id == c.id).all()}
        certs = []
        for cert in db.query(CrewCertification).filter(CrewCertification.crew_member_id == c.id).all():
            expiry_offset = _offset_minutes(datetime.combine(cert.expiry_date, datetime.min.time(), tzinfo=timezone.utc), horizon_start) if cert.expiry_date else None
            certs.append(Certification(certification_id=cert.certification_id, expiry_offset=expiry_offset))
        windows = []
        for a in db.query(CrewAvailability).filter(
            CrewAvailability.crew_member_id == c.id, CrewAvailability.availability_type == "available"
        ).all():
            windows.append((max(0, _offset_minutes(a.starts_at, horizon_start)), _offset_minutes(a.ends_at, horizon_start)))
        crew_defs.append(CrewDef(
            id=c.id, role_id=c.primary_role_id, home_location_id=c.home_location_id or "",
            skill_ids=frozenset(skills), certifications=tuple(certs),
            availability_windows=tuple(windows),
            max_hours_per_day=c.max_hours_per_day, max_hours_per_week=c.max_hours_per_week,
            min_rest_hours=c.min_rest_hours, standard_rate_per_hour=float(c.standard_rate),
            overtime_rate_per_hour=float(c.overtime_rate), max_travel_km=c.max_travel_km,
        ))

    # --- equipment ---
    equip_defs = []
    for e in equip_rows:
        windows = []
        for a in db.query(EquipmentAvailability).filter(
            EquipmentAvailability.equipment_id == e.id, EquipmentAvailability.availability_type == "available"
        ).all():
            windows.append((max(0, _offset_minutes(a.starts_at, horizon_start)), _offset_minutes(a.ends_at, horizon_start)))
        maint = []
        for m in db.query(EquipmentMaintenance).filter(
            EquipmentMaintenance.equipment_id == e.id, EquipmentMaintenance.blocks_usage == True  # noqa: E712
        ).all():
            maint.append((max(0, _offset_minutes(m.starts_at, horizon_start)), _offset_minutes(m.ends_at, horizon_start)))
        equip_defs.append(EquipmentDef(
            id=e.id, category_id=e.category_id, current_location_id=e.current_location_id or "",
            capacity_value=float(e.capacity_value) if e.capacity_value is not None else None,
            operators_required=e.operators_required,
            required_operator_cert_ids=tuple(e.required_operator_cert_ids or []),
            availability_windows=tuple(windows), maintenance_windows=tuple(maint),
            daily_operating_cost=float(e.daily_operating_cost or 0),
            transport_cost_per_km=float(e.transport_cost_per_km or 0),
            needs_transport=e.needs_transport,
        ))

    weights, solver_cfg = load_default_weights()
    weights = weights_for_profile(objective_profile, weights)

    locked = dict(locked_assignments or {})
    if project.deadline:
        locked["__project_deadline__"] = _offset_minutes(project.deadline, horizon_start)

    return SchedulingProblem(
        horizon_start=horizon_start,
        horizon_minutes=horizon_minutes,
        tasks=task_defs,
        crew=crew_defs,
        equipment=equip_defs,
        dependencies=dependencies,
        travel_matrix=travel_matrix,
        weights=weights,
        objective_profile=objective_profile,
        locked_assignments=locked,
        max_solve_seconds=max_solve_seconds or solver_cfg.get("max_time_seconds", 120),
        num_workers=solver_cfg.get("num_workers", 8),
        relative_gap=solver_cfg.get("relative_gap_limit", 0.02),
    )
