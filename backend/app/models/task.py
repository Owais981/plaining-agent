from datetime import datetime

from sqlalchemy import String, Integer, SmallInteger, Boolean, DateTime, ForeignKey, JSON
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.models.base import UUIDPKMixin


class Task(Base, UUIDPKMixin):
    __tablename__ = "tasks"

    project_id: Mapped[str] = mapped_column(String(36), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    location_id: Mapped[str] = mapped_column(String(36), ForeignKey("locations.id"), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    duration_minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    earliest_start: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    latest_finish: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    priority: Mapped[int] = mapped_column(SmallInteger, default=3)
    requires_daylight: Mapped[bool] = mapped_column(Boolean, default=False)
    weather_sensitive: Mapped[bool] = mapped_column(Boolean, default=False)
    status: Mapped[str] = mapped_column(String(20), default="pending")


class TaskDependency(Base):
    __tablename__ = "task_dependencies"

    predecessor_id: Mapped[str] = mapped_column(String(36), ForeignKey("tasks.id", ondelete="CASCADE"), primary_key=True)
    successor_id: Mapped[str] = mapped_column(String(36), ForeignKey("tasks.id", ondelete="CASCADE"), primary_key=True)
    lag_minutes: Mapped[int] = mapped_column(Integer, default=0)
    dependency_type: Mapped[str] = mapped_column(String(10), default="FS")  # FS, SS, FF, SF


class TaskCrewRequirement(Base, UUIDPKMixin):
    __tablename__ = "task_crew_requirements"

    task_id: Mapped[str] = mapped_column(String(36), ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False)
    role_id: Mapped[str] = mapped_column(String(36), ForeignKey("roles.id"), nullable=False)
    quantity: Mapped[int] = mapped_column(SmallInteger, default=1)
    required_skill_ids: Mapped[list] = mapped_column(JSON, default=list)
    required_cert_ids: Mapped[list] = mapped_column(JSON, default=list)


class TaskEquipmentRequirement(Base, UUIDPKMixin):
    __tablename__ = "task_equipment_requirements"

    task_id: Mapped[str] = mapped_column(String(36), ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False)
    category_id: Mapped[str] = mapped_column(String(36), ForeignKey("equipment_categories.id"), nullable=False)
    quantity: Mapped[int] = mapped_column(SmallInteger, default=1)
    min_capacity: Mapped[float | None] = mapped_column()
    capacity_unit: Mapped[str | None] = mapped_column(String(20))
