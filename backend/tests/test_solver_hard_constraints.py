from datetime import datetime, timezone

from app.optimization.problem import (
    SchedulingProblem, TaskDef, CrewDef, EquipmentDef, Dependency,
    CrewRequirement, EquipmentRequirement, Certification, TravelMatrix, TravelLeg,
)
from app.optimization.solver import solve_with_explanation
from tests.conftest import HORIZON_START, DAY, make_travel_matrix


def test_single_site_solves_optimally(single_site_problem):
    result, infeasible = solve_with_explanation(single_site_problem)
    assert infeasible is None
    assert result.status in ("OPTIMAL", "FEASIBLE")
    assert result.crew_assignments["task-1"] == ["crew-1"]


def test_unqualified_crew_never_assigned():
    """C1: a crew member without the right role must never be assigned,
    and if they are the only crew, the problem must be INFEASIBLE."""
    unqualified = CrewDef(
        id="crew-2", role_id="role-plumber", home_location_id="loc-a",
        availability_windows=((0, 3 * DAY),), standard_rate_per_hour=20, overtime_rate_per_hour=30,
    )
    task = TaskDef(
        id="task-1", location_id="loc-a", duration_minutes=120,
        earliest_start=8 * 60, latest_finish=18 * 60,
        crew_requirements=(CrewRequirement(role_id="role-electrician", quantity=1),),
    )
    problem = SchedulingProblem(
        horizon_start=HORIZON_START, horizon_minutes=3 * DAY,
        tasks=[task], crew=[unqualified], equipment=[], dependencies=[],
        travel_matrix=make_travel_matrix(["loc-a"]), max_solve_seconds=10,
    )
    result, infeasible = solve_with_explanation(problem)
    assert result.status == "INFEASIBLE"
    assert infeasible is not None


def test_certification_expiry_is_checked_against_task_date():
    """Build doc section 13: 'the single most common correctness bug' --
    a certification valid today but expired by the task date must NOT
    qualify the crew member."""
    task_offset = 10 * DAY  # task is on day 10
    crew_expired_by_then = CrewDef(
        id="crew-1", role_id="role-crane-op", home_location_id="loc-a",
        certifications=(Certification("cert-crane", expiry_offset=5 * DAY),),  # expires day 5, before the task
        availability_windows=((0, 20 * DAY),), standard_rate_per_hour=30, overtime_rate_per_hour=45,
    )
    task = TaskDef(
        id="task-1", location_id="loc-a", duration_minutes=120,
        earliest_start=task_offset + 8 * 60, latest_finish=task_offset + 18 * 60,
        crew_requirements=(CrewRequirement(role_id="role-crane-op", quantity=1, required_cert_ids=("cert-crane",)),),
    )
    problem = SchedulingProblem(
        horizon_start=HORIZON_START, horizon_minutes=20 * DAY,
        tasks=[task], crew=[crew_expired_by_then], equipment=[], dependencies=[],
        travel_matrix=make_travel_matrix(["loc-a"]), max_solve_seconds=10,
    )
    result, infeasible = solve_with_explanation(problem)
    assert result.status == "INFEASIBLE"


def test_certification_valid_through_task_date_is_accepted():
    task_offset = 3 * DAY
    crew = CrewDef(
        id="crew-1", role_id="role-crane-op", home_location_id="loc-a",
        certifications=(Certification("cert-crane", expiry_offset=10 * DAY),),  # expires after the task
        availability_windows=((0, 20 * DAY),), standard_rate_per_hour=30, overtime_rate_per_hour=45,
    )
    task = TaskDef(
        id="task-1", location_id="loc-a", duration_minutes=120,
        earliest_start=task_offset + 8 * 60, latest_finish=task_offset + 18 * 60,
        crew_requirements=(CrewRequirement(role_id="role-crane-op", quantity=1, required_cert_ids=("cert-crane",)),),
    )
    problem = SchedulingProblem(
        horizon_start=HORIZON_START, horizon_minutes=20 * DAY,
        tasks=[task], crew=[crew], equipment=[], dependencies=[],
        travel_matrix=make_travel_matrix(["loc-a"]), max_solve_seconds=10,
    )
    result, infeasible = solve_with_explanation(problem)
    assert result.status in ("OPTIMAL", "FEASIBLE")


def test_no_crew_double_booking_two_tasks_one_crew():
    """C3: with only one qualified crew member and two tasks whose windows
    give no slack to avoid overlap, the solver must be infeasible."""
    crew = CrewDef(
        id="crew-1", role_id="role-electrician", home_location_id="loc-a",
        availability_windows=((0, 3 * DAY),), standard_rate_per_hour=25, overtime_rate_per_hour=37.5,
    )
    # zero slack: each window equals exactly the task's duration, and the
    # windows overlap by 60 minutes, so no non-overlapping schedule exists.
    t1 = TaskDef(id="task-1", location_id="loc-a", duration_minutes=120, earliest_start=8 * 60, latest_finish=10 * 60,
                 crew_requirements=(CrewRequirement(role_id="role-electrician", quantity=1),))
    t2 = TaskDef(id="task-2", location_id="loc-a", duration_minutes=120, earliest_start=9 * 60, latest_finish=11 * 60,
                 crew_requirements=(CrewRequirement(role_id="role-electrician", quantity=1),))
    problem = SchedulingProblem(
        horizon_start=HORIZON_START, horizon_minutes=3 * DAY,
        tasks=[t1, t2], crew=[crew], equipment=[], dependencies=[],
        travel_matrix=make_travel_matrix(["loc-a"]), max_solve_seconds=10,
    )
    result, infeasible = solve_with_explanation(problem)
    assert result.status == "INFEASIBLE"


def test_crew_availability_window_enforced():
    """C2: a crew member with NO availability window covering the task
    must never be usable -- absence of a row = not available."""
    crew = CrewDef(
        id="crew-1", role_id="role-electrician", home_location_id="loc-a",
        availability_windows=(),  # explicitly no availability
        standard_rate_per_hour=25, overtime_rate_per_hour=37.5,
    )
    task = TaskDef(id="task-1", location_id="loc-a", duration_minutes=120, earliest_start=8 * 60, latest_finish=18 * 60,
                   crew_requirements=(CrewRequirement(role_id="role-electrician", quantity=1),))
    problem = SchedulingProblem(
        horizon_start=HORIZON_START, horizon_minutes=3 * DAY,
        tasks=[task], crew=[crew], equipment=[], dependencies=[],
        travel_matrix=make_travel_matrix(["loc-a"]), max_solve_seconds=10,
    )
    result, infeasible = solve_with_explanation(problem)
    assert result.status == "INFEASIBLE"


def test_equipment_maintenance_blocks_usage():
    """C4: equipment under maintenance during the task window must not be
    assignable."""
    crew = CrewDef(id="crew-1", role_id="role-op", home_location_id="loc-a",
                    availability_windows=((0, 3 * DAY),), standard_rate_per_hour=25, overtime_rate_per_hour=37.5)
    equip = EquipmentDef(
        id="eq-1", category_id="cat-crane", current_location_id="loc-a",
        availability_windows=((0, 3 * DAY),),
        maintenance_windows=((8 * 60, 18 * 60),),  # maintenance covers the whole task window
    )
    task = TaskDef(
        id="task-1", location_id="loc-a", duration_minutes=120, earliest_start=8 * 60, latest_finish=18 * 60,
        crew_requirements=(CrewRequirement(role_id="role-op", quantity=1),),
        equipment_requirements=(EquipmentRequirement(category_id="cat-crane", quantity=1),),
    )
    problem = SchedulingProblem(
        horizon_start=HORIZON_START, horizon_minutes=3 * DAY,
        tasks=[task], crew=[crew], equipment=[equip], dependencies=[],
        travel_matrix=make_travel_matrix(["loc-a"]), max_solve_seconds=10,
    )
    result, infeasible = solve_with_explanation(problem)
    assert result.status == "INFEASIBLE"


def test_travel_feasibility_blocks_impossible_transition():
    """C9: one crew member cannot do two different-site tasks back-to-back
    if there isn't enough time to travel between them."""
    crew = CrewDef(id="crew-1", role_id="role-electrician", home_location_id="loc-a",
                    availability_windows=((0, 3 * DAY),), standard_rate_per_hour=25, overtime_rate_per_hour=37.5)
    t1 = TaskDef(id="task-1", location_id="loc-a", duration_minutes=60, earliest_start=8 * 60, latest_finish=9 * 60,
                 crew_requirements=(CrewRequirement(role_id="role-electrician", quantity=1),))
    t2 = TaskDef(id="task-2", location_id="loc-b", duration_minutes=60, earliest_start=9 * 60 + 5, latest_finish=10 * 60,
                 crew_requirements=(CrewRequirement(role_id="role-electrician", quantity=1),))
    problem = SchedulingProblem(
        horizon_start=HORIZON_START, horizon_minutes=3 * DAY,
        tasks=[t1, t2], crew=[crew], equipment=[], dependencies=[],
        travel_matrix=make_travel_matrix(["loc-a", "loc-b"], minutes_between_different=90),
        max_solve_seconds=10,
    )
    result, infeasible = solve_with_explanation(problem)
    assert result.status == "INFEASIBLE"


def test_travel_feasibility_allows_sufficient_gap():
    crew = CrewDef(id="crew-1", role_id="role-electrician", home_location_id="loc-a",
                    availability_windows=((0, 3 * DAY),), standard_rate_per_hour=25, overtime_rate_per_hour=37.5)
    t1 = TaskDef(id="task-1", location_id="loc-a", duration_minutes=60, earliest_start=8 * 60, latest_finish=9 * 60,
                 crew_requirements=(CrewRequirement(role_id="role-electrician", quantity=1),))
    t2 = TaskDef(id="task-2", location_id="loc-b", duration_minutes=60, earliest_start=11 * 60, latest_finish=13 * 60,
                 crew_requirements=(CrewRequirement(role_id="role-electrician", quantity=1),))
    problem = SchedulingProblem(
        horizon_start=HORIZON_START, horizon_minutes=3 * DAY,
        tasks=[t1, t2], crew=[crew], equipment=[], dependencies=[],
        travel_matrix=make_travel_matrix(["loc-a", "loc-b"], minutes_between_different=90),
        max_solve_seconds=10,
    )
    result, infeasible = solve_with_explanation(problem)
    assert result.status in ("OPTIMAL", "FEASIBLE")


def test_working_hours_per_day_cap():
    """C10: a crew member cannot be scheduled beyond max_hours_per_day."""
    crew = CrewDef(id="crew-1", role_id="role-electrician", home_location_id="loc-a",
                    availability_windows=((0, 3 * DAY),), max_hours_per_day=8,
                    standard_rate_per_hour=25, overtime_rate_per_hour=37.5)
    # three non-overlapping 4h tasks in one day = 12h > 8h cap
    tasks = [
        TaskDef(id=f"task-{i}", location_id="loc-a", duration_minutes=240,
                earliest_start=(6 + i * 4) * 60, latest_finish=(6 + i * 4 + 4) * 60,
                crew_requirements=(CrewRequirement(role_id="role-electrician", quantity=1),))
        for i in range(3)
    ]
    problem = SchedulingProblem(
        horizon_start=HORIZON_START, horizon_minutes=3 * DAY,
        tasks=tasks, crew=[crew], equipment=[], dependencies=[],
        travel_matrix=make_travel_matrix(["loc-a"]), max_solve_seconds=10,
    )
    result, infeasible = solve_with_explanation(problem)
    assert result.status == "INFEASIBLE"


def test_minimum_rest_between_days_enforced():
    """C11: less than min_rest_hours between the end of one day's shift and
    the start of the next day's shift must be infeasible."""
    crew = CrewDef(id="crew-1", role_id="role-electrician", home_location_id="loc-a",
                    availability_windows=((0, 3 * DAY),), min_rest_hours=11,
                    standard_rate_per_hour=25, overtime_rate_per_hour=37.5)
    t1 = TaskDef(id="task-1", location_id="loc-a", duration_minutes=120, earliest_start=20 * 60, latest_finish=22 * 60,
                 crew_requirements=(CrewRequirement(role_id="role-electrician", quantity=1),))
    # next day starting only 6 hours after task-1 ends (22:00 -> 04:00 next day)
    t2 = TaskDef(id="task-2", location_id="loc-a", duration_minutes=120, earliest_start=DAY + 4 * 60, latest_finish=DAY + 6 * 60,
                 crew_requirements=(CrewRequirement(role_id="role-electrician", quantity=1),))
    problem = SchedulingProblem(
        horizon_start=HORIZON_START, horizon_minutes=3 * DAY,
        tasks=[t1, t2], crew=[crew], equipment=[], dependencies=[],
        travel_matrix=make_travel_matrix(["loc-a"]), max_solve_seconds=10,
    )
    result, infeasible = solve_with_explanation(problem)
    assert result.status == "INFEASIBLE"


def test_dependency_finish_to_start_with_lag():
    """C7: successor cannot start before predecessor finishes + lag."""
    crew = CrewDef(id="crew-1", role_id="role-electrician", home_location_id="loc-a",
                    availability_windows=((0, 3 * DAY),), standard_rate_per_hour=25, overtime_rate_per_hour=37.5)
    pred = TaskDef(id="pred", location_id="loc-a", duration_minutes=60, earliest_start=8 * 60, latest_finish=10 * 60,
                   crew_requirements=(CrewRequirement(role_id="role-electrician", quantity=1),))
    succ = TaskDef(id="succ", location_id="loc-a", duration_minutes=60, earliest_start=8 * 60, latest_finish=9 * 60 + 30,
                   crew_requirements=(CrewRequirement(role_id="role-electrician", quantity=1),))
    problem = SchedulingProblem(
        horizon_start=HORIZON_START, horizon_minutes=3 * DAY,
        tasks=[pred, succ], crew=[crew], equipment=[],
        dependencies=[Dependency("pred", "succ", lag_minutes=30, dependency_type="FS")],
        travel_matrix=make_travel_matrix(["loc-a"]), max_solve_seconds=10,
    )
    result, infeasible = solve_with_explanation(problem)
    # succ's window (ends 9:30) can't accommodate starting after pred+30min
    # (earliest possible start for succ is >= pred_end + 30, and pred can
    # finish no earlier than 9:00, so succ would need to start >= 9:30 and
    # run 60 min -- past its own 9:30 deadline). Must be infeasible.
    assert result.status == "INFEASIBLE"


def test_crew_quantity_requirement_enforced():
    """C12: a task requiring 2 crew must get exactly 2 qualified people."""
    crew = [
        CrewDef(id=f"crew-{i}", role_id="role-rigger", home_location_id="loc-a",
                availability_windows=((0, 3 * DAY),), standard_rate_per_hour=25, overtime_rate_per_hour=37.5)
        for i in range(2)
    ]
    task = TaskDef(id="task-1", location_id="loc-a", duration_minutes=120, earliest_start=8 * 60, latest_finish=18 * 60,
                   crew_requirements=(CrewRequirement(role_id="role-rigger", quantity=2),))
    problem = SchedulingProblem(
        horizon_start=HORIZON_START, horizon_minutes=3 * DAY,
        tasks=[task], crew=crew, equipment=[], dependencies=[],
        travel_matrix=make_travel_matrix(["loc-a"]), max_solve_seconds=10,
    )
    result, infeasible = solve_with_explanation(problem)
    assert result.status in ("OPTIMAL", "FEASIBLE")
    assert len(result.crew_assignments["task-1"]) == 2


def test_operator_certification_required_for_equipment():
    """C6: equipment needing a certified operator must have a certified
    crew member present; without one, infeasible."""
    equip = EquipmentDef(id="crane-1", category_id="cat-crane", current_location_id="loc-a",
                          availability_windows=((0, 3 * DAY),), required_operator_cert_ids=("cert-crane-op",), operators_required=1)
    uncertified = CrewDef(id="crew-1", role_id="role-op", home_location_id="loc-a",
                           availability_windows=((0, 3 * DAY),), standard_rate_per_hour=25, overtime_rate_per_hour=37.5)
    task = TaskDef(
        id="task-1", location_id="loc-a", duration_minutes=120, earliest_start=8 * 60, latest_finish=18 * 60,
        crew_requirements=(CrewRequirement(role_id="role-op", quantity=1),),
        equipment_requirements=(EquipmentRequirement(category_id="cat-crane", quantity=1),),
    )
    problem = SchedulingProblem(
        horizon_start=HORIZON_START, horizon_minutes=3 * DAY,
        tasks=[task], crew=[uncertified], equipment=[equip], dependencies=[],
        travel_matrix=make_travel_matrix(["loc-a"]), max_solve_seconds=10,
    )
    result, infeasible = solve_with_explanation(problem)
    assert result.status == "INFEASIBLE"
