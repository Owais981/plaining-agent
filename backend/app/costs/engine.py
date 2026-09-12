"""Deterministic cost calculator (build doc section 39). The LLM is never
the authoritative source for a cost figure -- every number here is derived
from the same SchedulingProblem/SolveResult the solver produced."""
from __future__ import annotations

from dataclasses import dataclass, field

from app.optimization.problem import SchedulingProblem
from app.optimization.solver import SolveResult, _day_index, STANDARD_DAY_MINUTES, ACCOMMODATION_DISTANCE_KM, ACCOMMODATION_NIGHTLY_COST


@dataclass
class CostBreakdown:
    labour: float = 0.0
    overtime: float = 0.0
    equipment: float = 0.0
    fuel: float = 0.0
    transport: float = 0.0
    tolls: float = 0.0
    accommodation: float = 0.0
    total: float = 0.0
    by_crew: dict[str, float] = field(default_factory=dict)
    by_equipment: dict[str, float] = field(default_factory=dict)


def calculate_cost(problem: SchedulingProblem, result: SolveResult) -> CostBreakdown:
    breakdown = CostBreakdown()
    if result.task_schedule is None:
        return breakdown

    crew_by_id = {c.id: c for c in problem.crew}
    equip_by_id = {e.id: e for e in problem.equipment}

    per_crew_day_minutes: dict[tuple[str, int], int] = {}
    for task in problem.tasks:
        sched = result.task_schedule.get(task.id)
        if not sched:
            continue
        start, _ = sched
        day = _day_index(start)
        for cid in (result.crew_assignments or {}).get(task.id, []):
            crew = crew_by_id.get(cid)
            if not crew:
                continue
            per_crew_day_minutes[(cid, day)] = per_crew_day_minutes.get((cid, day), 0) + task.duration_minutes
            home_dist = 0.0
            if crew.home_location_id != task.location_id:
                try:
                    leg = problem.travel_matrix.get(crew.home_location_id, task.location_id)
                    home_dist = leg.distance_km
                    breakdown.transport += leg.cost
                    breakdown.fuel += round(leg.distance_km * 0.15, 2)
                except KeyError:
                    pass
            if home_dist > ACCOMMODATION_DISTANCE_KM:
                breakdown.accommodation += ACCOMMODATION_NIGHTLY_COST

        for eid in (result.equipment_assignments or {}).get(task.id, []):
            equip = equip_by_id.get(eid)
            if not equip:
                continue
            cost = equip.daily_operating_cost
            breakdown.equipment += cost
            breakdown.by_equipment[eid] = breakdown.by_equipment.get(eid, 0.0) + cost
            if equip.needs_transport and equip.current_location_id != task.location_id:
                try:
                    leg = problem.travel_matrix.get(equip.current_location_id, task.location_id)
                    breakdown.transport += leg.distance_km * equip.transport_cost_per_km
                except KeyError:
                    pass

    for (cid, day), minutes in per_crew_day_minutes.items():
        crew = crew_by_id[cid]
        standard_minutes = min(minutes, STANDARD_DAY_MINUTES)
        overtime_minutes = max(0, minutes - STANDARD_DAY_MINUTES)
        labour = standard_minutes / 60 * crew.standard_rate_per_hour
        overtime = overtime_minutes / 60 * crew.overtime_rate_per_hour
        breakdown.labour += labour
        breakdown.overtime += overtime
        breakdown.by_crew[cid] = breakdown.by_crew.get(cid, 0.0) + labour + overtime

    breakdown.labour = round(breakdown.labour, 2)
    breakdown.overtime = round(breakdown.overtime, 2)
    breakdown.equipment = round(breakdown.equipment, 2)
    breakdown.fuel = round(breakdown.fuel, 2)
    breakdown.transport = round(breakdown.transport, 2)
    breakdown.accommodation = round(breakdown.accommodation, 2)
    breakdown.total = round(
        breakdown.labour + breakdown.overtime + breakdown.equipment
        + breakdown.fuel + breakdown.transport + breakdown.tolls + breakdown.accommodation, 2
    )
    return breakdown
