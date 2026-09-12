from datetime import date, datetime

from pydantic import BaseModel, ConfigDict


class ProjectCreate(BaseModel):
    code: str
    name: str
    client_id: str | None = None
    start_date: date
    end_date: date
    deadline: datetime | None = None
    priority: int = 3
    budget_total: float | None = None
    currency: str = "USD"


class ProjectOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    code: str
    name: str
    client_id: str | None
    start_date: date
    end_date: date
    deadline: datetime | None
    priority: int
    budget_total: float | None
    currency: str
    status: str
