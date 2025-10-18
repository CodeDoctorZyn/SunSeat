"""
OSM/Overpass helper utilities for railway line geometry and station lookup.
These functions are optional and only used if OSM_OVERPASS_ENABLED is set.
"""

from typing import List, Tuple, Optional
import os
import requests
import logging
from shapely.geometry import LineString, Point
import time

logger = logging.getLogger(__name__)


def _overpass_url() -> str:
    return os.getenv("OSM_OVERPASS_URL", "https://overpass-api.de/api/interpreter")


# Simple in-memory TTL cache
_CACHE: dict = {}


def _ttl_seconds() -> int:
    try:
        return int(os.getenv("OSM_CACHE_TTL", "1800"))  # default 30 minutes
    except Exception:
        return 1800


def _cache_get(key: str):
    item = _CACHE.get(key)
    if not item:
        return None
    ts, value = item
    if (time.time() - ts) < _ttl_seconds():
        return value
    # expired
    try:
        del _CACHE[key]
    except KeyError:
        pass
    return None


def _cache_set(key: str, value):
    # simple size cap
    if len(_CACHE) > 512:
        # drop ~20% oldest
        for k in list(_CACHE.keys())[:100]:
            _CACHE.pop(k, None)
    _CACHE[key] = (time.time(), value)


def _run_overpass(query: str) -> Optional[dict]:
    try:
        # Cache raw query results as well, since identical queries are common
        ckey = f"raw:{hash(query)}"
        cached = _cache_get(ckey)
        if cached is not None:
            return cached
        resp = requests.post(_overpass_url(), data={"data": query}, timeout=20)
        resp.raise_for_status()
        data = resp.json()
        _cache_set(ckey, data)
        return data
    except Exception as e:
        logger.error(f"Overpass query failed: {e}")
        return None


def find_station_coords(name: str) -> Optional[Tuple[float, float]]:
    """Find station coordinates by name around Melbourne/Victoria (approx bbox)."""
    if not name or len(name.strip()) < 2:
        return None
    # Approx bounding box around Greater Melbourne
    # south,west,north,east
    bbox = "-38.3,144.3,-37.3,145.6"
    q = f"""
    [out:json][timeout:25];
    node({bbox})[railway=station][name~"{name}",i];
    out center 1;
    """
    # Cache by normalized name
    nkey = f"station:{name.strip().lower()}"
    cached = _cache_get(nkey)
    if cached is not None:
        return cached

    data = _run_overpass(q)
    if not data or not data.get("elements"):
        return None
    el = data["elements"][0]
    lat = el.get("lat")
    lon = el.get("lon")
    if lat is None or lon is None:
        return None
    coord = (float(lat), float(lon))
    _cache_set(nkey, coord)
    return coord


def get_line_polyline(line_name: str) -> List[Tuple[float, float]]:
    """Fetch an approximate polyline for a rail line by name using OSM route relations."""
    if not line_name:
        return []
    # Try route=train or route=railway relations with a matching name
    # Cache by normalized line name
    lkey = f"line:{line_name.strip().lower()}"
    cached = _cache_get(lkey)
    if cached is not None:
        return cached

    q = f"""
    [out:json][timeout:40];
    relation[route~"^(train|railway)$"][name~"{line_name}",i];
    (._; >;);
    out body;
    """
    data = _run_overpass(q)
    if not data:
        return []
    nodes = {el['id']: (el.get('lat'), el.get('lon')) for el in data.get('elements', []) if el.get('type') == 'node'}
    coords: List[Tuple[float, float]] = []
    # Assemble ways in order they appear; this is a naive chaining
    for el in data.get('elements', []):
        if el.get('type') == 'way':
            way_nodes = el.get('nodes', [])
            for nid in way_nodes:
                pt = nodes.get(nid)
                if pt and pt[0] is not None and pt[1] is not None:
                    coords.append((float(pt[0]), float(pt[1])))
    # Deduplicate successive duplicates
    dedup: List[Tuple[float, float]] = []
    for c in coords:
        if not dedup or dedup[-1] != c:
            dedup.append(c)
    _cache_set(lkey, dedup)
    return dedup


def get_segment_between_points(polyline: List[Tuple[float, float]], start: Tuple[float, float], end: Tuple[float, float]) -> List[Tuple[float, float]]:
    """Cut a polyline between the nearest points to start and end."""
    if len(polyline) < 2:
        return []
    try:
        line = LineString([(lon, lat) for lat, lon in polyline])
        p_start = Point(start[1], start[0])
        p_end = Point(end[1], end[0])
        i_start = line.project(p_start, normalized=False)
        i_end = line.project(p_end, normalized=False)
        if i_start > i_end:
            i_start, i_end = i_end, i_start
        sub = line.segmentize(0.0001) if hasattr(line, 'segmentize') else line
        cut = sub.interpolate(i_start), sub.interpolate(i_end)
        # Extract coordinates between indices by sampling along the line
        # Simpler: pick indices by nearest vertex
        def nearest_idx(pt: Point) -> int:
            min_d = 1e9
            min_i = 0
            for i, (lat, lon) in enumerate(polyline):
                d = (pt.y - lat) ** 2 + (pt.x - lon) ** 2
                if d < min_d:
                    min_d = d
                    min_i = i
            return min_i
        s_idx = nearest_idx(cut[0])
        e_idx = nearest_idx(cut[1])
        if s_idx > e_idx:
            s_idx, e_idx = e_idx, s_idx
        return polyline[s_idx:e_idx+1]
    except Exception:
        return []


def build_route_via_osm(line_name: str, origin_name: str, dest_name: str) -> List[Tuple[float, float]]:
    """High-level helper: station coords + line polyline -> subsegment polyline."""
    start = find_station_coords(origin_name)
    end = find_station_coords(dest_name)
    if not start or not end:
        return []
    poly = get_line_polyline(line_name)
    if not poly:
        return []
    seg = get_segment_between_points(poly, start, end)
    # fallback to direct if cutting failed
    return seg or [start, end]
