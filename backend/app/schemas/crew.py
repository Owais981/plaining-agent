from datetime import date, datetime

from pydantic import BaseModel, ConfigDict


class CrewMemberCreate(BaseModel):
    employee_code: str
    full_name: str
    primary_role_id: str
    home_location_id: str | None = None
    max_hours_per_day: int = 10
    max_hours_per_week: int = 48
    min_rest_hours: int = 11
    standard_rate: float
    overtime_rate: float
    max_travel_km: int | None = None
    can_stay_overnight: bool = True


class CrewMemberOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    employee_code: str
    full_name: str
    primary_role_id: str
    home_location_id: str | None
    standard_rate: float
    overtime_rate: float
    is_active: bool


class CrewAvailabilityCreate(BaseModel):
    crew_member_id: str
    starts_at: datetime
    ends_at: datetime
    availability_type: str = "available"


class CrewCertificationCreate(BaseModel):
    crew_member_id: str
    certification_id: str
    issued_date: date
    expiry_date: date | None = None
    document_ref: str = ""
