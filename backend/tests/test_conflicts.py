"""The conflict engine must catch problems even in a HAND-BUILT result that
never went through the solver (build doc section 6: it must catch bugs in
the solver's own modelling and hand-edited plans, not just trust success)."""
from app.optimization.problem import (
    SchedulingProblem, TaskDef, CrewDef, CrewRequirement, Certification, TravelMatrix, TravelLeg,
)
from app.optimization.solver import SolveResult
from app.conflicts.engine import detect_conflicts
from tests.conftest import HORIZON_START, DAY, make_travel_matrix


def _problem(tasks, crew, travel=None):
    return SchedulingProblem(
        horizon_start=HORIZON_START, horizon_minutes=3 * DAY,
        tasks=tasks, crew=crew, equipment=[], dependencies=[],
        travel_matrix=travel or make_travel_matrix(["loc-a"]),
    )


def test_detects_hand_edited_double_booking():
    crew = CrewDef(id="crew-1", role_id="role-x", home_location_id="loc-a", availability_windows=((0, 3 * DAY),))
    t1 = TaskDef(id="t1", location_id="loc-a", duration_minutes=60, earliest_start=8 * 60, latest_finish=9 * 60)
    t2 = TaskDef(id="t2", location_id="loc-a", duration_minutes=60, earliest_start=8 * 60 + 30, latest_finish=9 * 60 + 30)
    problem = _problem([t1, t2], [crew])
    result = SolveResult(
        status="FEASIBLE",
        task_schedule={"t1": (8 * 60, 9 * 60), "t2": (8 * 60 + 30, 9 * 60 + 30)},
        crew_assignments={"t1": ["crew-1"], "t2": ["crew-1"]},
        equipment_assignments={},
    )
    conflicts = detect_conflicts(problem, result)
    types = {c.conflict_type for c in conflicts}
    assert "crew_double_booking" in types
    assert conflicts[0].severity == "critical"


def test_detects_certification_expired_on_hand_edited_plan():
    crew = CrewDef(id="crew-1", role_id="role-crane-op", home_location_id="loc-a",
                    certifications=(Certification("cert-crane", expiry_offset=1 * DAY),),
                    availability_windows=((0, 3 * DAY),))
    task = TaskDef(id="t1", location_id="loc-a", duration_minutes=60, earliest_start=2 * DAY, latest_finish=2 * DAY + 120,
                    crew_requirements=(CrewRequirement(role_id="role-crane-op", quantity=1, required_cert_ids=("cert-crane",)),))
    problem = _problem([task], [crew])
    result = SolveResult(
        status="FEASIBLE", task_schedule={"t1": (2 * DAY, 2 * DAY + 60)},
        crew_assignments={"t1": ["crew-1"]}, equipment_assignments={},
    )
    conflicts = detect_conflicts(problem, result)
    assert any(c.conflict_type == "certification_expired" for c in conflicts)


def test_detects_impossible_travel_time():
    crew = CrewDef(id="crew-1", role_id="role-x", home_location_id="loc-a", availability_windows=((0, 3 * DAY),))
    t1 = TaskDef(id="t1", location_id="loc-a", duration_minutes=60, earliest_start=8 * 60, latest_finish=9 * 60)
    t2 = TaskDef(id="t2", location_id="loc-b", duration_minutes=60, earliest_start=9 * 60 + 10, latest_finish=10 * 60 + 10)
    problem = _problem([t1, t2], [crew], travel=make_travel_matrix(["loc-a", "loc-b"], minutes_between_different=90))
    result = SolveResult(
        status="FEASIBLE",
        task_schedule={"t1": (8 * 60, 9 * 60), "t2": (9 * 60 + 10, 10 * 60 + 10)},
        crew_assignments={"t1": ["crew-1"], "t2": ["crew-1"]}, equipment_assignments={},
    )
    conflicts = detect_conflicts(problem, result)
    assert any(c.conflict_type == "impossible_travel_time" for c in conflicts)


def test_clean_plan_has_no_critical_conflicts():
    crew = CrewDef(id="crew-1", role_id="role-x", home_location_id="loc-a", availability_windows=((0, 3 * DAY),))
    task = TaskDef(id="t1", location_id="loc-a", duration_minutes=60, earliest_start=8 * 60, latest_finish=18 * 60,
                    crew_requirements=(CrewRequirement(role_id="role-x", quantity=1),))
    problem = _problem([task], [crew])
    result = SolveResult(
        status="OPTIMAL", task_schedule={"t1": (8 * 60, 9 * 60)},
        crew_assignments={"t1": ["crew-1"]}, equipment_assignments={},
    )
    conflicts = detect_conflicts(problem, result)
    assert not any(c.severity == "critical" for c in conflicts)
