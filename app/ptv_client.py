"""
PTV API v3 Client with HMAC authentication.
Handles all PTV Timetable API endpoints with proper authentication.
"""

import hmac
import hashlib
import urllib.parse
from typing import Dict, List, Optional, Any
import requests
import os
from datetime import datetime
import logging

logger = logging.getLogger(__name__)


class PTVClient:
    """
    Client for PTV Timetable API v3 with HMAC authentication.
    
    Provides methods to interact with PTV's REST API for routes, stops,
    departures, disruptions, and other transport data.
    """
    
    def __init__(self, user_id: Optional[str] = None, api_key: Optional[str] = None):
        """
        Initialize PTV API client.
        
        Args:
            user_id: PTV API user ID (defaults to PTV_USER_ID env var)
            api_key: PTV API key (defaults to PTV_API_KEY env var)
        """
        self.user_id = user_id or os.getenv("PTV_USER_ID")
        self.api_key = api_key or os.getenv("PTV_API_KEY")
        self.base_url = "https://timetableapi.ptv.vic.gov.au"
        
        if not self.user_id or not self.api_key:
            raise ValueError("PTV_USER_ID and PTV_API_KEY must be provided")
    
    def _generate_signature(self, request_path: str) -> str:
        """
        Generate HMAC-SHA1 signature for PTV API request.
        
        Args:
            request_path: API endpoint path including query parameters
            
        Returns:
            Uppercase hexadecimal HMAC signature
        """
        raw_signature = hmac.new(
            self.api_key.encode('utf-8'),
            request_path.encode('utf-8'),
            hashlib.sha1
        ).hexdigest().upper()
        
        return raw_signature
    
    def _make_request(self, endpoint: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        Make authenticated request to PTV API.
        
        Args:
            endpoint: API endpoint path (e.g., "/v3/routes")
            params: Query parameters
            
        Returns:
            JSON response data
            
        Raises:
            requests.RequestException: If API request fails
        """
        if params is None:
            params = {}
        
        # Add devid to parameters
        params["devid"] = self.user_id
        
        # Build query string
        query_string = urllib.parse.urlencode(params)
        request_path = f"{endpoint}?{query_string}"
        
        # Generate signature
        signature = self._generate_signature(request_path)
        
        # Add signature to URL
        full_url = f"{self.base_url}{request_path}&signature={signature}"
        
        logger.debug(f"Making PTV API request to: {endpoint}")
        
        response = requests.get(full_url, timeout=30)
        response.raise_for_status()
        
        return response.json()
    
    def get_routes(self, route_types: Optional[List[int]] = None) -> List[Dict[str, Any]]:
        """
        Get all routes, optionally filtered by transport type.
        
        Args:
            route_types: List of route types (0=Train, 1=Tram, 2=Bus, 3=V/Line train, 4=Night Bus)
            
        Returns:
            List of route objects
        """
        params = {}
        if route_types:
            params["route_types"] = ",".join(map(str, route_types))
        
        response = self._make_request("/v3/routes", params)
        return response.get("routes", [])
    
    def get_route_by_id(self, route_id: int, route_type: int) -> Dict[str, Any]:
        """
        Get route details by ID.
        
        Args:
            route_id: Route ID
            route_type: Route type (0-4)
            
        Returns:
            Route object
        """
        response = self._make_request(f"/v3/routes/{route_id}/route_type/{route_type}")
        return response.get("route", {})
    
    def search_stops(self, search_term: str, route_types: Optional[List[int]] = None,
                     latitude: Optional[float] = None, longitude: Optional[float] = None,
                     max_distance: Optional[float] = None, max_results: int = 30) -> List[Dict[str, Any]]:
        """
        Search for stops by name or location.
        
        Args:
            search_term: Stop name search term
            route_types: Filter by route types
            latitude: Latitude for location-based search
            longitude: Longitude for location-based search
            max_distance: Maximum distance in meters for location search
            max_results: Maximum number of results
            
        Returns:
            List of stop objects
        """
        params = {
            "search_term": search_term,
            "max_results": max_results
        }
        
        if route_types:
            params["route_types"] = ",".join(map(str, route_types))
        if latitude is not None:
            params["latitude"] = latitude
        if longitude is not None:
            params["longitude"] = longitude
        if max_distance is not None:
            params["max_distance"] = max_distance
        
        response = self._make_request("/v3/search", params)
        return response.get("stops", [])
    
    def get_stop_details(self, stop_id: int, route_type: int, 
                        include_accessibility: bool = True) -> Dict[str, Any]:
        """
        Get detailed stop information.
        
        Args:
            stop_id: Stop ID
            route_type: Route type
            include_accessibility: Include accessibility information
            
        Returns:
            Stop object with details
        """
        params = {}
        if include_accessibility:
            params["stop_accessibility"] = "true"
        
        response = self._make_request(f"/v3/stops/{stop_id}/route_type/{route_type}", params)
        return response.get("stop", {})
    
    def get_departures_by_stop(self, route_type: int, stop_id: int,
                              route_id: Optional[int] = None,
                              direction_id: Optional[int] = None,
                              datetime_utc: Optional[datetime] = None,
                              max_results: int = 5,
                              include_cancelled: bool = False,
                              expand: Optional[List[str]] = None) -> Dict[str, Any]:
        """
        Get departures from a stop.
        
        Args:
            route_type: Route type (0-4)
            stop_id: Stop ID
            route_id: Filter by specific route
            direction_id: Filter by direction (0 or 1)
            datetime_utc: Get departures from this time (UTC)
            max_results: Maximum number of departures
            include_cancelled: Include cancelled services
            expand: Additional data to include (route, run, direction, stop, disruption)
            
        Returns:
            Departures response with departures, routes, runs, directions, stops
        """
        params = {"max_results": max_results}
        
        if route_id is not None:
            params["route_id"] = route_id
        if direction_id is not None:
            params["direction_id"] = direction_id
        if datetime_utc:
            params["date_utc"] = datetime_utc.strftime("%Y-%m-%dT%H:%M:%SZ")
        if include_cancelled:
            params["include_cancelled"] = "true"
        if expand:
            params["expand"] = ",".join(expand)
        
        endpoint = f"/v3/departures/route_type/{route_type}/stop/{stop_id}"
        response = self._make_request(endpoint, params)
        return response
    
    def get_route_directions(self, route_id: int, route_type: int) -> List[Dict[str, Any]]:
        """
        Get directions for a route.
        
        Args:
            route_id: Route ID
            route_type: Route type
            
        Returns:
            List of direction objects
        """
        endpoint = f"/v3/directions/route/{route_id}/route_type/{route_type}"
        response = self._make_request(endpoint)
        return response.get("directions", [])
    
    def get_stops_on_route(self, route_id: int, route_type: int,
                          direction_id: Optional[int] = None) -> List[Dict[str, Any]]:
        """
        Get all stops on a route.
        
        Args:
            route_id: Route ID  
            route_type: Route type
            direction_id: Filter by direction
            
        Returns:
            List of stop objects on the route
        """
        params = {}
        if direction_id is not None:
            params["direction_id"] = direction_id
            
        endpoint = f"/v3/stops/route/{route_id}/route_type/{route_type}"
        response = self._make_request(endpoint, params)
        return response.get("stops", [])
    
    def get_disruptions(self, route_id: Optional[int] = None,
                       stop_id: Optional[int] = None,
                       disruption_modes: Optional[List[int]] = None) -> List[Dict[str, Any]]:
        """
        Get current disruptions.
        
        Args:
            route_id: Filter by route ID
            stop_id: Filter by stop ID  
            disruption_modes: Filter by disruption modes
            
        Returns:
            List of disruption objects
        """
        params = {}
        
        if route_id is not None:
            params["route_id"] = route_id
        if stop_id is not None:
            params["stop_id"] = stop_id
        if disruption_modes:
            params["disruption_modes"] = ",".join(map(str, disruption_modes))
        
        response = self._make_request("/v3/disruptions", params)
        return response.get("disruptions", {})
    
    def get_run_details(self, run_ref: str, route_type: int,
                       expand: Optional[List[str]] = None) -> Dict[str, Any]:
        """
        Get details for a specific run/service.
        
        Args:
            run_ref: Run reference from departures API
            route_type: Route type
            expand: Additional data to include
            
        Returns:
            Run object with details
        """
        params = {}
        if expand:
            params["expand"] = ",".join(expand)
            
        endpoint = f"/v3/runs/{run_ref}/route_type/{route_type}"
        response = self._make_request(endpoint, params)
        return response
    
    def get_pattern(self, run_ref: str, route_type: int,
                   expand: Optional[List[str]] = None,
                   stop_id: Optional[int] = None,
                   datetime_utc: Optional[datetime] = None) -> Dict[str, Any]:
        """
        Get stopping pattern for a run.
        
        Args:
            run_ref: Run reference
            route_type: Route type
            expand: Additional data to include
            stop_id: Get pattern from this stop
            datetime_utc: Get pattern from this time
            
        Returns:
            Stopping pattern with departures
        """
        params = {}
        if expand:
            params["expand"] = ",".join(expand)
        if stop_id is not None:
            params["stop_id"] = stop_id  
        if datetime_utc:
            params["date_utc"] = datetime_utc.strftime("%Y-%m-%dT%H:%M:%SZ")
            
        endpoint = f"/v3/pattern/run/{run_ref}/route_type/{route_type}"
        response = self._make_request(endpoint, params)
        return response


# Transport type constants
class RouteType:
    TRAIN = 0
    TRAM = 1
    BUS = 2
    VLINE_TRAIN = 3
    NIGHT_BUS = 4


# Convenience function to create authenticated client
def create_ptv_client() -> PTVClient:
    """Create PTV API client with environment variables."""
    return PTVClient()