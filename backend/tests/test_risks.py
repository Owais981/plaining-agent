from app.optimization.problem import SchedulingProblem, TaskDef, CrewDef, CrewRequirement, Certification
from app.optimization.solver import SolveResult
from app.risks.engine import assess_risks
from tests.conftest import HORIZON_START, DAY, make_travel_matrix


def test_single_point_of_failure_flagged():
    crew = [CrewDef(id="crew-1", role_id="role-crane-op", home_location_id="loc-a", availability_windows=((0, 3 * DAY),))]
    task = TaskDef(id="t1", location_id="loc-a", duration_minutes=60, earliest_start=8 * 60, latest_finish=18 * 60,
                    crew_requirements=(CrewRequirement(role_id="role-crane-op", quantity=1),))
    problem = SchedulingProblem(horizon_start=HORIZON_START, horizon_minutes=3 * DAY, tasks=[task], crew=crew,
                                 equipment=[], dependencies=[], travel_matrix=make_travel_matrix(["loc-a"]))
    result = SolveResult(status="OPTIMAL", task_schedule={"t1": (8 * 60, 9 * 60)}, crew_assignments={"t1": ["crew-1"]}, equipment_assignments={})
    risks = assess_risks(problem, result)
    assert any(r.risk_type == "single_point_of_failure" for r in risks)


def test_excessive_overtime_flagged():
    crew = [CrewDef(id="crew-1", role_id="role-x", home_location_id="loc-a", availability_windows=((0, 3 * DAY),))]
    problem = SchedulingProblem(horizon_start=HORIZON_START, horizon_minutes=3 * DAY, tasks=[], crew=crew,
                                 equipment=[], dependencies=[], travel_matrix=make_travel_matrix(["loc-a"]))
    result = SolveResult(status="OPTIMAL", task_schedule={}, crew_assignments={}, equipment_assignments={},
                          overtime_minutes={"crew-1": 400})
    risks = assess_risks(problem, result)
    assert any(r.risk_type == "excessive_overtime" and r.severity == "high" for r in risks)


def test_budget_exposure_flagged_when_over_budget():
    problem = SchedulingProblem(horizon_start=HORIZON_START, horizon_minutes=3 * DAY, tasks=[], crew=[],
                                 equipment=[], dependencies=[], travel_matrix=make_travel_matrix(["loc-a"]))
    result = SolveResult(status="OPTIMAL", task_schedule={}, crew_assignments={}, equipment_assignments={})
    risks = assess_risks(problem, result, project_budget=1000.0, actual_cost=1200.0)
    assert any(r.risk_type == "budget_exposure" and r.severity == "high" for r in risks)
