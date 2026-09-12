"""Post-processing pass that groups crew travelling to the same destination
into shared vehicles, rather than adding O(crew^2) variables to the core
CP-SAT model for a soft, non-critical optimization (build doc section 20)."""
from __future__ import annotations

import uuid
from collections import defaultdict
from dataclasses import dataclass, replace


@dataclass
class TravelLegRecord:
    crew_member_id: str
    from_location_id: str
    to_location_id: str
    departure_time: object  # datetime
    arrival_time: object
    distance_km: float
    origin_lat: float
    origin_lon: float
    shared_vehicle_id: str | None = None


def _round_to_bucket(dt, minutes: int = 30):
    discard = dt.minute % minutes
    return dt.replace(minute=dt.minute - discard, second=0, microsecond=0)


def group_shared_transport(legs: list[TravelLegRecord], vehicle_seats: int = 4, max_detour_km: float = 15.0) -> list[TravelLegRecord]:
    clusters: dict[tuple, list[TravelLegRecord]] = defaultdict(list)
    for leg in legs:
        window = _round_to_bucket(leg.arrival_time)
        clusters[(leg.to_location_id, window)].append(leg)

    grouped: list[TravelLegRecord] = []
    for (_, _), cluster_legs in clusters.items():
        if len(cluster_legs) < 2:
            grouped.extend(cluster_legs)
            continue
        remaining = list(cluster_legs)
        while remaining:
            anchor = remaining.pop(0)
            bucket = [anchor]
            still_remaining = []
            for leg in remaining:
                dx = (leg.origin_lat - anchor.origin_lat) ** 2 + (leg.origin_lon - anchor.origin_lon) ** 2
                if len(bucket) < vehicle_seats and dx ** 0.5 * 111 <= max_detour_km:
                    bucket.append(leg)
                else:
                    still_remaining.append(leg)
            remaining = still_remaining
            if len(bucket) > 1:
                vehicle_id = str(uuid.uuid4())
                grouped.extend(replace(leg, shared_vehicle_id=vehicle_id) for leg in bucket)
            else:
                grouped.extend(bucket)
    return grouped
