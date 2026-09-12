from __future__ import annotations

from datetime import datetime, timezone

import httpx

from app.routing.base import RoutingProvider, RouteResult
from app.routing.haversine import HaversineFallbackProvider


class GoogleRoutingProvider(RoutingProvider):
    """Google Distance Matrix provider. Requires GOOGLE_MAPS_API_KEY; the
    key is read from config/env only, never hardcoded, and never logged.
    Falls back to Haversine (clearly labeled) on any error or missing key."""

    supports_traffic = True
    name = "google"

    def __init__(self, api_key: str, cost_per_km: float = 0.6, timeout: float = 10.0):
        self.api_key = api_key
        self.cost_per_km = cost_per_km
        self.timeout = timeout
        self._fallback = HaversineFallbackProvider()

    async def matrix(self, origins, destinations, departure_time=None):
        if not self.api_key:
            return await self._fallback.matrix(origins, destinations, departure_time)

        url = "https://maps.googleapis.com/maps/api/distancematrix/json"
        params = {
            "origins": "|".join(f"{o.lat},{o.lon}" for o in origins),
            "destinations": "|".join(f"{d.lat},{d.lon}" for d in destinations),
            "key": self.api_key,
        }
        if departure_time:
            params["departure_time"] = str(int(departure_time.timestamp()))

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                resp = await client.get(url, params=params)
                resp.raise_for_status()
                data = resp.json()
                if data.get("status") != "OK":
                    raise ValueError(data.get("status"))
        except (httpx.HTTPError, ValueError, KeyError):
            return await self._fallback.matrix(origins, destinations, departure_time)

        now = datetime.now(timezone.utc)
        results: dict[tuple[str, str], RouteResult] = {}
        rows = data.get("rows", [])
        for i, o in enumerate(origins):
            elements = rows[i]["elements"] if i < len(rows) else []
            for j, d in enumerate(destinations):
                if o.location_id == d.location_id:
                    continue
                el = elements[j] if j < len(elements) else None
                if not el or el.get("status") != "OK":
                    continue
                distance_km = el["distance"]["value"] / 1000.0
                duration_field = el.get("duration_in_traffic", el["duration"])
                results[(o.location_id, d.location_id)] = RouteResult(
                    distance_km=round(distance_km, 2),
                    duration_minutes=max(int(round(duration_field["value"] / 60)), 1),
                    cost=round(distance_km * self.cost_per_km, 2),
                    data_source="google_live",
                    confidence="measured",
                    retrieved_at=now,
                )
        gaps = [(o, d) for o in origins for d in destinations
                if o.location_id != d.location_id and (o.location_id, d.location_id) not in results]
        if gaps:
            fb = await self._fallback.matrix([g[0] for g in gaps], [g[1] for g in gaps], departure_time)
            results.update(fb)
        return results
