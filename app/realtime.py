"""
GTFS-Realtime feed processor for PTV real-time data.
Handles trip updates, vehicle positions, and service alerts.
"""

import requests
import logging
from typing import Dict, List, Optional, Any, Tuple
from datetime import datetime, timezone
import os
from dataclasses import dataclass
from enum import Enum
import json

# For protobuf handling - would need gtfs-realtime-bindings package
try:
    from google.transit import gtfs_realtime_pb2
    PROTOBUF_AVAILABLE = True
except ImportError:
    PROTOBUF_AVAILABLE = False
    logging.warning("GTFS-Realtime protobuf bindings not available. Install gtfs-realtime-bindings package.")

logger = logging.getLogger(__name__)


class ScheduleRelationship(Enum):
    """GTFS-Realtime schedule relationship types."""
    SCHEDULED = 0
    ADDED = 1
    UNSCHEDULED = 2
    CANCELED = 3


class VehicleStopStatus(Enum):
    """Vehicle position relative to stop."""
    INCOMING_AT = 0
    STOPPED_AT = 1
    IN_TRANSIT_TO = 2


@dataclass
class TripUpdate:
    """Represents a trip update from GTFS-Realtime feed."""
    trip_id: str
    route_id: Optional[str]
    start_time: Optional[str]
    start_date: Optional[str]
    schedule_relationship: ScheduleRelationship
    stop_time_updates: List[Dict[str, Any]]
    vehicle_id: Optional[str] = None
    timestamp: Optional[datetime] = None


@dataclass
class VehiclePosition:
    """Represents vehicle position from GTFS-Realtime feed."""
    vehicle_id: str
    trip_id: Optional[str]
    route_id: Optional[str]
    latitude: Optional[float]
    longitude: Optional[float]
    bearing: Optional[float]
    speed: Optional[float]
    timestamp: Optional[datetime]
    stop_id: Optional[str] = None
    stop_status: Optional[VehicleStopStatus] = None


@dataclass
class ServiceAlert:
    """Represents service alert from GTFS-Realtime feed."""
    alert_id: str
    header_text: str
    description_text: str
    url: Optional[str]
    affected_routes: List[str]
    affected_stops: List[str]
    cause: Optional[str] = None
    effect: Optional[str] = None
    severity: Optional[str] = None


class GTFSRealtimeClient:
    """
    Client for consuming PTV GTFS-Realtime feeds.
    
    Processes protobuf feeds for trip updates, vehicle positions,
    and service alerts with caching support.
    """
    
    def __init__(self, 
                 trip_updates_url: Optional[str] = None,
                 vehicle_positions_url: Optional[str] = None,
                 service_alerts_url: Optional[str] = None):
        """
        Initialize GTFS-Realtime client.
        
        Args:
            trip_updates_url: URL for trip updates feed
            vehicle_positions_url: URL for vehicle positions feed  
            service_alerts_url: URL for service alerts feed
        """
        # PTV GTFS-Realtime feed URLs (these would need to be actual PTV URLs)
        self.trip_updates_url = trip_updates_url or os.getenv(
            "PTV_GTFS_RT_TRIP_UPDATES", 
            "https://data.ptv.vic.gov.au/downloads/gtfs-rt/trip-updates"
        )
        
        self.vehicle_positions_url = vehicle_positions_url or os.getenv(
            "PTV_GTFS_RT_VEHICLE_POSITIONS",
            "https://data.ptv.vic.gov.au/downloads/gtfs-rt/vehicle-positions" 
        )
        
        self.service_alerts_url = service_alerts_url or os.getenv(
            "PTV_GTFS_RT_SERVICE_ALERTS",
            "https://data.ptv.vic.gov.au/downloads/gtfs-rt/service-alerts"
        )
        
        self._cached_trip_updates: Dict[str, TripUpdate] = {}
        self._cached_vehicle_positions: Dict[str, VehiclePosition] = {}
        self._cached_alerts: Dict[str, ServiceAlert] = {}
        self._cache_timestamp: Optional[datetime] = None
        
    def _fetch_feed(self, url: str) -> Optional[bytes]:
        """
        Fetch protobuf feed from URL.
        
        Args:
            url: Feed URL
            
        Returns:
            Raw protobuf data or None if failed
        """
        try:
            response = requests.get(url, timeout=30)
            response.raise_for_status()
            return response.content
        except requests.RequestException as e:
            logger.error(f"Failed to fetch GTFS-RT feed from {url}: {e}")
            return None
    
    def _parse_trip_updates(self, feed_data: bytes) -> List[TripUpdate]:
        """
        Parse trip updates from protobuf feed.
        
        Args:
            feed_data: Raw protobuf data
            
        Returns:
            List of trip updates
        """
        if not PROTOBUF_AVAILABLE:
            logger.warning("Protobuf not available, returning empty trip updates")
            return []
        
        try:
            feed = gtfs_realtime_pb2.FeedMessage()
            feed.ParseFromString(feed_data)
            
            trip_updates = []
            
            for entity in feed.entity:
                if entity.HasField('trip_update'):
                    tu = entity.trip_update
                    trip = tu.trip
                    
                    # Parse stop time updates
                    stop_updates = []
                    for stu in tu.stop_time_update:
                        stop_update = {
                            'stop_id': stu.stop_id,
                            'stop_sequence': stu.stop_sequence,
                        }
                        
                        if stu.HasField('arrival'):
                            stop_update['arrival_delay'] = stu.arrival.delay
                            stop_update['arrival_time'] = stu.arrival.time
                        
                        if stu.HasField('departure'):
                            stop_update['departure_delay'] = stu.departure.delay  
                            stop_update['departure_time'] = stu.departure.time
                        
                        stop_updates.append(stop_update)
                    
                    # Create TripUpdate object
                    trip_update = TripUpdate(
                        trip_id=trip.trip_id,
                        route_id=trip.route_id if trip.HasField('route_id') else None,
                        start_time=trip.start_time if trip.HasField('start_time') else None,
                        start_date=trip.start_date if trip.HasField('start_date') else None,
                        schedule_relationship=ScheduleRelationship(trip.schedule_relationship),
                        stop_time_updates=stop_updates,
                        vehicle_id=tu.vehicle.id if tu.HasField('vehicle') else None,
                        timestamp=datetime.fromtimestamp(tu.timestamp, tz=timezone.utc) if tu.HasField('timestamp') else None
                    )
                    
                    trip_updates.append(trip_update)
            
            return trip_updates
            
        except Exception as e:
            logger.error(f"Failed to parse trip updates: {e}")
            return []
    
    def _parse_vehicle_positions(self, feed_data: bytes) -> List[VehiclePosition]:
        """
        Parse vehicle positions from protobuf feed.
        
        Args:
            feed_data: Raw protobuf data
            
        Returns:
            List of vehicle positions
        """
        if not PROTOBUF_AVAILABLE:
            logger.warning("Protobuf not available, returning empty vehicle positions")
            return []
        
        try:
            feed = gtfs_realtime_pb2.FeedMessage()
            feed.ParseFromString(feed_data)
            
            positions = []
            
            for entity in feed.entity:
                if entity.HasField('vehicle'):
                    vp = entity.vehicle
                    
                    position = VehiclePosition(
                        vehicle_id=vp.vehicle.id,
                        trip_id=vp.trip.trip_id if vp.HasField('trip') else None,
                        route_id=vp.trip.route_id if vp.HasField('trip') and vp.trip.HasField('route_id') else None,
                        latitude=vp.position.latitude if vp.HasField('position') else None,
                        longitude=vp.position.longitude if vp.HasField('position') else None,
                        bearing=vp.position.bearing if vp.HasField('position') and vp.position.HasField('bearing') else None,
                        speed=vp.position.speed if vp.HasField('position') and vp.position.HasField('speed') else None,
                        timestamp=datetime.fromtimestamp(vp.timestamp, tz=timezone.utc) if vp.HasField('timestamp') else None,
                        stop_id=vp.stop_id if vp.HasField('stop_id') else None,
                        stop_status=VehicleStopStatus(vp.current_status) if vp.HasField('current_status') else None
                    )
                    
                    positions.append(position)
            
            return positions
            
        except Exception as e:
            logger.error(f"Failed to parse vehicle positions: {e}")
            return []
    
    def _parse_service_alerts(self, feed_data: bytes) -> List[ServiceAlert]:
        """
        Parse service alerts from protobuf feed.
        
        Args:
            feed_data: Raw protobuf data
            
        Returns:
            List of service alerts
        """
        if not PROTOBUF_AVAILABLE:
            logger.warning("Protobuf not available, returning empty service alerts")
            return []
        
        try:
            feed = gtfs_realtime_pb2.FeedMessage()
            feed.ParseFromString(feed_data)
            
            alerts = []
            
            for entity in feed.entity:
                if entity.HasField('alert'):
                    alert = entity.alert
                    
                    # Extract affected routes and stops
                    affected_routes = []
                    affected_stops = []
                    
                    for selector in alert.informed_entity:
                        if selector.HasField('route_id'):
                            affected_routes.append(selector.route_id)
                        if selector.HasField('stop_id'):
                            affected_stops.append(selector.stop_id)
                    
                    # Get text content (prefer English)
                    header_text = ""
                    description_text = ""
                    url = None
                    
                    if alert.HasField('header_text'):
                        for translation in alert.header_text.translation:
                            if translation.language == 'en' or not header_text:
                                header_text = translation.text
                    
                    if alert.HasField('description_text'):
                        for translation in alert.description_text.translation:
                            if translation.language == 'en' or not description_text:
                                description_text = translation.text
                    
                    if alert.HasField('url'):
                        for translation in alert.url.translation:
                            if translation.language == 'en' or not url:
                                url = translation.text
                    
                    service_alert = ServiceAlert(
                        alert_id=entity.id,
                        header_text=header_text,
                        description_text=description_text,
                        url=url,
                        affected_routes=affected_routes,
                        affected_stops=affected_stops,
                        cause=str(alert.cause) if alert.HasField('cause') else None,
                        effect=str(alert.effect) if alert.HasField('effect') else None,
                        severity=str(alert.severity_level) if alert.HasField('severity_level') else None
                    )
                    
                    alerts.append(service_alert)
            
            return alerts
            
        except Exception as e:
            logger.error(f"Failed to parse service alerts: {e}")
            return []
    
    def update_trip_updates(self, force: bool = False) -> bool:
        """
        Fetch and update trip updates.
        
        Args:
            force: Force update even if recently cached
            
        Returns:
            True if updated successfully
        """
        # Check cache age (update every 30 seconds)
        if not force and self._cache_timestamp:
            age = datetime.now(timezone.utc) - self._cache_timestamp
            if age.total_seconds() < 30:
                return False
        
        feed_data = self._fetch_feed(self.trip_updates_url)
        if not feed_data:
            return False
        
        trip_updates = self._parse_trip_updates(feed_data)
        
        # Update cache
        self._cached_trip_updates.clear()
        for update in trip_updates:
            self._cached_trip_updates[update.trip_id] = update
        
        self._cache_timestamp = datetime.now(timezone.utc)
        logger.info(f"Updated {len(trip_updates)} trip updates")
        return True
    
    def update_vehicle_positions(self, force: bool = False) -> bool:
        """
        Fetch and update vehicle positions.
        
        Args:
            force: Force update even if recently cached
            
        Returns:
            True if updated successfully
        """
        feed_data = self._fetch_feed(self.vehicle_positions_url)
        if not feed_data:
            return False
        
        positions = self._parse_vehicle_positions(feed_data)
        
        # Update cache
        self._cached_vehicle_positions.clear()
        for position in positions:
            self._cached_vehicle_positions[position.vehicle_id] = position
        
        logger.info(f"Updated {len(positions)} vehicle positions")
        return True
    
    def update_service_alerts(self, force: bool = False) -> bool:
        """
        Fetch and update service alerts.
        
        Args:
            force: Force update even if recently cached
            
        Returns:
            True if updated successfully
        """
        feed_data = self._fetch_feed(self.service_alerts_url)
        if not feed_data:
            return False
        
        alerts = self._parse_service_alerts(feed_data)
        
        # Update cache
        self._cached_alerts.clear()
        for alert in alerts:
            self._cached_alerts[alert.alert_id] = alert
        
        logger.info(f"Updated {len(alerts)} service alerts")
        return True
    
    def get_trip_update(self, trip_id: str) -> Optional[TripUpdate]:
        """
        Get trip update for specific trip.
        
        Args:
            trip_id: GTFS trip ID
            
        Returns:
            TripUpdate object or None
        """
        self.update_trip_updates()  # Auto-update if needed
        return self._cached_trip_updates.get(trip_id)
    
    def get_vehicle_position(self, vehicle_id: str) -> Optional[VehiclePosition]:
        """
        Get vehicle position for specific vehicle.
        
        Args:
            vehicle_id: Vehicle identifier
            
        Returns:
            VehiclePosition object or None
        """
        self.update_vehicle_positions()  # Auto-update if needed
        return self._cached_vehicle_positions.get(vehicle_id)
    
    def get_route_alerts(self, route_id: str) -> List[ServiceAlert]:
        """
        Get service alerts affecting a specific route.
        
        Args:
            route_id: GTFS route ID
            
        Returns:
            List of ServiceAlert objects
        """
        self.update_service_alerts()  # Auto-update if needed
        
        return [alert for alert in self._cached_alerts.values() 
                if route_id in alert.affected_routes]
    
    def get_stop_alerts(self, stop_id: str) -> List[ServiceAlert]:
        """
        Get service alerts affecting a specific stop.
        
        Args:
            stop_id: GTFS stop ID
            
        Returns:
            List of ServiceAlert objects
        """
        self.update_service_alerts()  # Auto-update if needed
        
        return [alert for alert in self._cached_alerts.values() 
                if stop_id in alert.affected_stops]
    
    def get_all_trip_updates(self) -> List[TripUpdate]:
        """Get all cached trip updates."""
        self.update_trip_updates()
        return list(self._cached_trip_updates.values())
    
    def get_all_vehicle_positions(self) -> List[VehiclePosition]:
        """Get all cached vehicle positions.""" 
        self.update_vehicle_positions()
        return list(self._cached_vehicle_positions.values())
    
    def get_all_service_alerts(self) -> List[ServiceAlert]:
        """Get all cached service alerts."""
        self.update_service_alerts()
        return list(self._cached_alerts.values())


# Global realtime client instance
_realtime_client: Optional[GTFSRealtimeClient] = None


def get_realtime_client() -> GTFSRealtimeClient:
    """Get global GTFS-Realtime client instance."""
    global _realtime_client
    if _realtime_client is None:
        _realtime_client = GTFSRealtimeClient()
    return _realtime_client


# Convenience functions for common operations
def get_trip_delay(trip_id: str, stop_id: str) -> Optional[int]:
    """
    Get delay in seconds for trip at specific stop.
    
    Args:
        trip_id: GTFS trip ID
        stop_id: GTFS stop ID
        
    Returns:
        Delay in seconds (positive = late, negative = early) or None
    """
    client = get_realtime_client()
    trip_update = client.get_trip_update(trip_id)
    
    if not trip_update:
        return None
    
    # Find stop time update for this stop
    for stu in trip_update.stop_time_updates:
        if stu.get('stop_id') == stop_id:
            return stu.get('departure_delay', stu.get('arrival_delay'))
    
    return None


def get_vehicle_location(trip_id: str) -> Optional[Tuple[float, float, Optional[float]]]:
    """
    Get current vehicle location and bearing for trip.
    
    Args:
        trip_id: GTFS trip ID
        
    Returns:
        Tuple of (latitude, longitude, bearing) or None
    """
    client = get_realtime_client()
    
    # Find vehicle by trip_id
    for vehicle in client.get_all_vehicle_positions():
        if vehicle.trip_id == trip_id:
            if vehicle.latitude is not None and vehicle.longitude is not None:
                return (vehicle.latitude, vehicle.longitude, vehicle.bearing)
    
    return None