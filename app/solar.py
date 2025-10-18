"""
Solar position and irradiance calculations.
Integrates Astral library for sun position with optional Solcast API for live irradiance data.
"""

from datetime import datetime, timedelta
from typing import Tuple, Optional, Dict, Any
from astral import LocationInfo
from astral.sun import sun, azimuth, elevation
from zoneinfo import ZoneInfo
import requests
import logging
import os
from functools import lru_cache
import json

logger = logging.getLogger(__name__)

# Cache for solar calculations (5-minute grid)
_solar_cache: Dict[str, Tuple[float, float, Optional[float]]] = {}


class SolarAPI:
    """
    Solar irradiance API client with Solcast integration.
    
    Provides live solar irradiance data with fallback to clear-sky models.
    """
    
    def __init__(self, api_key: Optional[str] = None):
        """
        Initialize solar API client.
        
        Args:
            api_key: Solcast API key (defaults to SOLCAST_API_KEY env var)
        """
        self.solcast_api_key = api_key or os.getenv("SOLCAST_API_KEY")
        self.base_url = "https://api.solcast.com.au"
        
    def get_live_irradiance(self, lat: float, lon: float, 
                           dt: Optional[datetime] = None) -> Optional[float]:
        """
        Get live solar irradiance from Solcast API.
        
        Args:
            lat: Latitude in degrees
            lon: Longitude in degrees
            dt: Datetime for forecast (defaults to now)
            
        Returns:
            Global Horizontal Irradiance (GHI) in W/m² or None if unavailable
        """
        if not self.solcast_api_key:
            logger.debug("No Solcast API key available")
            return None
        
        if dt is None:
            dt = datetime.now()
        
        try:
            # Format datetime for Solcast API
            dt_str = dt.strftime("%Y-%m-%dT%H:%M:%S.000Z")
            
            params = {
                "latitude": lat,
                "longitude": lon,
                "start": dt_str,
                "end": dt_str,
                "output_parameters": "ghi",
                "format": "json"
            }
            
            headers = {
                "Authorization": f"Bearer {self.solcast_api_key}"
            }
            
            response = requests.get(
                f"{self.base_url}/data/live/radiation_and_weather",
                params=params,
                headers=headers,
                timeout=10
            )
            
            if response.status_code == 200:
                data = response.json()
                if data.get("forecasts"):
                    return data["forecasts"][0].get("ghi")
            else:
                logger.warning(f"Solcast API error: {response.status_code}")
                
        except requests.RequestException as e:
            logger.error(f"Failed to fetch irradiance data: {e}")
        except (KeyError, IndexError, ValueError) as e:
            logger.error(f"Failed to parse Solcast response: {e}")
        
        return None
    
    def get_forecast_irradiance(self, lat: float, lon: float,
                               hours_ahead: int = 1) -> Optional[float]:
        """
        Get forecast solar irradiance.
        
        Args:
            lat: Latitude in degrees
            lon: Longitude in degrees
            hours_ahead: Hours into the future
            
        Returns:
            Forecast GHI in W/m² or None if unavailable
        """
        forecast_time = datetime.now() + timedelta(hours=hours_ahead)
        return self.get_live_irradiance(lat, lon, forecast_time)


def get_solar_position(lat: float, lon: float, dt: datetime) -> Tuple[float, float]:
    """
    Calculate solar azimuth and altitude at given location and time.
    
    Args:
        lat: Latitude in degrees
        lon: Longitude in degrees  
        dt: Datetime (should be timezone-aware)
        
    Returns:
        Tuple of (azimuth_degrees, altitude_degrees)
        - Azimuth: 0-360 degrees (0/360 is North, 90 is East, 180 is South, 270 is West)
        - Altitude: -90 to 90 degrees (negative means below horizon)
    """
    # Create location info for astral
    location = LocationInfo("temp", "temp", "UTC", lat, lon)
    
    # Ensure datetime is timezone-aware
    if dt.tzinfo is None:
        # Assume Melbourne timezone if naive
        melbourne_tz = ZoneInfo("Australia/Melbourne")
        dt = dt.replace(tzinfo=melbourne_tz)
    
    # Calculate solar position
    solar_azimuth = azimuth(location.observer, dt)
    solar_altitude = elevation(location.observer, dt)
    
    return solar_azimuth, solar_altitude


def get_solar_position_cached(lat: float, lon: float, dt: datetime,
                             include_irradiance: bool = True) -> Tuple[float, float, Optional[float]]:
    """
    Get solar position with caching and optional irradiance.
    
    Uses 5-minute grid caching to reduce computation and API calls.
    
    Args:
        lat: Latitude in degrees
        lon: Longitude in degrees
        dt: Datetime
        include_irradiance: Whether to fetch live irradiance data
        
    Returns:
        Tuple of (azimuth, altitude, irradiance)
        irradiance is None if not requested or unavailable
    """
    # Round to 5-minute grid for caching
    rounded_time = dt.replace(
        minute=(dt.minute // 5) * 5,
        second=0,
        microsecond=0
    )
    
    # Create cache key
    cache_key = f"{lat:.4f}_{lon:.4f}_{rounded_time.isoformat()}"
    
    if cache_key in _solar_cache:
        return _solar_cache[cache_key]
    
    # Calculate solar position
    azimuth_deg, altitude_deg = get_solar_position(lat, lon, rounded_time)
    
    # Get irradiance if requested
    irradiance = None
    if include_irradiance:
        solar_api = SolarAPI()
        irradiance = solar_api.get_live_irradiance(lat, lon, rounded_time)
    
    result = (azimuth_deg, altitude_deg, irradiance)
    
    # Cache result (limit cache size)
    if len(_solar_cache) > 1000:
        # Remove oldest entries
        oldest_keys = sorted(_solar_cache.keys())[:200]
        for key in oldest_keys:
            del _solar_cache[key]
    
    _solar_cache[cache_key] = result
    return result


def is_sun_visible(altitude: float, threshold: float = 10.0) -> bool:
    """
    Check if sun is visible (above threshold altitude).
    
    Args:
        altitude: Solar altitude in degrees
        threshold: Minimum altitude threshold in degrees (default 10°)
        
    Returns:
        True if sun is visible above threshold
    """
    return altitude >= threshold


def get_sun_times(lat: float, lon: float, date: datetime) -> Dict[str, datetime]:
    """
    Get sunrise/sunset times for a given location and date.
    
    Args:
        lat: Latitude in degrees
        lon: Longitude in degrees
        date: Date (timezone-aware datetime)
        
    Returns:
        Dictionary with 'sunrise' and 'sunset' datetime objects
    """
    location = LocationInfo("temp", "temp", "UTC", lat, lon)
    
    # Ensure datetime is timezone-aware
    if date.tzinfo is None:
        melbourne_tz = ZoneInfo("Australia/Melbourne")
        date = date.replace(tzinfo=melbourne_tz)
    
    sun_times = sun(location.observer, date=date.date(), tzinfo=date.tzinfo)
    
    return {
        'sunrise': sun_times['sunrise'],
        'sunset': sun_times['sunset'],
        'dawn': sun_times['dawn'],
        'dusk': sun_times['dusk'],
        'noon': sun_times['noon']
    }


def calculate_clear_sky_irradiance(altitude: float, azimuth: float,
                                  lat: float, dt: datetime) -> float:
    """
    Calculate clear-sky solar irradiance using simplified model.
    
    This provides a fallback when live irradiance data is unavailable.
    
    Args:
        altitude: Solar altitude in degrees
        azimuth: Solar azimuth in degrees
        lat: Latitude in degrees
        dt: Datetime
        
    Returns:
        Estimated clear-sky GHI in W/m²
    """
    if altitude <= 0:
        return 0.0
    
    # Simple clear-sky model based on solar altitude
    # Maximum clear-sky irradiance (around 1200 W/m² at sea level)
    max_irradiance = 1200.0
    
    # Air mass coefficient (simplified)
    air_mass = 1 / max(0.001, abs(altitude / 90.0))
    
    # Atmospheric attenuation
    transmission = 0.7 ** air_mass
    
    # Solar constant adjusted for altitude
    irradiance = max_irradiance * transmission * max(0, altitude / 90.0)
    
    # Seasonal adjustment (simple model)
    day_of_year = dt.timetuple().tm_yday
    seasonal_factor = 1 + 0.1 * abs(lat) / 90.0 * (1 - 2 * abs(day_of_year - 172) / 365)
    
    return irradiance * seasonal_factor


def get_sun_intensity_index(irradiance: Optional[float], altitude: float) -> Tuple[int, str]:
    """
    Calculate sun intensity index from irradiance and altitude.
    
    Args:
        irradiance: GHI in W/m² (None for clear-sky estimate)
        altitude: Solar altitude in degrees
        
    Returns:
        Tuple of (intensity_index, description)
        intensity_index: 0-10 scale (0=no sun, 10=maximum intensity)
        description: Human-readable intensity description
    """
    if altitude <= 0:
        return (0, "No sun (below horizon)")
    
    if altitude < 10:
        return (1, "Very low sun (near horizon)")
    
    # Use actual irradiance if available, otherwise estimate
    if irradiance is None:
        # Fallback to altitude-based estimate
        if altitude < 20:
            intensity = 2
            desc = "Low sun"
        elif altitude < 40:
            intensity = 5
            desc = "Moderate sun"
        elif altitude < 60:
            intensity = 7
            desc = "Strong sun"
        else:
            intensity = 8
            desc = "Very strong sun"
    else:
        # Scale irradiance to 0-10 index
        if irradiance < 100:
            intensity = 2
            desc = "Weak sun"
        elif irradiance < 300:
            intensity = 4
            desc = "Moderate sun"
        elif irradiance < 600:
            intensity = 6
            desc = "Strong sun"
        elif irradiance < 900:
            intensity = 8
            desc = "Very strong sun"
        else:
            intensity = 10
            desc = "Maximum sun intensity"
    
    return (intensity, desc)


def is_underground_segment(lat1: float, lon1: float, lat2: float, lon2: float,
                          segment_name: Optional[str] = None) -> bool:
    """
    Determine if a route segment is underground (tunnel/subway).
    
    Args:
        lat1, lon1: Start coordinates
        lat2, lon2: End coordinates  
        segment_name: Optional segment name for keyword detection
        
    Returns:
        True if segment is likely underground
    """
    # Melbourne CBD underground segments (approximate)
    underground_zones = [
        # City Loop stations
        {"lat_min": -37.8200, "lat_max": -37.8150, 
         "lon_min": 144.9600, "lon_max": 144.9700},
    ]
    
    # Check if segment passes through underground zones
    for zone in underground_zones:
        if (zone["lat_min"] <= lat1 <= zone["lat_max"] and 
            zone["lon_min"] <= lon1 <= zone["lon_max"]) or \
           (zone["lat_min"] <= lat2 <= zone["lat_max"] and 
            zone["lon_min"] <= lon2 <= zone["lon_max"]):
            return True
    
    # Check segment name for underground keywords
    if segment_name:
        underground_keywords = ["tunnel", "underground", "city loop", "parliament", "flagstaff"]
        segment_lower = segment_name.lower()
        if any(keyword in segment_lower for keyword in underground_keywords):
            return True
    
    return False


# Global solar API instance
_solar_api: Optional[SolarAPI] = None


def get_solar_api() -> SolarAPI:
    """Get global solar API instance."""
    global _solar_api
    if _solar_api is None:
        _solar_api = SolarAPI()
    return _solar_api