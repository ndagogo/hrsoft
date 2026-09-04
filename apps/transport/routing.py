"""
Replaceable map / routing providers.

Default: Nominatim (geocode) + public OSRM (directions).
Swap via TRANSPORT_ROUTING settings without changing views.
"""
from __future__ import annotations

import json
import logging
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from django.conf import settings

logger = logging.getLogger("apps.transport.routing")


@dataclass
class GeoPoint:
    lat: float
    lng: float
    label: str = ""


@dataclass
class RouteResult:
    distance_km: Decimal
    duration_min: int
    geometry: dict[str, Any] = field(default_factory=dict)  # GeoJSON LineString
    provider: str = "osrm"
    waypoints: list[dict] = field(default_factory=list)


def _transport_settings() -> dict:
    return getattr(settings, "TRANSPORT_ROUTING", {})


def _http_get_json(url: str, timeout: int = 12, user_agent: str = "") -> dict | list | None:
    headers = {
        "Accept": "application/json",
        "User-Agent": user_agent or _transport_settings().get(
            "USER_AGENT", "HFDN-HRMS-Transport/1.0 (contact: hr@localhost)"
        ),
    }
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, json.JSONDecodeError, ValueError) as exc:
        logger.warning("Routing HTTP failed: %s (%s)", url[:120], exc)
        return None


def geocode(query: str, *, country_codes: str | None = None, limit: int = 5) -> list[dict]:
    """Return list of {label, lat, lng} from Nominatim (or configured geocoder)."""
    query = (query or "").strip()
    if len(query) < 2:
        return []
    cfg = _transport_settings()
    base = cfg.get("GEOCODER_URL", "https://nominatim.openstreetmap.org/search").rstrip("/")
    params = {
        "q": query,
        "format": "json",
        "addressdetails": "0",
        "limit": str(limit),
    }
    cc = country_codes or cfg.get("COUNTRY_CODES", "ng")
    if cc:
        params["countrycodes"] = cc
    url = f"{base}?{urllib.parse.urlencode(params)}"
    data = _http_get_json(url, timeout=int(cfg.get("TIMEOUT_SECONDS", 12)))
    if not isinstance(data, list):
        return []
    results = []
    for row in data:
        try:
            results.append({
                "label": row.get("display_name") or query,
                "lat": float(row["lat"]),
                "lng": float(row["lon"]),
            })
        except (KeyError, TypeError, ValueError):
            continue
    return results


def reverse_geocode(lat: float, lng: float) -> str:
    cfg = _transport_settings()
    base = cfg.get("REVERSE_GEOCODER_URL", "https://nominatim.openstreetmap.org/reverse").rstrip("/")
    params = {"lat": lat, "lon": lng, "format": "json"}
    url = f"{base}?{urllib.parse.urlencode(params)}"
    data = _http_get_json(url, timeout=int(cfg.get("TIMEOUT_SECONDS", 12)))
    if isinstance(data, dict):
        return data.get("display_name") or f"{lat:.5f}, {lng:.5f}"
    return f"{lat:.5f}, {lng:.5f}"


def route_between(points: list[GeoPoint]) -> RouteResult | None:
    """
    Drive route through ordered points via OSRM.
    points: [origin, stop1, stop2, ...]
    """
    if len(points) < 2:
        return None
    cfg = _transport_settings()
    provider = (cfg.get("PROVIDER") or "osrm").lower()
    if provider == "osrm":
        return _route_osrm(points, cfg)
    # Future: mapbox / google
    return _route_osrm(points, cfg)


def _route_osrm(points: list[GeoPoint], cfg: dict) -> RouteResult | None:
    base = cfg.get("OSRM_URL", "https://router.project-osrm.org").rstrip("/")
    coord = ";".join(f"{p.lng:.6f},{p.lat:.6f}" for p in points)
    url = (
        f"{base}/route/v1/driving/{coord}"
        f"?overview=full&geometries=geojson&steps=false&annotations=false"
    )
    data = _http_get_json(url, timeout=int(cfg.get("TIMEOUT_SECONDS", 15)))
    if not isinstance(data, dict) or data.get("code") != "Ok":
        return None
    routes = data.get("routes") or []
    if not routes:
        return None
    r0 = routes[0]
    metres = float(r0.get("distance") or 0)
    seconds = float(r0.get("duration") or 0)
    geometry = r0.get("geometry") or {}
    if geometry.get("type") != "LineString":
        geometry = {"type": "LineString", "coordinates": []}
    return RouteResult(
        distance_km=Decimal(str(round(metres / 1000.0, 2))),
        duration_min=max(1, int(round(seconds / 60.0))),
        geometry=geometry,
        provider="osrm",
        waypoints=[{"lat": p.lat, "lng": p.lng, "label": p.label} for p in points],
    )


def haversine_km(lat1, lng1, lat2, lng2) -> Decimal:
    """Fallback straight-line distance when OSRM is unreachable."""
    from math import asin, cos, radians, sin, sqrt

    r = 6371.0
    dlat = radians(float(lat2) - float(lat1))
    dlng = radians(float(lng2) - float(lng1))
    a = sin(dlat / 2) ** 2 + cos(radians(float(lat1))) * cos(radians(float(lat2))) * sin(dlng / 2) ** 2
    km = 2 * r * asin(sqrt(a))
    return Decimal(str(round(km, 2)))


def estimate_route_or_fallback(points: list[GeoPoint]) -> RouteResult:
    result = route_between(points)
    if result:
        return result
    # Fallback: sum haversine + assume 30 km/h urban
    total = Decimal("0")
    coords = []
    for i in range(len(points) - 1):
        total += haversine_km(points[i].lat, points[i].lng, points[i + 1].lat, points[i + 1].lng)
        coords.append([points[i].lng, points[i].lat])
    if points:
        coords.append([points[-1].lng, points[-1].lat])
    mins = max(1, int(round(float(total) / 30.0 * 60)))
    return RouteResult(
        distance_km=total,
        duration_min=mins,
        geometry={"type": "LineString", "coordinates": coords},
        provider="haversine",
        waypoints=[{"lat": p.lat, "lng": p.lng, "label": p.label} for p in points],
    )
