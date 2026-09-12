from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime


@dataclass
class Coordinate:
    location_id: str
    lat: float
    lon: float


@dataclass
class RouteResult:
    distance_km: float
    duration_minutes: int
    cost: float
    data_source: str          # 'osrm' | 'google_live' | 'haversine_estimate'
    confidence: str           # 'measured' | 'estimated'
    retrieved_at: datetime


class RoutingProvider(ABC):
    supports_traffic: bool = False
    name: str = "base"

    @abstractmethod
    async def matrix(
        self,
        origins: list[Coordinate],
        destinations: list[Coordinate],
        departure_time: datetime | None = None,
    ) -> dict[tuple[str, str], RouteResult]:
        """Return a route for every (origin, destination) pair keyed by
        (origin.location_id, destination.location_id)."""
        raise NotImplementedError
