"""
Core seat advice engine for SunSeat application.
Integrates GTFS data, real-time updates, and solar calculations to predict optimal seating.
"""

from datetime import datetime, timedelta
import os
from typing import List, Tuple, Optional, Dict, Any
import logging

from app.models import (
    SeatAdvice, CarriageFacing, SegmentAdvice, AdviceSummary, TripQuery
)
from app.solar import (
    get_solar_position_cached, is_sun_visible, is_underground_segment,
    get_sun_intensity_index, get_sun_times
)
from app.geometry import polyline_to_segments, calculate_bearing, calculate_distance
from app.gtfs import get_gtfs_loader
# Optional integrations: guard imports so core logic works without them
try:
    from app.realtime import get_realtime_client, get_trip_delay
except Exception:  # pragma: no cover
    def get_realtime_client():
        class _Dummy:
            def get_all_service_alerts(self):
                return []
        return _Dummy()

    def get_trip_delay(trip_id: str, stop_id: str):
        return 0

try:
    from app.ptv_client import create_ptv_client, RouteType
except Exception:  # pragma: no cover
    create_ptv_client = None
    class RouteType:
        TRAIN = 0
        TRAM = 1
        BUS = 2
        VLINE_TRAIN = 3

logger = logging.getLogger(__name__)


def calculate_segment_advice(
    bearing: float,
    solar_azimuth: float, 
    solar_altitude: float,
    irradiance: Optional[float] = None,
    is_underground: bool = False,
    facing: CarriageFacing = CarriageFacing.UNKNOWN
) -> Tuple[SeatAdvice, Dict[str, Any]]:
    """
    Calculate seat advice for a single segment with comprehensive logic.
    
    Args:
        bearing: Segment bearing in degrees (0-360, 0 is North)
        solar_azimuth: Solar azimuth in degrees (0-360, 0 is North)  
        solar_altitude: Solar altitude in degrees (-90 to 90)
        irradiance: Optional solar irradiance in W/m²
        is_underground: Whether segment is underground/tunnel
        facing: Direction passenger carriage is facing
        
    Returns:
        Tuple of (SeatAdvice, metadata_dict)
    """
    metadata = {
        'delta_angle': None,
        'sun_intensity': None,
        'is_underground': is_underground
    }
    
    # Underground segments have no sun exposure
    if is_underground:
        return SeatAdvice.NEITHER, metadata
    
    # If sun is too low, no significant impact
    if not is_sun_visible(solar_altitude, threshold=10.0):
        metadata['sun_intensity'] = "Below horizon"
        return SeatAdvice.NEITHER, metadata
    
    # Calculate relative angle Δ = (α − θ) mod 360
    # where α = solar azimuth, θ = bearing
    delta = (solar_azimuth - bearing + 360) % 360
    metadata['delta_angle'] = delta
    
    # Apply the core algorithm:
    # if h < 10° → "NEITHER" (already handled above)
    # if 0 < Δ < 180 → "RIGHT" 
    # if 180 ≤ Δ < 360 → "LEFT"
    if 0 < delta < 180:
        advice = SeatAdvice.RIGHT
    elif 180 <= delta < 360:
        advice = SeatAdvice.LEFT
    else:
        # delta == 0 or 180 (sun directly ahead/behind)
        advice = SeatAdvice.NEITHER
    
    # Adjust for carriage facing direction
    if facing == CarriageFacing.BACKWARD:
        if advice == SeatAdvice.LEFT:
            advice = SeatAdvice.RIGHT
        elif advice == SeatAdvice.RIGHT:
            advice = SeatAdvice.LEFT
    
    # Calculate sun intensity for metadata
    intensity_index, intensity_desc = get_sun_intensity_index(irradiance, solar_altitude)
    metadata['sun_intensity'] = intensity_desc
    metadata['intensity_index'] = intensity_index
    
    return advice, metadata


def get_trip_coordinates_from_ptv(trip_query: TripQuery) -> Tuple[List[Tuple[float, float]], List[str]]:
    """
    Get trip coordinates and stop names from PTV API and GTFS data.
    
    Args:
        trip_query: Trip query parameters
        
    Returns:
        Tuple of (coordinates, stop_names)
    """
    # Prefer PTV if available
    try:
        if create_ptv_client:
            ptv_client = create_ptv_client()
            # Search for origin and destination stops
            origin_stops = ptv_client.search_stops(trip_query.origin_station, max_results=5)
            dest_stops = ptv_client.search_stops(trip_query.destination_station, max_results=5)
            if origin_stops and dest_stops:
                origin_stop = origin_stops[0]
                dest_stop = dest_stops[0]
                coordinates = [
                    (origin_stop.get('stop_latitude') or origin_stop.get('stop_lat'), origin_stop.get('stop_longitude') or origin_stop.get('stop_lon')),
                    (dest_stop.get('stop_latitude') or dest_stop.get('stop_lat'), dest_stop.get('stop_longitude') or dest_stop.get('stop_lon'))
                ]
                stop_names = [origin_stop['stop_name'], dest_stop['stop_name']]
                if all(c[0] is not None and c[1] is not None for c in coordinates):
                    return coordinates, stop_names
    except Exception as e:
        logger.error(f"Failed to get trip coordinates from PTV: {e}")

    # Fallback: use GTFS to build an exact polyline along a matching trip for the line
    try:
        gtfs_loader = get_gtfs_loader()
        coords = gtfs_loader.get_polyline_for_route_between_stops(
            line_name=trip_query.line,
            origin=trip_query.origin_station,
            destination=trip_query.destination_station
        )
        # Build stop names list: origin, intermediate blanks, destination
        stop_names: List[str] = []
        if coords:
            stop_names = [trip_query.origin_station] + [""] * (max(0, len(coords) - 2)) + [trip_query.destination_station]
        if coords:
            return coords, stop_names
    except Exception as e:
        logger.error(f"GTFS fallback failed: {e}")

    # Optional: OSM/Overpass fallback for geometry if enabled
    try:
        if os.getenv("OSM_OVERPASS_ENABLED", "false").lower() in ("1", "true", "yes"): 
            from app.osm import build_route_via_osm
            coords = build_route_via_osm(
                line_name=trip_query.line,
                origin_name=trip_query.origin_station,
                dest_name=trip_query.destination_station
            )
            if coords:
                stop_names = [trip_query.origin_station] + [""] * (max(0, len(coords) - 2)) + [trip_query.destination_station]
                return coords, stop_names
    except Exception as e:
        logger.error(f"OSM fallback failed: {e}")

    return [], []


def generate_trip_advice_from_query(trip_query: TripQuery) -> AdviceSummary:
    """
    Generate seat advice from a trip query using all available data sources.
    
    Args:
        trip_query: Trip query with origin, destination, time, etc.
        
    Returns:
        Complete advice summary with segments and recommendations
    """
    try:
        # Parse departure time
        departure_datetime = datetime.fromisoformat(
            f"{trip_query.departure_date}T{trip_query.departure_time}"
        )
        
        # Get trip coordinates (from PTV API or GTFS)
        coordinates, stop_names = get_trip_coordinates_from_ptv(trip_query)
        route_source = "ptv/gtfs" if coordinates else "fallback"
        
        # Fallback to sample data if no coordinates found
        if not coordinates:
            logger.info("Using fallback sample route data")
            coordinates = [
                (-37.8136, 144.9631),  # Melbourne Central
                (-37.8183, 144.9671),  # Parliament
                (-37.8225, 144.9731),  # Richmond
                (-37.8342, 144.9764),  # South Yarra
            ]
            stop_names = ["Melbourne Central", "Parliament", "Richmond", "South Yarra"]
            route_source = "fallback"
        
        # Estimate trip duration (would come from GTFS/PTV in production)
        total_distance = sum(
            calculate_distance(coordinates[i][0], coordinates[i][1],
                             coordinates[i+1][0], coordinates[i+1][1])
            for i in range(len(coordinates) - 1)
        )
        
        # Estimate duration based on transport mode (rough estimates)
        speed_kmh = 35  # Average speed for metro trains
        duration_minutes = (total_distance / speed_kmh) * 60
        
        advice = generate_trip_advice(
            coordinates=coordinates,
            start_time=departure_datetime,
            total_duration_minutes=duration_minutes,
            stop_names=stop_names,
            facing=trip_query.facing
        )
        # annotate metadata
        try:
            advice.trip_metadata = {
                **(advice.trip_metadata or {}),
                "route_source": route_source,
                "origin": trip_query.origin_station,
                "destination": trip_query.destination_station,
                "line": trip_query.line
            }
        except Exception:
            pass
        return advice
        
    except Exception as e:
        logger.error(f"Failed to generate trip advice: {e}")
        return AdviceSummary(
            total_distance_km=0.0,
            total_duration_minutes=0.0,
            left_percentage=0.0,
            right_percentage=0.0,
            neither_percentage=100.0,
            recommendation="Unable to generate advice - please check your input",
            segments=[]
        )


def generate_trip_advice(
    coordinates: List[Tuple[float, float]],
    start_time: datetime,
    total_duration_minutes: float,
    stop_names: Optional[List[str]] = None,
    facing: CarriageFacing = CarriageFacing.UNKNOWN,
    trip_id: Optional[str] = None
) -> AdviceSummary:
    """
    Generate comprehensive seat advice for an entire trip.
    
    Args:
        coordinates: List of (lat, lon) points along the route
        start_time: Trip start time (timezone-aware)
        total_duration_minutes: Total trip duration in minutes
        stop_names: Optional list of stop names
        facing: Direction passenger carriage is facing
        trip_id: Optional GTFS trip ID for real-time data
        
    Returns:
        AdviceSummary with segment-by-segment advice and overall recommendation
    """
    if len(coordinates) < 2:
        return AdviceSummary(
            total_distance_km=0.0,
            total_duration_minutes=0.0,
            left_percentage=0.0,
            right_percentage=0.0,
            neither_percentage=100.0,
            recommendation="Insufficient route data",
            segments=[]
        )
    
    # Convert coordinates to segments
    segments_geo = polyline_to_segments(coordinates)
    
    if not segments_geo:
        return AdviceSummary(
            total_distance_km=0.0,
            total_duration_minutes=0.0,
            left_percentage=0.0,
            right_percentage=0.0,
            neither_percentage=100.0,
            recommendation="No route segments available",
            segments=[]
        )
    
    # Calculate total distance
    total_distance = sum(seg['distance_km'] for seg in segments_geo)
    
    # Generate segment advice
    segments_advice = []
    cumulative_time = 0.0
    
    for i, seg_geo in enumerate(segments_geo):
        # Calculate time for this segment based on distance proportion
        if total_distance > 0:
            segment_duration = (seg_geo['distance_km'] / total_distance) * total_duration_minutes
        else:
            segment_duration = total_duration_minutes / len(segments_geo)
        
        # Calculate time at segment midpoint
        midpoint_time = start_time + timedelta(minutes=cumulative_time + segment_duration / 2)
        
        # Check for real-time delays
        if trip_id:
            # This would require stop IDs - simplified for demo
            delay_seconds = get_trip_delay(trip_id, f"stop_{i}")
            if delay_seconds:
                midpoint_time += timedelta(seconds=delay_seconds)
        
        # Get solar position with irradiance at segment midpoint
        solar_azimuth, solar_altitude, irradiance = get_solar_position_cached(
            seg_geo['midpoint_lat'], 
            seg_geo['midpoint_lon'], 
            midpoint_time,
            include_irradiance=True
        )
        
        # Check if segment is underground
        is_underground = is_underground_segment(
            seg_geo['start_lat'], seg_geo['start_lon'],
            seg_geo['end_lat'], seg_geo['end_lon'],
            stop_names[i] if stop_names and i < len(stop_names) else None
        )
        
        # Calculate advice for this segment
        advice, metadata = calculate_segment_advice(
            seg_geo['bearing'], 
            solar_azimuth, 
            solar_altitude,
            irradiance,
            is_underground,
            facing
        )
        
        # Create segment advice
        start_stop = stop_names[i] if stop_names and i < len(stop_names) else f"Point {i+1}"
        end_stop = stop_names[i+1] if stop_names and i+1 < len(stop_names) else f"Point {i+2}"
        
        segment_advice = SegmentAdvice(
            start_stop=start_stop,
            end_stop=end_stop,
            bearing_degrees=seg_geo['bearing'],
            solar_azimuth=solar_azimuth,
            solar_altitude=solar_altitude,
            advice=advice,
            distance_km=seg_geo['distance_km'],
            duration_minutes=segment_duration,
            start_lat=seg_geo['start_lat'],
            start_lon=seg_geo['start_lon'],
            end_lat=seg_geo['end_lat'],
            end_lon=seg_geo['end_lon']
        )
        
        # Add metadata to segment
        segment_advice.metadata = metadata
        
        segments_advice.append(segment_advice)
        cumulative_time += segment_duration
    
    # Calculate percentages based on duration
    left_duration = sum(seg.duration_minutes for seg in segments_advice if seg.advice == SeatAdvice.LEFT)
    right_duration = sum(seg.duration_minutes for seg in segments_advice if seg.advice == SeatAdvice.RIGHT)
    neither_duration = sum(seg.duration_minutes for seg in segments_advice if seg.advice == SeatAdvice.NEITHER)
    
    total_actual_duration = left_duration + right_duration + neither_duration
    
    if total_actual_duration > 0:
        left_percentage = (left_duration / total_actual_duration) * 100
        right_percentage = (right_duration / total_actual_duration) * 100  
        neither_percentage = (neither_duration / total_actual_duration) * 100
    else:
        left_percentage = right_percentage = neither_percentage = 0.0
    
    # Generate enhanced recommendation with emoji
    recommendation = _generate_recommendation(
        left_percentage, right_percentage, neither_percentage,
        segments_advice, facing
    )
    
    return AdviceSummary(
        total_distance_km=total_distance,
        total_duration_minutes=total_actual_duration,
        left_percentage=left_percentage,
        right_percentage=right_percentage,
        neither_percentage=neither_percentage,
        recommendation=recommendation,
        segments=segments_advice,
        route_coordinates=[[lat, lon] for (lat, lon) in coordinates]
    )


def _generate_recommendation(
    left_percentage: float,
    right_percentage: float, 
    neither_percentage: float,
    segments: List[SegmentAdvice],
    facing: CarriageFacing
) -> str:
    """
    Generate enhanced recommendation text with emoji and context.
    
    Args:
        left_percentage: Percentage of time with left-side sun
        right_percentage: Percentage of time with right-side sun
        neither_percentage: Percentage of time with no significant sun
        segments: List of segment advice
        facing: Carriage facing direction
        
    Returns:
        Human-readable recommendation string
    """
    # Count high-intensity segments
    high_intensity_segments = sum(
        1 for seg in segments 
        if hasattr(seg, 'metadata') and 
        seg.metadata.get('intensity_index', 0) >= 7
    )
    
    # Base recommendation
    if left_percentage > right_percentage and left_percentage > 25:
        if left_percentage > 60:
            base_rec = f"☀️ Sit on the LEFT side - strong sun exposure for {left_percentage:.0f}% of journey"
        else:
            base_rec = f"🌤️ Prefer LEFT side - moderate sun exposure for {left_percentage:.0f}% of journey"
    elif right_percentage > left_percentage and right_percentage > 25:
        if right_percentage > 60:
            base_rec = f"☀️ Sit on the RIGHT side - strong sun exposure for {right_percentage:.0f}% of journey"
        else:
            base_rec = f"🌤️ Prefer RIGHT side - moderate sun exposure for {right_percentage:.0f}% of journey"
    elif neither_percentage > 70:
        base_rec = "🌫️ Any seat is fine - minimal sun exposure expected"
    else:
        base_rec = "⚖️ Sun exposure is evenly distributed - any seat is comfortable"
    
    # Add context about underground segments
    underground_count = sum(
        1 for seg in segments
        if hasattr(seg, 'metadata') and seg.metadata.get('is_underground', False)
    )
    
    if underground_count > 0:
        base_rec += f" ({underground_count} underground segment{'s' if underground_count > 1 else ''})"
    
    # Add intensity warning
    if high_intensity_segments > 0:
        base_rec += f" ⚠️ {high_intensity_segments} high-intensity segment{'s' if high_intensity_segments > 1 else ''}"
    
    # Add facing direction note
    if facing == CarriageFacing.BACKWARD:
        base_rec += " (adjusted for backward-facing seat)"
    
    return base_rec


def get_disruption_alerts(route_name: str) -> List[Dict[str, Any]]:
    """
    Get service disruption alerts for a route.
    
    Args:
        route_name: Route/line name
        
    Returns:
        List of disruption alert dictionaries
    """
    try:
        realtime_client = get_realtime_client()
        
        # Get all alerts and filter by route
        # This is simplified - would need proper route ID mapping
        alerts = realtime_client.get_all_service_alerts()
        
        route_alerts = []
        for alert in alerts:
            if any(route_name.lower() in route.lower() for route in alert.affected_routes):
                route_alerts.append({
                    'title': alert.header_text,
                    'description': alert.description_text,
                    'severity': alert.severity,
                    'url': alert.url
                })
        
        return route_alerts
        
    except Exception as e:
        logger.error(f"Failed to get disruption alerts: {e}")
        return []


def validate_trip_query(trip_query: TripQuery) -> Tuple[bool, Optional[str]]:
    """
    Validate trip query parameters.
    
    Args:
        trip_query: Trip query to validate
        
    Returns:
        Tuple of (is_valid, error_message)
    """
    try:
        # Validate date format
        departure_date = datetime.strptime(trip_query.departure_date, '%Y-%m-%d')
        
        # Validate time format
        departure_time = datetime.strptime(trip_query.departure_time, '%H:%M')
        
        # Check if date is not too far in past or future
        now = datetime.now()
        if departure_date.date() < now.date():
            return False, "Departure date cannot be in the past"
        
        if departure_date.date() > (now.date() + timedelta(days=90)):
            return False, "Departure date cannot be more than 90 days in the future"
        
        # Validate station names (basic check)
        if len(trip_query.origin_station.strip()) < 2:
            return False, "Origin station name too short"
        
        if len(trip_query.destination_station.strip()) < 2:
            return False, "Destination station name too short"
        
        if trip_query.origin_station.lower() == trip_query.destination_station.lower():
            return False, "Origin and destination must be different"
        
        return True, None
        
    except ValueError as e:
        return False, f"Invalid date or time format: {e}"
    except Exception as e:
        return False, f"Validation error: {e}"