from __future__ import annotations

from datetime import datetime, timezone

import httpx

from app.routing.base import RoutingProvider, RouteResult, Coordinate
from app.routing.haversine import HaversineFallbackProvider


class OSRMProvider(RoutingProvider):
    """Self-hosted OSRM table-service provider. Real HTTP calls, no
    hardcoded credentials -- base_url comes from OSRM_BASE_URL. Falls back
    to Haversine (clearly labeled) if the service is unreachable, per build
    doc section 18: "if routing provider is unavailable, fall back."""

    supports_traffic = False
    name = "osrm"

    def __init__(self, base_url: str, cost_per_km: float = 0.6, timeout: float = 10.0):
        self.base_url = base_url.rstrip("/")
        self.cost_per_km = cost_per_km
        self.timeout = timeout
        self._fallback = HaversineFallbackProvider()

    async def matrix(self, origins, destinations, departure_time=None):
        if not self.base_url:
            return await self._fallback.matrix(origins, destinations, departure_time)

        coords = origins + [d for d in destinations if d.location_id not in {o.location_id for o in origins}]
        coord_str = ";".join(f"{c.lon},{c.lat}" for c in coords)
        idx = {c.location_id: i for i, c in enumerate(coords)}
        src_idx = [idx[o.location_id] for o in origins]
        dst_idx = [idx[d.location_id] for d in destinations]
        url = f"{self.base_url}/table/v1/driving/{coord_str}"
        params = {
            "sources": ";".join(map(str, src_idx)),
            "destinations": ";".join(map(str, dst_idx)),
            "annotations": "distance,duration",
        }
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                resp = await client.get(url, params=params)
                resp.raise_for_status()
                data = resp.json()
        except (httpx.HTTPError, ValueError):
            return await self._fallback.matrix(origins, destinations, departure_time)

        now = datetime.now(timezone.utc)
        results: dict[tuple[str, str], RouteResult] = {}
        durations = data.get("durations", [])
        distances = data.get("distances", [])
        for i, o in enumerate(origins):
            for j, d in enumerate(destinations):
                if o.location_id == d.location_id:
                    continue
                try:
                    dur_s = durations[i][j]
                    dist_m = distances[i][j]
                except (IndexError, TypeError):
                    continue
                if dur_s is None or dist_m is None:
                    continue
                distance_km = dist_m / 1000.0
                results[(o.location_id, d.location_id)] = RouteResult(
                    distance_km=round(distance_km, 2),
                    duration_minutes=max(int(round(dur_s / 60)), 1),
                    cost=round(distance_km * self.cost_per_km, 2),
                    data_source="osrm",
                    confidence="measured",
                    retrieved_at=now,
                )
        # fill any missing pairs (unreachable in OSRM's graph) with fallback estimate
        missing_o = [o for o in origins]
        missing_d = [d for d in destinations]
        gaps = [(o, d) for o in missing_o for d in missing_d
                if o.location_id != d.location_id and (o.location_id, d.location_id) not in results]
        if gaps:
            fb = await self._fallback.matrix([g[0] for g in gaps], [g[1] for g in gaps], departure_time)
            results.update(fb)
        return results
