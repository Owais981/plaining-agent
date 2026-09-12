"""Deterministic risk register (build doc section 40). Claude may summarize
these for the user, but every risk object here is produced by rules over
the actual problem/result data, never invented."""
from __future__ import annotations

from dataclasses import dataclass

from app.optimization.problem import SchedulingProblem
from app.optimization.solver import SolveResult, _day_index


@dataclass
class Risk:
    risk_type: str
    severity: str  # high, medium, low
    entity_type: str | None
    entity_id: str | None
    description: str
    mitigation: str = ""


def assess_risks(problem: SchedulingProblem, result: SolveResult, project_budget: float | None = None, actual_cost: float | None = None) -> list[Risk]:
    risks: list[Risk] = []
    if result.task_schedule is None:
        return risks

    risks += _single_points_of_failure(problem, result)
    risks += _excessive_overtime(result)
    risks += _deadline_exposure(problem, result)
    risks += _maintenance_exposure(problem, result)
    risks += _fragile_dependencies(problem)
    risks += _limited_qualified_personnel(problem)
    if project_budget and actual_cost:
        risks += _budget_exposure(project_budget, actual_cost)

    severity_order = {"high": 0, "medium": 1, "low": 2}
    return sorted(risks, key=lambda r: severity_order.get(r.severity, 3))


def _single_points_of_failure(problem, result) -> list[Risk]:
    out = []
    for task in problem.tasks:
        for req in task.crew_requirements:
            qualified = [
                c for c in problem.crew
                if c.role_id == req.role_id and set(req.required_skill_ids).issubset(c.skill_ids)
                and all(c.is_cert_valid(cid, task.latest_finish) for cid in req.required_cert_ids)
            ]
            if len(qualified) <= req.quantity:
                out.append(Risk(
                    "single_point_of_failure", "high", "task", task.id,
                    f"Task {task.id} needs {req.quantity} crew with role {req.role_id}; only {len(qualified)} qualified crew exist in total.",
                    "Cross-train an additional crew member or bring in a contractor with this qualification.",
                ))
        for req in task.equipment_requirements:
            candidates = [e for e in problem.equipment if e.category_id == req.category_id]
            if len(candidates) <= req.quantity:
                out.append(Risk(
                    "single_point_of_failure", "high", "task", task.id,
                    f"Task {task.id} needs {req.quantity} unit(s) of equipment category {req.category_id}; only {len(candidates)} exist.",
                    "Arrange a rental backup or reschedule if the unit is unavailable.",
                ))
    return out


def _excessive_overtime(result) -> list[Risk]:
    out = []
    for cid, minutes in (result.overtime_minutes or {}).items():
        if minutes > 6 * 60:
            out.append(Risk(
                "excessive_overtime", "high", "crew", cid,
                f"Crew member {cid} accumulates {minutes} overtime minutes in this plan -- fatigue and safety risk.",
                "Redistribute tasks or add crew capacity.",
            ))
        elif minutes > 2 * 60:
            out.append(Risk(
                "excessive_overtime", "medium", "crew", cid,
                f"Crew member {cid} accumulates {minutes} overtime minutes in this plan.",
                "Monitor; consider redistributing if this pattern repeats across the project.",
            ))
    return out


def _deadline_exposure(problem, result) -> list[Risk]:
    out = []
    for task in problem.tasks:
        sched = result.task_schedule.get(task.id)
        if not sched:
            continue
        _, end = sched
        slack = task.latest_finish - end
        if 0 <= slack < 60:
            out.append(Risk(
                "deadline_exposure", "medium", "task", task.id,
                f"Task {task.id} finishes with only {slack} minutes of slack before its deadline.",
                "Any delay (weather, travel, absence) will breach the deadline -- consider adding buffer.",
            ))
    return out


def _maintenance_exposure(problem, result) -> list[Risk]:
    out = []
    for equip in problem.equipment:
        used_days = {
            _day_index(result.task_schedule[t.id][0])
            for t in problem.tasks
            if equip.id in (result.equipment_assignments or {}).get(t.id, []) and t.id in result.task_schedule
        }
        for m_start, m_end in equip.maintenance_windows:
            m_day = _day_index(m_start)
            if any(abs(d - m_day) <= 1 for d in used_days):
                out.append(Risk(
                    "maintenance_risk", "medium", "equipment", equip.id,
                    f"Equipment {equip.id} has a maintenance window close to days it is scheduled for use.",
                    "Confirm the maintenance window will not slip and overlap a scheduled task.",
                ))
    return out


def _fragile_dependencies(problem) -> list[Risk]:
    out = []
    successor_counts: dict[str, int] = {}
    for dep in problem.dependencies:
        successor_counts[dep.predecessor_id] = successor_counts.get(dep.predecessor_id, 0) + 1
    for task_id, count in successor_counts.items():
        if count >= 3:
            out.append(Risk(
                "fragile_dependency_chain", "medium", "task", task_id,
                f"Task {task_id} blocks {count} downstream tasks -- any delay cascades widely.",
                "Consider adding buffer after this task or splitting downstream work into parallel branches.",
            ))
    return out


def _limited_qualified_personnel(problem) -> list[Risk]:
    out = []
    for cert_id in {cid for c in problem.crew for cid in c.cert_ids_valid_through()}:
        holders = [c for c in problem.crew if cert_id in c.cert_ids_valid_through()]
        if len(holders) == 1:
            out.append(Risk(
                "limited_qualified_personnel", "medium", "crew", holders[0].id,
                f"Only one active crew member holds certification {cert_id}.",
                "Train a backup crew member on this certification.",
            ))
    return out


def _budget_exposure(project_budget: float, actual_cost: float) -> list[Risk]:
    ratio = actual_cost / project_budget if project_budget else 0
    if ratio > 1.0:
        return [Risk("budget_exposure", "high", "project", None,
                      f"Plan cost {actual_cost:.2f} exceeds the project budget of {project_budget:.2f}.",
                      "Reduce scope, cut overtime, or request a budget increase.")]
    if ratio > 0.9:
        return [Risk("budget_exposure", "medium", "project", None,
                      f"Plan cost {actual_cost:.2f} is at {ratio*100:.0f}% of the project budget.",
                      "Little headroom remains for scope changes or delays.")]
    return []
