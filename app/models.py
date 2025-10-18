"""
Pydantic models for SunSeat application.
Defines data structures for trip queries, advice, and API responses.
"""

from enum import Enum
from typing import List, Optional, Dict, Any
from datetime import datetime
from pydantic import BaseModel, Field, validator


class SeatAdvice(str, Enum):
    """Seat recommendation for a route segment."""
    LEFT = "LEFT"
    RIGHT = "RIGHT" 
    NEITHER = "NEITHER"


class CarriageFacing(str, Enum):
    """Direction the passenger's carriage is facing."""
    FORWARD = "forward"
    BACKWARD = "backward"
    UNKNOWN = "unknown"


class TransportMode(str, Enum):
    """Transport modes supported by the system."""
    TRAIN = "train"
    TRAM = "tram"
    BUS = "bus"
    VLINE = "vline"
    NIGHT_BUS = "night_bus"


class TripQuery(BaseModel):
    """Query parameters for trip advice."""
    origin_station: str = Field(..., description="Origin station name or ID")
    destination_station: str = Field(..., description="Destination station name or ID")
    line: str = Field(..., description="Line/service name")
    departure_date: str = Field(..., description="Departure date (YYYY-MM-DD)")
    departure_time: str = Field(..., description="Departure time (HH:MM)")
    facing: CarriageFacing = Field(default=CarriageFacing.UNKNOWN, description="Carriage facing direction")
    transport_mode: Optional[TransportMode] = Field(default=None, description="Transport mode")
    
    @validator('departure_date')
    def validate_date_format(cls, v):
        """Validate date format."""
        try:
            datetime.strptime(v, '%Y-%m-%d')
            return v
        except ValueError:
            raise ValueError('Date must be in YYYY-MM-DD format')
    
    @validator('departure_time')
    def validate_time_format(cls, v):
        """Validate time format."""
        try:
            datetime.strptime(v, '%H:%M')
            return v
        except ValueError:
            raise ValueError('Time must be in HH:MM format')


class SegmentAdvice(BaseModel):
    """Advice for a single route segment."""
    start_stop: str
    end_stop: str
    bearing_degrees: float
    solar_azimuth: float
    solar_altitude: float
    advice: SeatAdvice
    distance_km: float
    duration_minutes: float
    # Geometry for map rendering (optional)
    start_lat: Optional[float] = None
    start_lon: Optional[float] = None
    end_lat: Optional[float] = None
    end_lon: Optional[float] = None
    irradiance: Optional[float] = Field(None, description="Solar irradiance in W/m²")
    sun_intensity_index: Optional[int] = Field(None, description="Sun intensity index (0-10)")
    is_underground: bool = Field(False, description="Whether segment is underground")
    metadata: Optional[Dict[str, Any]] = Field(default_factory=dict, description="Additional segment metadata")


class DisruptionAlert(BaseModel):
    """Service disruption alert."""
    title: str
    description: str
    severity: Optional[str] = None
    url: Optional[str] = None
    affected_routes: List[str] = Field(default_factory=list)
    affected_stops: List[str] = Field(default_factory=list)


class AdviceSummary(BaseModel):
    """Summary of seat advice for the entire trip."""
    total_distance_km: float
    total_duration_minutes: float
    left_percentage: float
    right_percentage: float
    neither_percentage: float
    recommendation: str
    segments: List[SegmentAdvice]
    # Full route coordinate polyline for map rendering
    route_coordinates: Optional[List[List[float]]] = None
    disruptions: List[DisruptionAlert] = Field(default_factory=list, description="Active disruption alerts")
    sun_times: Optional[Dict[str, str]] = Field(None, description="Sunrise/sunset times")
    trip_metadata: Optional[Dict[str, Any]] = Field(default_factory=dict, description="Additional trip metadata")


class StopSearchResult(BaseModel):
    """Stop search result from PTV API."""
    stop_id: str
    stop_name: str
    stop_lat: float
    stop_lon: float
    zone_id: Optional[str] = None
    route_types: List[int] = Field(default_factory=list)
    distance_meters: Optional[float] = None


class RouteInfo(BaseModel):
    """Route information."""
    route_id: str
    route_name: str
    route_short_name: str
    route_type: int
    route_color: Optional[str] = None
    agency_name: Optional[str] = None


class TripLeg(BaseModel):
    """Individual leg of a multi-modal trip."""
    origin_stop: StopSearchResult
    destination_stop: StopSearchResult
    route: RouteInfo
    departure_time: str
    arrival_time: str
    duration_minutes: float
    advice_summary: Optional[AdviceSummary] = None


class MultiModalTripAdvice(BaseModel):
    """Advice for multi-modal trips (with transfers)."""
    legs: List[TripLeg]
    total_duration_minutes: float
    total_distance_km: float
    overall_recommendation: str
    transfer_count: int


class APIError(BaseModel):
    """Standard API error response."""
    error: str
    detail: Optional[str] = None
    error_code: Optional[str] = None


class APIResponse(BaseModel):
    """Standard API response wrapper."""
    success: bool
    data: Optional[Any] = None
    error: Optional[APIError] = None
    timestamp: datetime = Field(default_factory=datetime.now)


class CacheInfo(BaseModel):
    """Cache information for debugging."""
    cached: bool
    cache_age_seconds: Optional[float] = None
    cache_key: Optional[str] = None


class SystemStatus(BaseModel):
    """System status information."""
    gtfs_last_updated: Optional[datetime] = None
    realtime_status: bool = False
    solar_api_status: bool = False
    ptv_api_status: bool = False
    active_alerts_count: int = 0