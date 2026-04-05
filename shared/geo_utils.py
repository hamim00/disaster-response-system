"""
Shared geo utilities: Haversine distance, GeoJSON helpers.
Note: Pydantic models use (latitude, longitude) order.
      GeoJSON and PostGIS use (longitude, latitude) order.
"""
import math
from typing import List, Tuple


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """
    Calculate great-circle distance between two points in kilometres.
    Args use (latitude, longitude) convention.
    """
    R = 6371.0  # Earth radius in km
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)

    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return R * 2 * math.asin(math.sqrt(a))


def straight_line_geojson(
    origin_lat: float, origin_lon: float,
    dest_lat: float, dest_lon: float,
) -> dict:
    """
    Build a GeoJSON LineString for a straight-line (boat) route.
    Coordinates are (longitude, latitude) per GeoJSON spec.
    """
    return {
        "type": "LineString",
        "coordinates": [
            [origin_lon, origin_lat],
            [dest_lon, dest_lat],
        ],
    }


def point_geojson(lat: float, lon: float) -> dict:
    """Build a GeoJSON Point. Coordinates are (longitude, latitude)."""
    return {"type": "Point", "coordinates": [lon, lat]}


def geojson_to_wkt_point(lat: float, lon: float) -> str:
    """Convert lat/lon to PostGIS-compatible WKT POINT string."""
    return f"SRID=4326;POINT({lon} {lat})"


def linestring_coords(geojson: dict) -> List[Tuple[float, float]]:
    """
    Extract (lon, lat) coordinate pairs from a GeoJSON LineString.
    Returns list of (longitude, latitude) tuples (GeoJSON order).
    """
    if geojson.get("type") != "LineString":
        return []
    return [(c[0], c[1]) for c in geojson.get("coordinates", [])]
