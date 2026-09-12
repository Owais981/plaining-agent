from datetime import date, datetime

from sqlalchemy import String, Integer, SmallInteger, Boolean, Numeric, Date, DateTime, ForeignKey, JSON
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.models.base import UUIDPKMixin


class CrewMember(Base, UUIDPKMixin):
    __tablename__ = "crew_members"

    employee_code: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    full_name: Mapped[str] = mapped_column(String(255), nullable=False)
    primary_role_id: Mapped[str] = mapped_column(String(36), ForeignKey("roles.id"), nullable=False)
    home_location_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("locations.id"))
    max_hours_per_day: Mapped[int] = mapped_column(SmallInteger, default=10)
    max_hours_per_week: Mapped[int] = mapped_column(SmallInteger, default=48)
    min_rest_hours: Mapped[int] = mapped_column(SmallInteger, default=11)
    standard_rate: Mapped[float] = mapped_column(Numeric(8, 2), nullable=False)
    overtime_rate: Mapped[float] = mapped_column(Numeric(8, 2), nullable=False)
    max_travel_km: Mapped[int | None] = mapped_column(Integer)  # NULL = unrestricted
    can_stay_overnight: Mapped[bool] = mapped_column(Boolean, default=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class CrewSkill(Base):
    __tablename__ = "crew_skills"

    crew_member_id: Mapped[str] = mapped_column(String(36), ForeignKey("crew_members.id", ondelete="CASCADE"), primary_key=True)
    skill_id: Mapped[str] = mapped_column(String(36), ForeignKey("skills.id"), primary_key=True)
    proficiency: Mapped[int] = mapped_column(SmallInteger, default=3)  # 1-5


class CrewCertification(Base, UUIDPKMixin):
    __tablename__ = "crew_certifications"

    crew_member_id: Mapped[str] = mapped_column(String(36), ForeignKey("crew_members.id", ondelete="CASCADE"), nullable=False)
    certification_id: Mapped[str] = mapped_column(String(36), ForeignKey("certifications.id"), nullable=False)
    issued_date: Mapped[date] = mapped_column(Date, nullable=False)
    expiry_date: Mapped[date | None] = mapped_column(Date)
    document_ref: Mapped[str] = mapped_column(String(500), default="")


class CrewAvailability(Base, UUIDPKMixin):
    """Positive availability windows. Absence of a row = NOT available.
    This is a deliberate design choice (see build doc section 4/7): defaulting
    to "available" is how you end up scheduling someone who left months ago."""

    __tablename__ = "crew_availability"

    crew_member_id: Mapped[str] = mapped_column(String(36), ForeignKey("crew_members.id", ondelete="CASCADE"), nullable=False)
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ends_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    availability_type: Mapped[str] = mapped_column(String(20), nullable=False)  # available, leave, sick, training
