import os
import pandas as pd
from typing import List, Tuple, Optional, Dict
from pathlib import Path
import json
from functools import lru_cache


class GTFSLoader:
    """Load and query GTFS static feed data."""
    
    def __init__(self, gtfs_dir: str):
        """Initialize with GTFS directory path."""
        self.gtfs_dir = Path(gtfs_dir)
        self._routes = None
        self._stops = None
        self._trips = None
        self._stop_times = None
        self._shapes = None
        # Minimal built-in station coordinates for fallback when GTFS is missing
        self._station_coords = {
            # CBD
            'melbourne central': (-37.8100, 144.9620),
            'flinders street': (-37.8183, 144.9671),
            'parliament': (-37.8123, 144.9730),
            'flagstaff': (-37.8110, 144.9550),
            'richmond': (-37.8240, 144.9980),
            'south yarra': (-37.8380, 144.9920),
            'clayton': (-37.9244, 145.1218),
            'craigieburn': (-37.6000, 144.9460),
            'caulfield': (-37.8770, 145.0430),
            'dandenong': (-38.0022, 145.1989)
        }
    
    @property
    def routes(self) -> pd.DataFrame:
        """Load routes.txt lazily."""
        if self._routes is None:
            routes_file = self.gtfs_dir / "routes.txt"
            if routes_file.exists():
                self._routes = pd.read_csv(routes_file)
            else:
                self._routes = pd.DataFrame(columns=['route_id', 'route_short_name', 'route_long_name'])
        return self._routes
    
    @property
    def stops(self) -> pd.DataFrame:
        """Load stops.txt lazily."""
        if self._stops is None:
            stops_file = self.gtfs_dir / "stops.txt"
            if stops_file.exists():
                self._stops = pd.read_csv(stops_file)
            else:
                self._stops = pd.DataFrame(columns=['stop_id', 'stop_name', 'stop_lat', 'stop_lon'])
        return self._stops
    
    @property
    def trips(self) -> pd.DataFrame:
        """Load trips.txt lazily."""
        if self._trips is None:
            trips_file = self.gtfs_dir / "trips.txt"
            if trips_file.exists():
                self._trips = pd.read_csv(trips_file)
            else:
                self._trips = pd.DataFrame(columns=['route_id', 'service_id', 'trip_id', 'shape_id'])
        return self._trips
    
    @property
    def stop_times(self) -> pd.DataFrame:
        """Load stop_times.txt lazily."""
        if self._stop_times is None:
            stop_times_file = self.gtfs_dir / "stop_times.txt"
            if stop_times_file.exists():
                self._stop_times = pd.read_csv(stop_times_file)
            else:
                self._stop_times = pd.DataFrame(columns=['trip_id', 'stop_id', 'stop_sequence', 'arrival_time'])
        return self._stop_times
    
    @property
    def shapes(self) -> pd.DataFrame:
        """Load shapes.txt lazily."""
        if self._shapes is None:
            shapes_file = self.gtfs_dir / "shapes.txt"
            if shapes_file.exists():
                self._shapes = pd.read_csv(shapes_file)
            else:
                self._shapes = pd.DataFrame(columns=['shape_id', 'shape_pt_lat', 'shape_pt_lon', 'shape_pt_sequence'])
        return self._shapes
    
    def find_routes(self, line_name: str) -> List[Dict]:
        """Find routes matching a line name."""
        routes_df = self.routes
        if routes_df.empty:
            return []
        
        # Search in both short and long names (case insensitive)
        mask = (routes_df['route_short_name'].str.contains(line_name, case=False, na=False) |
                routes_df['route_long_name'].str.contains(line_name, case=False, na=False))
        
        matching_routes = routes_df[mask]
        return matching_routes.to_dict('records')
    
    def find_stops(self, stop_name: str) -> List[Dict]:
        """Find stops matching a name.""" 
        stops_df = self.stops
        if stops_df.empty:
            return []
        
        # Search stop names (case insensitive)
        mask = stops_df['stop_name'].str.contains(stop_name, case=False, na=False)
        matching_stops = stops_df[mask]
        return matching_stops.to_dict('records')
    
    def get_trip_for_route(self, route_id: str, departure_time: str = None) -> Optional[Dict]:
        """Get a trip for the given route, optionally filtered by departure time."""
        trips_df = self.trips
        if trips_df.empty:
            return None
        
        # Get trips for this route
        route_trips = trips_df[trips_df['route_id'] == route_id]
        if route_trips.empty:
            return None
        
        # For simplicity, just return the first trip
        # In a real implementation, you'd filter by service_id, departure time, etc.
        return route_trips.iloc[0].to_dict()
    
    def get_trip_shape(self, trip_id: str) -> List[Tuple[float, float]]:
        """Get the shape coordinates for a trip."""
        trips_df = self.trips
        shapes_df = self.shapes
        
        if trips_df.empty or shapes_df.empty:
            return []
        
        # Find the trip
        trip_mask = trips_df['trip_id'] == trip_id
        if not trip_mask.any():
            return []
        
        trip = trips_df[trip_mask].iloc[0]
        shape_id = trip.get('shape_id')
        
        if pd.isna(shape_id):
            return []
        
        # Get shape points
        shape_points = shapes_df[shapes_df['shape_id'] == shape_id].sort_values('shape_pt_sequence')
        
        if shape_points.empty:
            return []
        
        coordinates = [(row['shape_pt_lat'], row['shape_pt_lon']) for _, row in shape_points.iterrows()]
        return coordinates
    
    def get_trip_stops(self, trip_id: str) -> List[Dict]:
        """Get the stops for a trip in sequence."""
        stop_times_df = self.stop_times
        stops_df = self.stops
        
        if stop_times_df.empty or stops_df.empty:
            return []
        
        # Get stop times for this trip
        trip_stops = stop_times_df[stop_times_df['trip_id'] == trip_id].sort_values('stop_sequence')
        
        if trip_stops.empty:
            return []
        
        # Join with stops to get coordinates
        trip_stops = trip_stops.merge(stops_df, on='stop_id', how='left')
        
        return trip_stops.to_dict('records')
    
    def get_fallback_route(self, origin: str, destination: str) -> List[Tuple[float, float]]:
        """
        Create a fallback route between origin and destination stops.
        Returns straight line coordinates if stops are found.
        """
        # Try GTFS lookup first
        origin_stops = self.find_stops(origin)
        dest_stops = self.find_stops(destination)

        if origin_stops and dest_stops:
            origin_stop = origin_stops[0]
            dest_stop = dest_stops[0]
            return [
                (origin_stop['stop_lat'], origin_stop['stop_lon']),
                (dest_stop['stop_lat'], dest_stop['stop_lon'])
            ]

        # Then try built-in coordinates by name
        o_key = str(origin).strip().lower()
        d_key = str(destination).strip().lower()
        if o_key in self._station_coords and d_key in self._station_coords:
            o_lat, o_lon = self._station_coords[o_key]
            d_lat, d_lon = self._station_coords[d_key]
            return [(o_lat, o_lon), (d_lat, d_lon)]

        # Final fallback: simple CBD sample
        return [
            (-37.8136, 144.9631),  # Melbourne Central
            (-37.8183, 144.9671),  # Parliament
        ]

    def get_polyline_for_route_between_stops(self, line_name: str, origin: str, destination: str) -> List[Tuple[float, float]]:
        """
        Build an approximate polyline for a route by chaining stop coordinates between
        origin and destination on the first matching trip for the given line/route.
        Falls back to straight line between two stops if trip/stop sequences are unavailable.
        """
        try:
            routes = self.find_routes(line_name)
            if not routes:
                return self.get_fallback_route(origin, destination)

            route_id = routes[0].get('route_id')
            if route_id is None:
                return self.get_fallback_route(origin, destination)

            trip = self.get_trip_for_route(route_id)
            if not trip:
                return self.get_fallback_route(origin, destination)

            trip_id = trip.get('trip_id')
            trip_stops = self.get_trip_stops(trip_id)
            if not trip_stops:
                return self.get_fallback_route(origin, destination)

            # Find indices for origin/destination by fuzzy name match
            def _norm(s: str) -> str:
                return str(s or '').strip().lower()

            o = _norm(origin)
            d = _norm(destination)

            o_idx = None
            d_idx = None
            for i, st in enumerate(trip_stops):
                name = _norm(st.get('stop_name'))
                if o_idx is None and (o in name):
                    o_idx = i
                if d in name:
                    d_idx = i

            if o_idx is None or d_idx is None:
                return self.get_fallback_route(origin, destination)

            if o_idx > d_idx:
                # If the trip is in reverse relative to requested direction, swap
                o_idx, d_idx = d_idx, o_idx

            sub = trip_stops[o_idx:d_idx+1]
            coords: List[Tuple[float, float]] = []
            for st in sub:
                lat = st.get('stop_lat') or st.get('stop_latitude')
                lon = st.get('stop_lon') or st.get('stop_longitude')
                if lat is not None and lon is not None:
                    coords.append((float(lat), float(lon)))

            if len(coords) >= 2:
                return coords

            return self.get_fallback_route(origin, destination)
        except Exception:
            return self.get_fallback_route(origin, destination)


@lru_cache(maxsize=1)
def get_gtfs_loader() -> GTFSLoader:
    """Get cached GTFS loader instance."""
    gtfs_dir = os.getenv("GTFS_DIR", "/Users/zaynsmacantosh/Desktop/sundirect/data/gtfs_sample")
    return GTFSLoader(gtfs_dir)


def load_sample_geojson_route() -> List[Tuple[float, float]]:
    """
    Load a sample GeoJSON route for testing purposes.
    Returns Melbourne train line coordinates if available.
    """
    # Sample Melbourne train route (approximation of Cranbourne line)
    sample_coordinates = [
        (-37.8136, 144.9631),  # Melbourne Central
        (-37.8183, 144.9671),  # Parliament  
        (-37.8225, 144.9731),  # Richmond
        (-37.8342, 144.9764),  # South Yarra
        (-37.8415, 144.9803),  # Toorak
        (-37.8501, 144.9876),  # Armadale
        (-37.8612, 145.0234),  # Oakleigh  
        (-37.8756, 145.0876),  # Dandenong
        (-37.9123, 145.1234),  # Cranbourne
    ]
    
    return sample_coordinates