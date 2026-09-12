from app.optimization.problem import SchedulingProblem, TaskDef, CrewDef, EquipmentDef
from app.optimization.solver import SolveResult, STANDARD_DAY_MINUTES
from app.costs.engine import calculate_cost
from tests.conftest import HORIZON_START, DAY, make_travel_matrix


def test_labour_cost_uses_standard_rate_within_standard_day():
    crew = CrewDef(id="crew-1", role_id="role-x", home_location_id="loc-a",
                    availability_windows=((0, 3 * DAY),), standard_rate_per_hour=20.0, overtime_rate_per_hour=30.0)
    task = TaskDef(id="t1", location_id="loc-a", duration_minutes=120, earliest_start=8 * 60, latest_finish=18 * 60)
    problem = SchedulingProblem(
        horizon_start=HORIZON_START, horizon_minutes=3 * DAY, tasks=[task], crew=[crew],
        equipment=[], dependencies=[], travel_matrix=make_travel_matrix(["loc-a"]),
    )
    result = SolveResult(status="OPTIMAL", task_schedule={"t1": (8 * 60, 10 * 60)}, crew_assignments={"t1": ["crew-1"]}, equipment_assignments={})
    breakdown = calculate_cost(problem, result)
    assert breakdown.labour == 2 * 20.0  # 2 hours at standard rate
    assert breakdown.overtime == 0.0
    assert breakdown.total == breakdown.labour


def test_overtime_cost_kicks_in_beyond_standard_day():
    crew = CrewDef(id="crew-1", role_id="role-x", home_location_id="loc-a",
                    availability_windows=((0, 3 * DAY),), standard_rate_per_hour=20.0, overtime_rate_per_hour=30.0)
    duration = STANDARD_DAY_MINUTES + 60  # 1 hour of overtime
    task = TaskDef(id="t1", location_id="loc-a", duration_minutes=duration, earliest_start=6 * 60, latest_finish=20 * 60)
    problem = SchedulingProblem(
        horizon_start=HORIZON_START, horizon_minutes=3 * DAY, tasks=[task], crew=[crew],
        equipment=[], dependencies=[], travel_matrix=make_travel_matrix(["loc-a"]),
    )
    result = SolveResult(status="OPTIMAL", task_schedule={"t1": (6 * 60, 6 * 60 + duration)}, crew_assignments={"t1": ["crew-1"]}, equipment_assignments={})
    breakdown = calculate_cost(problem, result)
    assert breakdown.labour == round(STANDARD_DAY_MINUTES / 60 * 20.0, 2)
    assert breakdown.overtime == round(1 * 30.0, 2)


def test_equipment_daily_operating_cost_included():
    crew = CrewDef(id="crew-1", role_id="role-x", home_location_id="loc-a", availability_windows=((0, 3 * DAY),))
    equip = EquipmentDef(id="eq-1", category_id="cat-crane", current_location_id="loc-a", daily_operating_cost=150.0)
    task = TaskDef(id="t1", location_id="loc-a", duration_minutes=60, earliest_start=8 * 60, latest_finish=18 * 60)
    problem = SchedulingProblem(
        horizon_start=HORIZON_START, horizon_minutes=3 * DAY, tasks=[task], crew=[crew],
        equipment=[equip], dependencies=[], travel_matrix=make_travel_matrix(["loc-a"]),
    )
    result = SolveResult(
        status="OPTIMAL", task_schedule={"t1": (8 * 60, 9 * 60)},
        crew_assignments={"t1": ["crew-1"]}, equipment_assignments={"t1": ["eq-1"]},
    )
    breakdown = calculate_cost(problem, result)
    assert breakdown.equipment == 150.0
