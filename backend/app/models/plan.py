from datetime import datetime

from sqlalchemy import String, Integer, Boolean, Numeric, DateTime, ForeignKey, JSON, Text, UniqueConstraint, CheckConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.models.base import UUIDPKMixin, TimestampMixin

PLAN_STATUSES = ("draft", "proposed", "approved", "superseded")
SOLVER_STATUSES = ("OPTIMAL", "FEASIBLE", "INFEASIBLE", "TIMEOUT")


class Plan(Base, UUIDPKMixin, TimestampMixin):
    __tablename__ = "plans"
    __table_args__ = (UniqueConstraint("project_id", "version"),)

    project_id: Mapped[str] = mapped_column(String(36), ForeignKey("projects.id"), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    parent_plan_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("plans.id"))
    scenario_label: Mapped[str] = mapped_column(String(100), default="baseline")
    status: Mapped[str] = mapped_column(String(20), default="draft")
    solver_status: Mapped[str | None] = mapped_column(String(20))
    objective_value: Mapped[float | None] = mapped_column(Numeric(14, 2))
    total_cost: Mapped[float | None] = mapped_column(Numeric(12, 2))
    total_travel_km: Mapped[float | None] = mapped_column(Numeric(10, 2))
    total_overtime_hrs: Mapped[float | None] = mapped_column(Numeric(8, 2))
    solve_seconds: Mapped[float | None] = mapped_column(Numeric(8, 2))
    input_snapshot: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    created_by: Mapped[str | None] = mapped_column(String(36), ForeignKey("users.id"))
    approved_by: Mapped[str | None] = mapped_column(String(36), ForeignKey("users.id"))
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    stale: Mapped[bool] = mapped_column(Boolean, default=False)


class PlanAssignment(Base, UUIDPKMixin):
    __tablename__ = "plan_assignments"

    plan_id: Mapped[str] = mapped_column(String(36), ForeignKey("plans.id", ondelete="CASCADE"), nullable=False)
    task_id: Mapped[str] = mapped_column(String(36), ForeignKey("tasks.id"), nullable=False)
    crew_member_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("crew_members.id"))
    equipment_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("equipment.id"))
    scheduled_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    scheduled_end: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    is_overtime: Mapped[bool] = mapped_column(Boolean, default=False)
    overtime_minutes: Mapped[int] = mapped_column(Integer, default=0)
    assignment_reason: Mapped[str] = mapped_column(Text, default="")


class PlanTravelLeg(Base, UUIDPKMixin):
    __tablename__ = "plan_travel_legs"

    plan_id: Mapped[str] = mapped_column(String(36), ForeignKey("plans.id", ondelete="CASCADE"), nullable=False)
    crew_member_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("crew_members.id"))
    equipment_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("equipment.id"))
    from_location_id: Mapped[str] = mapped_column(String(36), ForeignKey("locations.id"), nullable=False)
    to_location_id: Mapped[str] = mapped_column(String(36), ForeignKey("locations.id"), nullable=False)
    departure_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    arrival_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    distance_km: Mapped[float] = mapped_column(Numeric(8, 2), nullable=False)
    transport_mode: Mapped[str] = mapped_column(String(50), nullable=False)
    shared_vehicle_id: Mapped[str | None] = mapped_column(String(36))
    estimated_cost: Mapped[float | None] = mapped_column(Numeric(10, 2))
    data_source: Mapped[str] = mapped_column(String(30), nullable=False)  # osrm, google_live, haversine_estimate
    confidence: Mapped[str] = mapped_column(String(20), nullable=False, default="estimated")  # measured, estimated


class PlanConflict(Base, UUIDPKMixin):
    __tablename__ = "plan_conflicts"

    plan_id: Mapped[str] = mapped_column(String(36), ForeignKey("plans.id", ondelete="CASCADE"), nullable=False)
    severity: Mapped[str] = mapped_column(String(20), nullable=False)  # critical, warning, info
    conflict_type: Mapped[str] = mapped_column(String(50), nullable=False)
    entity_type: Mapped[str | None] = mapped_column(String(20))
    entity_id: Mapped[str | None] = mapped_column(String(36))
    description: Mapped[str] = mapped_column(Text, nullable=False)
    suggested_fix: Mapped[str] = mapped_column(Text, default="")


class PlanRisk(Base, UUIDPKMixin):
    __tablename__ = "plan_risks"

    plan_id: Mapped[str] = mapped_column(String(36), ForeignKey("plans.id", ondelete="CASCADE"), nullable=False)
    risk_type: Mapped[str] = mapped_column(String(50), nullable=False)
    severity: Mapped[str] = mapped_column(String(20), nullable=False)  # high, medium, low
    entity_type: Mapped[str | None] = mapped_column(String(20))
    entity_id: Mapped[str | None] = mapped_column(String(36))
    description: Mapped[str] = mapped_column(Text, nullable=False)
    mitigation: Mapped[str] = mapped_column(Text, default="")
