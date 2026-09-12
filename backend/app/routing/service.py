from __future__ import annotations

import json
from datetime import datetime, timezone

from app.config import get_settings
from app.routing.base import RoutingProvider, RouteResult, Coordinate
from app.routing.haversine import HaversineFallbackProvider
from app.routing.osrm import OSRMProvider
from app.routing.google import GoogleRoutingProvider

try:
    import redis as redis_lib
except ImportError:  # pragma: no cover
    redis_lib = None


def build_provider() -> RoutingProvider:
    settings = get_settings()
    if settings.routing_provider == "osrm" and settings.osrm_base_url:
        return OSRMProvider(settings.osrm_base_url)
    if settings.routing_provider == "google" and settings.google_maps_api_key:
        return GoogleRoutingProvider(settings.google_maps_api_key)
    return HaversineFallbackProvider(
        road_winding_factor=settings.road_winding_factor,
        average_speed_kmh=settings.average_speed_kmh,
    )


class RoutingService:
    """Distance/duration matrices with Redis caching and provenance
    tracking (build doc section 7 / 18 / 19)."""

    def __init__(self, provider: RoutingProvider | None = None, redis_client=None, cache_ttl_hours: int | None = None):
        settings = get_settings()
        self.provider = provider or build_provider()
        self.ttl_seconds = (cache_ttl_hours or settings.route_cache_ttl_hours) * 3600
        self._redis = redis_client
        if self._redis is None and redis_lib is not None:
            try:
                self._redis = redis_lib.from_url(settings.redis_url, socket_connect_timeout=0.5)
                self._redis.ping()
            except Exception:
                self._redis = None

    def _cache_key(self, from_id: str, to_id: str, departure_time: datetime | None) -> str:
        if departure_time and self.provider.supports_traffic:
            bucket = departure_time.strftime("%Y%m%d%H")
            return f"route:live:{from_id}:{to_id}:{bucket}"
        return f"route:static:{from_id}:{to_id}"

    def _get_cached(self, key: str) -> RouteResult | None:
        if not self._redis:
            return None
        raw = self._redis.get(key)
        if not raw:
            return None
        data = json.loads(raw)
        data["retrieved_at"] = datetime.fromisoformat(data["retrieved_at"])
        return RouteResult(**data)

    def _set_cached(self, key: str, result: RouteResult):
        if not self._redis:
            return
        payload = {
            "distance_km": result.distance_km,
            "duration_minutes": result.duration_minutes,
            "cost": result.cost,
            "data_source": result.data_source,
            "confidence": result.confidence,
            "retrieved_at": result.retrieved_at.isoformat(),
        }
        self._redis.setex(key, self.ttl_seconds, json.dumps(payload))

    async def build_matrix(self, locations: list[Coordinate], departure_time: datetime | None = None) -> dict[tuple[str, str], RouteResult]:
        matrix: dict[tuple[str, str], RouteResult] = {}
        missing_origins: list[Coordinate] = []
        missing_dests: list[Coordinate] = []
        pairs_needed = [(o, d) for o in locations for d in locations if o.location_id != d.location_id]

        for o, d in pairs_needed:
            key = self._cache_key(o.location_id, d.location_id, departure_time)
            cached = self._get_cached(key)
            if cached:
                matrix[(o.location_id, d.location_id)] = cached

        still_missing_pairs = [(o, d) for o, d in pairs_needed if (o.location_id, d.location_id) not in matrix]
        if still_missing_pairs:
            origins = list({o.location_id: o for o, _ in still_missing_pairs}.values())
            dests = list({d.location_id: d for _, d in still_missing_pairs}.values())
            fresh = await self.provider.matrix(origins, dests, departure_time)
            for (fid, tid), result in fresh.items():
                matrix[(fid, tid)] = result
                self._set_cached(self._cache_key(fid, tid, departure_time), result)

        return matrix
