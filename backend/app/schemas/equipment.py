from datetime import datetime

from pydantic import BaseModel, ConfigDict


class EquipmentCreate(BaseModel):
    asset_code: str
    name: str
    category_id: str
    model: str = ""
    current_location_id: str | None = None
    capacity_value: float | None = None
    capacity_unit: str | None = None
    operators_required: int = 1
    required_operator_cert_ids: list[str] = []
    needs_transport: bool = True
    transport_type: str = "self-drive"
    daily_operating_cost: float | None = None
    transport_cost_per_km: float | None = None
    ownership: str = "owned"


class EquipmentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    asset_code: str
    name: str
    category_id: str
    current_location_id: str | None
    daily_operating_cost: float | None
    ownership: str
    is_active: bool


class EquipmentAvailabilityCreate(BaseModel):
    equipment_id: str
    starts_at: datetime
    ends_at: datetime
    availability_type: str = "available"


class EquipmentMaintenanceCreate(BaseModel):
    equipment_id: str
    starts_at: datetime
    ends_at: datetime
    maintenance_type: str = "scheduled"
    blocks_usage: bool = True
