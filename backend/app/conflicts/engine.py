"""Independent conflict-detection pass (build doc section 6 / 16).

Runs over a SchedulingProblem + SolveResult -- the SAME data shape the
solver used -- but with NO knowledge of which internal solver constraints
fired. This is deliberate: it catches (a) bugs in the solver's own
constraint modelling, (b) hand-edited plans, and (c) plans that have gone
stale because the underlying data changed after the solve (build doc
section 36, plan freshness). It never trusts "the solver said this plan is
fine" -- it re-derives every fact from scratch.
"""
from __future__ import annotations

import itertools
from dataclasses import dataclass

from app.optimization.problem import SchedulingProblem
from app.optimization.solver import SolveResult, _is_crew_qualified, _day_index, STANDARD_DAY_MINUTES


@dataclass
class Conflict:
    conflict_type: str
    severity: str  # critical, warning, info
    entity_type: str | None
    entity_id: str | None
    description: str
    suggested_fix: str = ""


def _windows_contain(windows, start, end) -> bool:
    return any(w[0] <= start and w[1] >= end for w in windows)


def _overlaps(a_start, a_end, b_start, b_end) -> bool:
    return a_start < b_end and b_start < a_end


def detect_conflicts(problem: SchedulingProblem, result: SolveResult) -> list[Conflict]:
    conflicts: list[Conflict] = []
    if result.task_schedule is None:
        return conflicts

    conflicts += _check_crew_overlap(problem, result)
    conflicts += _check_crew_availability(problem, result)
    conflicts += _check_skills_and_certs(problem, result)
    conflicts += _check_working_hours(problem, result)
    conflicts += _check_rest_periods(problem, result)
    conflicts += _check_overtime_ratio(problem, result)
    conflicts += _check_equipment_overlap(problem, result)
    conflicts += _check_equipment_availability_and_maintenance(problem, result)
    conflicts += _check_operator_certs(problem, result)
    conflicts += _check_travel_feasibility(problem, result)
    conflicts += _check_dependencies(problem, result)
    conflicts += _check_deadlines(problem, result)
    conflicts += _check_resource_shortage(problem, result)

    order = {"critical": 0, "warning": 1, "info": 2}
    return sorted(conflicts, key=lambda c: order.get(c.severity, 3))


def _check_crew_overlap(problem, result) -> list[Conflict]:
    out = []
    by_crew: dict[str, list[tuple[str, int, int]]] = {}
    for task_id, crew_ids in (result.crew_assignments or {}).items():
        start, end = result.task_schedule[task_id]
        for cid in crew_ids:
            by_crew.setdefault(cid, []).append((task_id, start, end))
    for cid, items in by_crew.items():
        for (t1, s1, e1), (t2, s2, e2) in itertools.combinations(items, 2):
            if _overlaps(s1, e1, s2, e2):
                out.append(Conflict(
                    "crew_double_booking", "critical", "crew", cid,
                    f"Crew member {cid} is assigned to task {t1} and task {t2} at overlapping times.",
                    f"Reassign one of {t1}/{t2} to another qualified crew member or reschedule it.",
                ))
    return out


def _check_crew_availability(problem, result) -> list[Conflict]:
    out = []
    crew_by_id = {c.id: c for c in problem.crew}
    for task_id, crew_ids in (result.crew_assignments or {}).items():
        start, end = result.task_schedule[task_id]
        for cid in crew_ids:
            crew = crew_by_id.get(cid)
            if crew is None or not _windows_contain(crew.availability_windows, start, end):
                out.append(Conflict(
                    "crew_unavailable", "critical", "crew", cid,
                    f"Crew member {cid} is scheduled on task {task_id} outside any declared availability window.",
                    "Add an availability window covering this task, or reassign the task.",
                ))
    return out


def _check_skills_and_certs(problem, result) -> list[Conflict]:
    out = []
    crew_by_id = {c.id: c for c in problem.crew}
    for task in problem.tasks:
        assigned = (result.crew_assignments or {}).get(task.id, [])
        _, end = result.task_schedule.get(task.id, (0, 0))
        for req in task.crew_requirements:
            for cid in assigned:
                crew = crew_by_id.get(cid)
                if crew is None:
                    continue
                if crew.role_id != req.role_id or not set(req.required_skill_ids).issubset(crew.skill_ids):
                    out.append(Conflict(
                        "skill_mismatch", "critical", "crew", cid,
                        f"Crew member {cid} does not hold the role/skills required for task {task.id}.",
                        "Assign a crew member who holds the required role and skills.",
                    ))
                for cert_id in req.required_cert_ids:
                    if not crew.is_cert_valid(cert_id, end):
                        out.append(Conflict(
                            "certification_expired", "critical", "crew", cid,
                            f"Crew member {cid}'s certification {cert_id} is missing or expires before task {task.id} finishes.",
                            "Renew the certification before the task date, or assign a currently-certified crew member.",
                        ))
    return out


def _check_working_hours(problem, result) -> list[Conflict]:
    out = []
    per_crew_day: dict[tuple[str, int], int] = {}
    for task in problem.tasks:
        start, end = result.task_schedule.get(task.id, (None, None))
        if start is None:
            continue
        day = _day_index(start)
        for cid in (result.crew_assignments or {}).get(task.id, []):
            per_crew_day[(cid, day)] = per_crew_day.get((cid, day), 0) + task.duration_minutes
    crew_by_id = {c.id: c for c in problem.crew}
    for (cid, day), minutes in per_crew_day.items():
        crew = crew_by_id.get(cid)
        if crew and minutes > crew.max_hours_per_day * 60:
            out.append(Conflict(
                "working_hours_exceeded", "critical", "crew", cid,
                f"Crew member {cid} is scheduled for {minutes/60:.1f}h on day index {day}, exceeding the {crew.max_hours_per_day}h/day limit.",
                "Move some of this crew member's tasks on that day to another qualified crew member.",
            ))
    return out


def _check_rest_periods(problem, result) -> list[Conflict]:
    out = []
    crew_by_id = {c.id: c for c in problem.crew}
    by_crew: dict[str, list[tuple[str, int, int]]] = {}
    for task_id, crew_ids in (result.crew_assignments or {}).items():
        start, end = result.task_schedule[task_id]
        for cid in crew_ids:
            by_crew.setdefault(cid, []).append((task_id, start, end))
    for cid, items in by_crew.items():
        crew = crew_by_id.get(cid)
        if not crew:
            continue
        rest_needed = crew.min_rest_hours * 60
        ordered = sorted(items, key=lambda x: x[1])
        for (t1, s1, e1), (t2, s2, e2) in zip(ordered, ordered[1:]):
            gap = s2 - e1
            if 0 <= gap < rest_needed:
                out.append(Conflict(
                    "insufficient_rest", "critical", "crew", cid,
                    f"Crew member {cid} has only {gap} min rest between task {t1} and task {t2}; {rest_needed} min required.",
                    f"Delay {t2} by {rest_needed - gap} minutes or assign a different crew member.",
                ))
    return out


def _check_overtime_ratio(problem, result) -> list[Conflict]:
    out = []
    for cid, minutes in (result.overtime_minutes or {}).items():
        if minutes > 4 * 60:
            out.append(Conflict(
                "excessive_overtime", "warning", "crew", cid,
                f"Crew member {cid} is projected to work {minutes} overtime minutes across the plan.",
                "Consider redistributing tasks to reduce fatigue risk.",
            ))
    return out


def _check_equipment_overlap(problem, result) -> list[Conflict]:
    out = []
    by_equip: dict[str, list[tuple[str, int, int]]] = {}
    for task_id, equip_ids in (result.equipment_assignments or {}).items():
        start, end = result.task_schedule[task_id]
        for eid in equip_ids:
            by_equip.setdefault(eid, []).append((task_id, start, end))
    for eid, items in by_equip.items():
        for (t1, s1, e1), (t2, s2, e2) in itertools.combinations(items, 2):
            if _overlaps(s1, e1, s2, e2):
                out.append(Conflict(
                    "equipment_double_alloc", "critical", "equipment", eid,
                    f"Equipment {eid} is allocated to task {t1} and task {t2} at overlapping times.",
                    "Reassign one task to alternate equipment or reschedule it.",
                ))
    return out


def _check_equipment_availability_and_maintenance(problem, result) -> list[Conflict]:
    out = []
    equip_by_id = {e.id: e for e in problem.equipment}
    for task_id, equip_ids in (result.equipment_assignments or {}).items():
        start, end = result.task_schedule[task_id]
        for eid in equip_ids:
            equip = equip_by_id.get(eid)
            if equip is None:
                continue
            if equip.availability_windows and not _windows_contain(equip.availability_windows, start, end):
                out.append(Conflict(
                    "equipment_location", "warning", "equipment", eid,
                    f"Equipment {eid} is scheduled on task {task_id} outside its declared availability window.",
                    "Confirm the equipment's availability window or reassign the task.",
                ))
            for m_start, m_end in equip.maintenance_windows:
                if _overlaps(start, end, m_start, m_end):
                    out.append(Conflict(
                        "maintenance_conflict", "critical", "equipment", eid,
                        f"Equipment {eid} is scheduled on task {task_id} during a maintenance window.",
                        "Reschedule the task outside the maintenance window or use alternate equipment.",
                    ))
    return out


def _check_operator_certs(problem, result) -> list[Conflict]:
    out = []
    crew_by_id = {c.id: c for c in problem.crew}
    for task in problem.tasks:
        _, end = result.task_schedule.get(task.id, (0, 0))
        assigned_crew = (result.crew_assignments or {}).get(task.id, [])
        for eid in (result.equipment_assignments or {}).get(task.id, []):
            equip = next((e for e in problem.equipment if e.id == eid), None)
            if not equip or not equip.required_operator_cert_ids:
                continue
            certified = sum(
                1 for cid in assigned_crew
                if (c := crew_by_id.get(cid)) and all(c.is_cert_valid(cert, end) for cert in equip.required_operator_cert_ids)
            )
            if certified < equip.operators_required:
                out.append(Conflict(
                    "no_qualified_operator", "critical", "equipment", eid,
                    f"Task {task.id} uses equipment {eid} which needs {equip.operators_required} certified operator(s); only {certified} assigned crew qualify.",
                    "Assign a crew member holding the required operator certification(s).",
                ))
    return out


def _check_travel_feasibility(problem, result) -> list[Conflict]:
    out = []
    by_crew: dict[str, list[tuple[str, int, int, str]]] = {}
    for task in problem.tasks:
        start, end = result.task_schedule.get(task.id, (None, None))
        if start is None:
            continue
        for cid in (result.crew_assignments or {}).get(task.id, []):
            by_crew.setdefault(cid, []).append((task.id, start, end, task.location_id))
    for cid, items in by_crew.items():
        ordered = sorted(items, key=lambda x: x[1])
        for (t1, s1, e1, loc1), (t2, s2, e2, loc2) in zip(ordered, ordered[1:]):
            if loc1 == loc2:
                continue
            try:
                leg = problem.travel_matrix.get(loc1, loc2)
            except KeyError:
                continue
            gap = s2 - e1
            if gap < leg.duration_minutes:
                out.append(Conflict(
                    "impossible_travel_time", "critical", "crew", cid,
                    f"Crew member {cid} finishes task {t1} at minute {e1} and starts task {t2} at minute {s2}; "
                    f"the journey takes {leg.duration_minutes} min ({leg.data_source}), only {gap} min available.",
                    f"Delay {t2} by {leg.duration_minutes - gap} minutes or assign a crew member already near the second site.",
                ))
    return out


def _check_dependencies(problem, result) -> list[Conflict]:
    out = []
    for dep in problem.dependencies:
        p = result.task_schedule.get(dep.predecessor_id)
        s = result.task_schedule.get(dep.successor_id)
        if not p or not s:
            continue
        ps, pe = p
        ss, se = s
        ok = {
            "FS": ss - pe >= dep.lag_minutes,
            "SS": ss - ps >= dep.lag_minutes,
            "FF": se - pe >= dep.lag_minutes,
            "SF": se - ps >= dep.lag_minutes,
        }.get(dep.dependency_type, True)
        if not ok:
            out.append(Conflict(
                "dependency_violation", "critical", "task", dep.successor_id,
                f"Dependency {dep.dependency_type} from {dep.predecessor_id} to {dep.successor_id} (lag {dep.lag_minutes}m) is violated.",
                "Re-solve after checking the dependency's lag and the two tasks' time windows.",
            ))
    return out


def _check_deadlines(problem, result) -> list[Conflict]:
    out = []
    deadline = problem.locked_assignments.get("__project_deadline__")
    for task in problem.tasks:
        sched = result.task_schedule.get(task.id)
        if not sched:
            continue
        _, end = sched
        if end > task.latest_finish:
            out.append(Conflict(
                "deadline_violation", "critical", "task", task.id,
                f"Task {task.id} finishes at minute {end}, after its own deadline of {task.latest_finish}.",
                "Extend the task window or free up resources earlier in the schedule.",
            ))
        elif deadline is not None and end > deadline:
            out.append(Conflict(
                "deadline_violation", "critical", "task", task.id,
                f"Task {task.id} finishes at minute {end}, after the project deadline at minute {deadline}.",
                "Extend the project deadline or reduce scope/tasks in this plan.",
            ))
    return out


def _check_resource_shortage(problem, result) -> list[Conflict]:
    out = []
    for task in problem.tasks:
        assigned = len((result.crew_assignments or {}).get(task.id, []))
        required = sum(r.quantity for r in task.crew_requirements)
        if assigned < required:
            out.append(Conflict(
                "resource_shortage", "warning", "task", task.id,
                f"Task {task.id} requires {required} crew but only {assigned} are assigned in this plan.",
                "Add qualified crew or relax the requirement.",
            ))
    return out
