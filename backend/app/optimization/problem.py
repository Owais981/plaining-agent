"""Plain-Python problem definition for the scheduler. Deliberately has zero
SQLAlchemy/DB dependency so the solver and its tests can run against hand-built
in-memory problems (see build doc section 12, "known-answer tests").

All times are expressed as integer minutes offset from a shared `horizon_start`
epoch, which keeps the CP-SAT model's domains small integers instead of raw
timestamps.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass(frozen=True)
class CrewRequirement:
    role_id: str
    quantity: int = 1
    required_skill_ids: tuple[str, ...] = ()
    required_cert_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class EquipmentRequirement:
    category_id: str
    quantity: int = 1
    min_capacity: float | None = None


@dataclass(frozen=True)
class TaskDef:
    id: str
    location_id: str
    duration_minutes: int
    earliest_start: int  # minutes from horizon_start
    latest_finish: int   # minutes from horizon_start
    priority: int = 3
    crew_requirements: tuple[CrewRequirement, ...] = ()
    equipment_requirements: tuple[EquipmentRequirement, ...] = ()


@dataclass(frozen=True)
class Dependency:
    predecessor_id: str
    successor_id: str
    lag_minutes: int = 0
    dependency_type: str = "FS"  # FS, SS, FF, SF


@dataclass(frozen=True)
class Certification:
    certification_id: str
    expiry_offset: int | None  # minutes from horizon_start when it expires; None = never


@dataclass(frozen=True)
class CrewDef:
    id: str
    role_id: str
    home_location_id: str
    skill_ids: frozenset[str] = field(default_factory=frozenset)
    certifications: tuple[Certification, ...] = ()
    availability_windows: tuple[tuple[int, int], ...] = ()  # [(start,end), ...] minutes from horizon_start
    max_hours_per_day: int = 10
    max_hours_per_week: int = 48
    min_rest_hours: int = 11
    standard_rate_per_hour: float = 0.0
    overtime_rate_per_hour: float = 0.0
    max_travel_km: float | None = None

    def cert_ids_valid_through(self) -> frozenset[str]:
        return frozenset(c.certification_id for c in self.certifications)

    def is_cert_valid(self, cert_id: str, at_offset: int) -> bool:
        for c in self.certifications:
            if c.certification_id == cert_id:
                return c.expiry_offset is None or c.expiry_offset >= at_offset
        return False


@dataclass(frozen=True)
class EquipmentDef:
    id: str
    category_id: str
    current_location_id: str
    capacity_value: float | None = None
    operators_required: int = 1
    required_operator_cert_ids: tuple[str, ...] = ()
    availability_windows: tuple[tuple[int, int], ...] = ()
    maintenance_windows: tuple[tuple[int, int], ...] = ()
    daily_operating_cost: float = 0.0
    transport_cost_per_km: float = 0.0
    needs_transport: bool = True


@dataclass(frozen=True)
class TravelLeg:
    distance_km: float
    duration_minutes: int
    cost: float
    data_source: str = "haversine_estimate"
    confidence: str = "estimated"


@dataclass
class TravelMatrix:
    legs: dict[tuple[str, str], TravelLeg]

    def get(self, from_loc: str, to_loc: str) -> TravelLeg:
        if from_loc == to_loc:
            return TravelLeg(distance_km=0.0, duration_minutes=0, cost=0.0, data_source="same_location", confidence="measured")
        return self.legs[(from_loc, to_loc)]


@dataclass
class ObjectiveWeights:
    labour: float = 1.0
    overtime: float = 1.8
    travel: float = 1.2
    equipment: float = 1.0
    accommodation: float = 1.0
    imbalance: float = 0.3
    makespan: float = 0.5


@dataclass
class SchedulingProblem:
    horizon_start: datetime
    horizon_minutes: int
    tasks: list[TaskDef]
    crew: list[CrewDef]
    equipment: list[EquipmentDef]
    dependencies: list[Dependency]
    travel_matrix: TravelMatrix
    weights: ObjectiveWeights = field(default_factory=ObjectiveWeights)
    objective_profile: str = "balanced"
    locked_assignments: dict[str, dict] = field(default_factory=dict)  # task_id -> {crew_id, equipment_id, start}
    max_solve_seconds: int = 120
    num_workers: int = 8
    relative_gap: float = 0.02
    random_seed: int = 42

    def task_by_id(self, task_id: str) -> TaskDef:
        return next(t for t in self.tasks if t.id == task_id)


PROFILE_WEIGHT_OVERRIDES: dict[str, dict[str, float]] = {
    "balanced": {},
    "minimize_cost": {"labour": 2.0, "overtime": 2.5, "equipment": 1.5, "travel": 1.0, "makespan": 0.1},
    "minimize_travel": {"travel": 3.0, "labour": 1.0, "makespan": 0.3},
    "minimize_overtime": {"overtime": 4.0, "labour": 1.0, "imbalance": 1.0},
    "earliest_finish": {"makespan": 3.0, "labour": 0.8, "travel": 0.8},
}


def weights_for_profile(profile: str, base: ObjectiveWeights | None = None) -> ObjectiveWeights:
    base = base or ObjectiveWeights()
    overrides = PROFILE_WEIGHT_OVERRIDES.get(profile, {})
    values = {**base.__dict__, **overrides}
    return ObjectiveWeights(**values)
