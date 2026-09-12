"""Simple reference/lookup tables: clients, roles, skills, certifications,
equipment categories, and users (for auth)."""
from sqlalchemy import String, Boolean
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.models.base import UUIDPKMixin, TimestampMixin


class Client(Base, UUIDPKMixin, TimestampMixin):
    __tablename__ = "clients"
    name: Mapped[str] = mapped_column(String(255), nullable=False)


class Role(Base, UUIDPKMixin):
    __tablename__ = "roles"
    name: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    description: Mapped[str] = mapped_column(String(500), default="")


class Skill(Base, UUIDPKMixin):
    __tablename__ = "skills"
    name: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    description: Mapped[str] = mapped_column(String(500), default="")


class Certification(Base, UUIDPKMixin):
    __tablename__ = "certifications"
    name: Mapped[str] = mapped_column(String(150), unique=True, nullable=False)
    description: Mapped[str] = mapped_column(String(500), default="")


class EquipmentCategory(Base, UUIDPKMixin):
    __tablename__ = "equipment_categories"
    name: Mapped[str] = mapped_column(String(150), unique=True, nullable=False)
    description: Mapped[str] = mapped_column(String(500), default="")


class User(Base, UUIDPKMixin, TimestampMixin):
    __tablename__ = "users"
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    full_name: Mapped[str] = mapped_column(String(255), default="")
    role: Mapped[str] = mapped_column(String(20), default="viewer")  # viewer, editor, approver, admin
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
