import math
from typing import List, Tuple


def calculate_bearing(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """
    Calculate the initial bearing (forward azimuth) between two points.
    
    Args:
        lat1, lon1: Starting point latitude and longitude in degrees
        lat2, lon2: Ending point latitude and longitude in degrees
        
    Returns:
        Bearing in degrees (0-360, where 0/360 is North, 90 is East)
    """
    if lat1 == lat2 and lon1 == lon2:
        return 0.0
        
    # Convert to radians
    lat1_rad = math.radians(lat1)
    lat2_rad = math.radians(lat2) 
    dlon_rad = math.radians(lon2 - lon1)
    
    # Calculate bearing
    y = math.sin(dlon_rad) * math.cos(lat2_rad)
    x = (math.cos(lat1_rad) * math.sin(lat2_rad) - 
         math.sin(lat1_rad) * math.cos(lat2_rad) * math.cos(dlon_rad))
    
    bearing_rad = math.atan2(y, x)
    bearing_deg = math.degrees(bearing_rad)
    
    # Normalize to 0-360
    return (bearing_deg + 360) % 360


def calculate_distance(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """
    Calculate the great circle distance between two points using Haversine formula.
    
    Args:
        lat1, lon1: Starting point latitude and longitude in degrees
        lat2, lon2: Ending point latitude and longitude in degrees
        
    Returns:
        Distance in kilometers
    """
    if lat1 == lat2 and lon1 == lon2:
        return 0.0
        
    # Convert to radians
    lat1_rad = math.radians(lat1)
    lat2_rad = math.radians(lat2)
    dlat_rad = math.radians(lat2 - lat1)
    dlon_rad = math.radians(lon2 - lon1)
    
    # Haversine formula
    a = (math.sin(dlat_rad / 2) ** 2 + 
         math.cos(lat1_rad) * math.cos(lat2_rad) * math.sin(dlon_rad / 2) ** 2)
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    
    # Earth's radius in kilometers
    earth_radius_km = 6371.0
    return earth_radius_km * c


def get_segment_midpoint(lat1: float, lon1: float, lat2: float, lon2: float) -> Tuple[float, float]:
    """
    Calculate the midpoint between two coordinates.
    
    Args:
        lat1, lon1: Starting point latitude and longitude in degrees
        lat2, lon2: Ending point latitude and longitude in degrees
        
    Returns:
        Tuple of (midpoint_lat, midpoint_lon) in degrees
    """
    mid_lat = (lat1 + lat2) / 2
    mid_lon = (lon1 + lon2) / 2
    return mid_lat, mid_lon


def polyline_to_segments(coordinates: List[Tuple[float, float]]) -> List[dict]:
    """
    Convert a polyline to a list of segments with bearing and distance.
    
    Args:
        coordinates: List of (lat, lon) tuples defining the polyline
        
    Returns:
        List of segment dictionaries with keys:
        - start_lat, start_lon: Starting coordinates
        - end_lat, end_lon: Ending coordinates  
        - bearing: Bearing in degrees (0-360)
        - distance_km: Segment distance in kilometers
        - midpoint_lat, midpoint_lon: Segment midpoint coordinates
    """
    if len(coordinates) < 2:
        return []
        
    segments = []
    for i in range(len(coordinates) - 1):
        lat1, lon1 = coordinates[i]
        lat2, lon2 = coordinates[i + 1]
        
        bearing = calculate_bearing(lat1, lon1, lat2, lon2)
        distance = calculate_distance(lat1, lon1, lat2, lon2)
        midpoint_lat, midpoint_lon = get_segment_midpoint(lat1, lon1, lat2, lon2)
        
        segments.append({
            'start_lat': lat1,
            'start_lon': lon1,
            'end_lat': lat2,
            'end_lon': lon2,
            'bearing': bearing,
            'distance_km': distance,
            'midpoint_lat': midpoint_lat,
            'midpoint_lon': midpoint_lon
        })
    
    return segments