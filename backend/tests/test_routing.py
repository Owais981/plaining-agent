import asyncio

from app.routing.base import Coordinate
from app.routing.haversine import HaversineFallbackProvider, haversine_km


def test_haversine_distance_known_points():
    # London to Paris is ~344 km great-circle
    d = haversine_km(51.5074, -0.1278, 48.8566, 2.3522)
    assert 330 < d < 360


def test_haversine_provider_always_labels_estimate():
    provider = HaversineFallbackProvider()
    origins = [Coordinate("a", 51.5, -0.1)]
    dests = [Coordinate("b", 48.85, 2.35)]
    matrix = asyncio.run(provider.matrix(origins, dests))
    leg = matrix[("a", "b")]
    assert leg.data_source == "haversine_estimate"
    assert leg.confidence == "estimated"
    assert leg.duration_minutes > 0


def test_haversine_provider_skips_same_location():
    provider = HaversineFallbackProvider()
    origins = [Coordinate("a", 51.5, -0.1)]
    matrix = asyncio.run(provider.matrix(origins, origins))
    assert matrix == {}
