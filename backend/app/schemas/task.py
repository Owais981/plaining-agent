from datetime import datetime

from pydantic import BaseModel, ConfigDict


class CrewRequirementIn(BaseModel):
    role_id: str
    quantity: int = 1
    required_skill_ids: list[str] = []
    required_cert_ids: list[str] = []


class EquipmentRequirementIn(BaseModel):
    category_id: str
    quantity: int = 1
    min_capacity: float | None = None
    capacity_unit: str | None = None


class TaskCreate(BaseModel):
    project_id: str
    location_id: str
    name: str
    duration_minutes: int
    earliest_start: datetime | None = None
    latest_finish: datetime | None = None
    priority: int = 3
    requires_daylight: bool = False
    weather_sensitive: bool = False
    crew_requirements: list[CrewRequirementIn] = []
    equipment_requirements: list[EquipmentRequirementIn] = []


class TaskOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    project_id: str
    location_id: str
    name: str
    duration_minutes: int
    earliest_start: datetime | None
    latest_finish: datetime | None
    priority: int
    status: str


class DependencyCreate(BaseModel):
    predecessor_id: str
    successor_id: str
    lag_minutes: int = 0
    dependency_type: str = "FS"
