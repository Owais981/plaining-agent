from datetime import datetime

from sqlalchemy import String, Integer, SmallInteger, Boolean, Numeric, DateTime, ForeignKey, JSON
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.models.base import UUIDPKMixin


class Equipment(Base, UUIDPKMixin):
    __tablename__ = "equipment"

    asset_code: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    category_id: Mapped[str] = mapped_column(String(36), ForeignKey("equipment_categories.id"), nullable=False)
    model: Mapped[str] = mapped_column(String(255), default="")
    current_location_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("locations.id"))
    capacity_value: Mapped[float | None] = mapped_column(Numeric(10, 2))
    capacity_unit: Mapped[str | None] = mapped_column(String(20))
    operators_required: Mapped[int] = mapped_column(SmallInteger, default=1)
    required_operator_cert_ids: Mapped[list] = mapped_column(JSON, default=list)
    weight_kg: Mapped[float | None] = mapped_column(Numeric(10, 2))
    length_m: Mapped[float | None] = mapped_column(Numeric(6, 2))
    width_m: Mapped[float | None] = mapped_column(Numeric(6, 2))
    height_m: Mapped[float | None] = mapped_column(Numeric(6, 2))
    needs_transport: Mapped[bool] = mapped_column(Boolean, default=True)
    transport_type: Mapped[str] = mapped_column(String(50), default="self-drive")  # self-drive, flatbed, lowloader
    daily_operating_cost: Mapped[float | None] = mapped_column(Numeric(10, 2))
    transport_cost_per_km: Mapped[float | None] = mapped_column(Numeric(8, 2))
    ownership: Mapped[str] = mapped_column(String(20), default="owned")  # owned, rented
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class EquipmentMaintenance(Base, UUIDPKMixin):
    __tablename__ = "equipment_maintenance"

    equipment_id: Mapped[str] = mapped_column(String(36), ForeignKey("equipment.id", ondelete="CASCADE"), nullable=False)
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ends_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    maintenance_type: Mapped[str] = mapped_column(String(50), nullable=False)  # scheduled, breakdown, inspection
    blocks_usage: Mapped[bool] = mapped_column(Boolean, default=True)


class EquipmentAvailability(Base, UUIDPKMixin):
    __tablename__ = "equipment_availability"

    equipment_id: Mapped[str] = mapped_column(String(36), ForeignKey("equipment.id", ondelete="CASCADE"), nullable=False)
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ends_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    availability_type: Mapped[str] = mapped_column(String(20), nullable=False)
