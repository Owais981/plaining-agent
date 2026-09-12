from sqlalchemy import String, Text, Float, JSON
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.models.base import UUIDPKMixin, TimestampMixin


class Location(Base, UUIDPKMixin, TimestampMixin):
    """Canonical location. lat/lon is the portable source of truth used by
    the routing layer everywhere (SQLite dev, Postgres prod, tests).

    On PostgreSQL, the initial Alembic migration additionally adds a
    generated `geom GEOGRAPHY(POINT,4326)` column with a GIST index so SQL
    callers can run spatial queries (e.g. "crew within 80km") directly --
    see alembic/versions/0001_initial_schema.py. The ORM does not map that
    column because GEOGRAPHY has no portable SQLite equivalent; all
    application code uses lat/lon + the routing service instead.
    """

    __tablename__ = "locations"

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    address: Mapped[str] = mapped_column(Text, default="")
    latitude: Mapped[float] = mapped_column(Float, nullable=False)
    longitude: Mapped[float] = mapped_column(Float, nullable=False)
    site_type: Mapped[str] = mapped_column(String(50), default="site")  # site, depot, office, accommodation
    access_notes: Mapped[str] = mapped_column(Text, default="")
    operating_hours: Mapped[dict] = mapped_column(JSON, default=dict)
