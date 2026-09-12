"""Straight-line fallback provider. Always available, never fails, and is
ALWAYS tagged data_source='haversine_estimate' / confidence='estimated' so
downstream code and the UI never present it as measured travel (build doc
section 22 / rule 9)."""
from __future__ import annotations

import math
from datetime import datetime, timezone

from app.routing.base import RoutingProvider, RouteResult, Coordinate


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlambda / 2) ** 2
    return 2 * r * math.asin(min(1.0, math.sqrt(a)))


class HaversineFallbackProvider(RoutingProvider):
    supports_traffic = False
    name = "haversine"

    def __init__(self, road_winding_factor: float = 1.3, average_speed_kmh: float = 55.0, cost_per_km: float = 0.6):
        self.road_winding_factor = road_winding_factor
        self.average_speed_kmh = average_speed_kmh
        self.cost_per_km = cost_per_km

    async def matrix(self, origins, destinations, departure_time=None):
        results: dict[tuple[str, str], RouteResult] = {}
        now = datetime.now(timezone.utc)
        for o in origins:
            for d in destinations:
                if o.location_id == d.location_id:
                    continue
                straight = haversine_km(o.lat, o.lon, d.lat, d.lon)
                distance = straight * self.road_winding_factor
                duration = int(round(distance / self.average_speed_kmh * 60))
                results[(o.location_id, d.location_id)] = RouteResult(
                    distance_km=round(distance, 2),
                    duration_minutes=max(duration, 1),
                    cost=round(distance * self.cost_per_km, 2),
                    data_source="haversine_estimate",
                    confidence="estimated",
                    retrieved_at=now,
                )
        return results
