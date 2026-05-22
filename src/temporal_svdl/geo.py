from __future__ import annotations

import math


def compute_bearing(from_lat: float, from_lng: float, to_lat: float, to_lng: float) -> float:
    """Return the compass bearing in [0, 360) degrees pointing from one coordinate to another."""
    lat1 = math.radians(from_lat)
    lat2 = math.radians(to_lat)
    d_lng = math.radians(to_lng - from_lng)

    x = math.sin(d_lng) * math.cos(lat2)
    y = math.cos(lat1) * math.sin(lat2) - math.sin(lat1) * math.cos(lat2) * math.cos(d_lng)
    return (math.degrees(math.atan2(x, y)) + 360) % 360
