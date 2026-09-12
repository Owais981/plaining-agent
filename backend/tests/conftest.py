import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from datetime import datetime, timezone

import pytest

from app.optimization.problem import (
    SchedulingProblem, TaskDef, CrewDef, EquipmentDef, Dependency,
    CrewRequirement, EquipmentRequirement, Certification, TravelMatrix, TravelLeg,
    ObjectiveWeights,
)

HORIZON_START = datetime(2026, 3, 1, tzinfo=timezone.utc)
DAY = 1440


def make_travel_matrix(location_ids, minutes_between_different=30, km_between_different=25.0):
    legs = {}
    for a in location_ids:
        for b in location_ids:
            if a == b:
                continue
            legs[(a, b)] = TravelLeg(distance_km=km_between_different, duration_minutes=minutes_between_different, cost=km_between_different * 0.6)
    return TravelMatrix(legs)


@pytest.fixture
def base_weights():
    return ObjectiveWeights()


@pytest.fixture
def single_site_problem():
    """One task, one location, one qualified crew member. Should solve trivially."""
    crew = CrewDef(
        id="crew-1", role_id="role-electrician", home_location_id="loc-a",
        skill_ids=frozenset({"skill-basic"}),
        certifications=(Certification("cert-safety", expiry_offset=None),),
        availability_windows=((0, 3 * DAY),),
        standard_rate_per_hour=25.0, overtime_rate_per_hour=37.5,
    )
    task = TaskDef(
        id="task-1", location_id="loc-a", duration_minutes=120,
        earliest_start=8 * 60, latest_finish=18 * 60,
        crew_requirements=(CrewRequirement(role_id="role-electrician", quantity=1, required_skill_ids=("skill-basic",), required_cert_ids=("cert-safety",)),),
    )
    return SchedulingProblem(
        horizon_start=HORIZON_START, horizon_minutes=3 * DAY,
        tasks=[task], crew=[crew], equipment=[], dependencies=[],
        travel_matrix=make_travel_matrix(["loc-a"]), max_solve_seconds=10,
    )
