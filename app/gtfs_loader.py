"""
GTFS data loader and processor with SQLite storage.
Handles static GTFS feeds with caching and efficient querying.
"""

import sqlite3
import zipfile
import csv
import json
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any
import logging
import requests
import pandas as pd
from datetime import datetime, timedelta
import os
import tempfile
import shutil

logger = logging.getLogger(__name__)

# Global GTFS loader instance
_gtfs_loader = None


class GTFSLoader:
    """
    Load, process and query GTFS static data with SQLite storage.
    
    Handles downloading PTV GTFS feeds, parsing CSV files, and storing
    in SQLite database for efficient querying of routes, stops, trips, etc.
    """
    
    def __init__(self, db_path: Optional[str] = None, gtfs_url: Optional[str] = None):
        """
        Initialize GTFS loader.
        
        Args:
            db_path: Path to SQLite database (defaults to data/gtfs.db)
            gtfs_url: URL to download GTFS zip (defaults to PTV GTFS feed)
        """
        self.data_dir = Path("data")
        self.data_dir.mkdir(exist_ok=True)
        
        self.db_path = db_path or str(self.data_dir / "gtfs.db")
        self.gtfs_url = gtfs_url or os.getenv("GTFS_URL", 
            "https://data.ptv.vic.gov.au/downloads/gtfs.zip")
        
        self.gtfs_zip_path = self.data_dir / "gtfs.zip"
        self.gtfs_extract_dir = self.data_dir / "gtfs_extracted"
        
        # Track when data was last updated
        self.last_update_file = self.data_dir / "last_gtfs_update.txt"
        
    def _get_db_connection(self) -> sqlite3.Connection:
        """Get SQLite database connection."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row  # Enable dict-like access
        return conn
    
    def _should_update_gtfs(self) -> bool:
        """Check if GTFS data should be updated (daily refresh)."""
        if not Path(self.db_path).exists():
            return True
            
        if not self.last_update_file.exists():
            return True
            
        try:
            with open(self.last_update_file, 'r') as f:
                last_update = datetime.fromisoformat(f.read().strip())
            
            # Update if more than 24 hours old
            return datetime.now() - last_update > timedelta(hours=24)
        except (ValueError, IOError):
            return True
    
    def download_gtfs_feed(self, force: bool = False) -> bool:
        """
        Download GTFS feed from PTV.
        
        Args:
            force: Force download even if recent data exists
            
        Returns:
            True if downloaded/updated, False if using cached data
        """
        if not force and not self._should_update_gtfs():
            logger.info("Using cached GTFS data")
            return False
            
        logger.info(f"Downloading GTFS feed from {self.gtfs_url}")
        
        try:
            response = requests.get(self.gtfs_url, timeout=300)
            response.raise_for_status()
            
            with open(self.gtfs_zip_path, 'wb') as f:
                f.write(response.content)
            
            logger.info(f"Downloaded GTFS feed ({len(response.content)} bytes)")
            
            # Mark update time
            with open(self.last_update_file, 'w') as f:
                f.write(datetime.now().isoformat())
            
            return True
            
        except requests.RequestException as e:
            logger.error(f"Failed to download GTFS feed: {e}")
            if not self.gtfs_zip_path.exists():
                raise
            logger.warning("Using existing GTFS file")
            return False
    
    def extract_gtfs_files(self) -> None:
        """Extract GTFS ZIP file."""
        if self.gtfs_extract_dir.exists():
            shutil.rmtree(self.gtfs_extract_dir)
        
        self.gtfs_extract_dir.mkdir()
        
        with zipfile.ZipFile(self.gtfs_zip_path, 'r') as zip_ref:
            zip_ref.extractall(self.gtfs_extract_dir)
        
        logger.info(f"Extracted GTFS files to {self.gtfs_extract_dir}")
    
    def _create_database_schema(self) -> None:
        """Create SQLite database schema for GTFS tables."""
        conn = self._get_db_connection()
        
        # Create tables matching GTFS specification
        tables = {
            "agency": """
                CREATE TABLE IF NOT EXISTS agency (
                    agency_id TEXT PRIMARY KEY,
                    agency_name TEXT NOT NULL,
                    agency_url TEXT,
                    agency_timezone TEXT,
                    agency_lang TEXT,
                    agency_phone TEXT
                )
            """,
            "routes": """
                CREATE TABLE IF NOT EXISTS routes (
                    route_id TEXT PRIMARY KEY,
                    agency_id TEXT,
                    route_short_name TEXT,
                    route_long_name TEXT,
                    route_desc TEXT,
                    route_type INTEGER,
                    route_url TEXT,
                    route_color TEXT,
                    route_text_color TEXT,
                    FOREIGN KEY (agency_id) REFERENCES agency (agency_id)
                )
            """,
            "stops": """
                CREATE TABLE IF NOT EXISTS stops (
                    stop_id TEXT PRIMARY KEY,
                    stop_code TEXT,
                    stop_name TEXT NOT NULL,
                    stop_desc TEXT,
                    stop_lat REAL,
                    stop_lon REAL,
                    zone_id TEXT,
                    stop_url TEXT,
                    location_type INTEGER,
                    parent_station TEXT,
                    wheelchair_boarding INTEGER
                )
            """,
            "trips": """
                CREATE TABLE IF NOT EXISTS trips (
                    route_id TEXT,
                    service_id TEXT,
                    trip_id TEXT PRIMARY KEY,
                    trip_headsign TEXT,
                    trip_short_name TEXT,
                    direction_id INTEGER,
                    block_id TEXT,
                    shape_id TEXT,
                    wheelchair_accessible INTEGER,
                    FOREIGN KEY (route_id) REFERENCES routes (route_id)
                )
            """,
            "stop_times": """
                CREATE TABLE IF NOT EXISTS stop_times (
                    trip_id TEXT,
                    arrival_time TEXT,
                    departure_time TEXT,
                    stop_id TEXT,
                    stop_sequence INTEGER,
                    stop_headsign TEXT,
                    pickup_type INTEGER,
                    drop_off_type INTEGER,
                    shape_dist_traveled REAL,
                    FOREIGN KEY (trip_id) REFERENCES trips (trip_id),
                    FOREIGN KEY (stop_id) REFERENCES stops (stop_id)
                )
            """,
            "shapes": """
                CREATE TABLE IF NOT EXISTS shapes (
                    shape_id TEXT,
                    shape_pt_lat REAL,
                    shape_pt_lon REAL,
                    shape_pt_sequence INTEGER,
                    shape_dist_traveled REAL
                )
            """,
            "calendar": """
                CREATE TABLE IF NOT EXISTS calendar (
                    service_id TEXT PRIMARY KEY,
                    monday INTEGER,
                    tuesday INTEGER,
                    wednesday INTEGER,
                    thursday INTEGER,
                    friday INTEGER,
                    saturday INTEGER,
                    sunday INTEGER,
                    start_date TEXT,
                    end_date TEXT
                )
            """
        }
        
        for table_name, create_sql in tables.items():
            conn.execute(create_sql)
        
        # Create indexes for performance
        indexes = [
            "CREATE INDEX IF NOT EXISTS idx_routes_type ON routes(route_type)",
            "CREATE INDEX IF NOT EXISTS idx_stops_name ON stops(stop_name)",
            "CREATE INDEX IF NOT EXISTS idx_stops_location ON stops(stop_lat, stop_lon)",
            "CREATE INDEX IF NOT EXISTS idx_trips_route ON trips(route_id)",
            "CREATE INDEX IF NOT EXISTS idx_trips_shape ON trips(shape_id)",
            "CREATE INDEX IF NOT EXISTS idx_stop_times_trip ON stop_times(trip_id)",
            "CREATE INDEX IF NOT EXISTS idx_stop_times_stop ON stop_times(stop_id)",
            "CREATE INDEX IF NOT EXISTS idx_shapes_id ON shapes(shape_id, shape_pt_sequence)"
        ]
        
        for index_sql in indexes:
            conn.execute(index_sql)
        
        conn.commit()
        conn.close()
    
    def _load_csv_to_db(self, filename: str, table_name: str) -> None:
        """Load a GTFS CSV file into SQLite table."""
        csv_path = self.gtfs_extract_dir / filename
        if not csv_path.exists():
            logger.warning(f"GTFS file {filename} not found, skipping")
            return
        
        conn = self._get_db_connection()
        
        # Clear existing data
        conn.execute(f"DELETE FROM {table_name}")
        
        with open(csv_path, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            
            # Get column names from CSV
            if not reader.fieldnames:
                logger.warning(f"No columns found in {filename}")
                return
                
            columns = reader.fieldnames
            placeholders = ','.join(['?' for _ in columns])
            
            insert_sql = f"INSERT INTO {table_name} ({','.join(columns)}) VALUES ({placeholders})"
            
            rows = []
            for row in reader:
                # Convert empty strings to None for better SQLite handling
                row_values = [val if val.strip() else None for val in row.values()]
                rows.append(row_values)
                
                # Batch insert for performance
                if len(rows) >= 1000:
                    conn.executemany(insert_sql, rows)
                    rows = []
            
            # Insert remaining rows
            if rows:
                conn.executemany(insert_sql, rows)
        
        conn.commit()
        conn.close()
        
        logger.info(f"Loaded {table_name} from {filename}")
    
    def load_gtfs_to_database(self) -> None:
        """Load all GTFS CSV files into SQLite database."""
        self._create_database_schema()
        
        # Map GTFS files to database tables
        file_table_map = {
            "agency.txt": "agency",
            "routes.txt": "routes", 
            "stops.txt": "stops",
            "trips.txt": "trips",
            "stop_times.txt": "stop_times",
            "shapes.txt": "shapes",
            "calendar.txt": "calendar"
        }
        
        for filename, table_name in file_table_map.items():
            self._load_csv_to_db(filename, table_name)
    
    def update_gtfs_data(self, force: bool = False) -> bool:
        """
        Update GTFS data if needed.
        
        Args:
            force: Force update even if recent
            
        Returns:
            True if data was updated
        """
        if self.download_gtfs_feed(force):
            self.extract_gtfs_files()
            self.load_gtfs_to_database()
            return True
        return False
    
    def search_stops(self, query: str, limit: int = 10) -> List[Dict[str, Any]]:
        """
        Search stops by name.
        
        Args:
            query: Search term
            limit: Maximum results
            
        Returns:
            List of stop dictionaries
        """
        conn = self._get_db_connection()
        
        sql = """
            SELECT stop_id, stop_name, stop_lat, stop_lon, zone_id
            FROM stops 
            WHERE stop_name LIKE ? 
            ORDER BY stop_name
            LIMIT ?
        """
        
        cursor = conn.execute(sql, (f"%{query}%", limit))
        stops = [dict(row) for row in cursor.fetchall()]
        conn.close()
        
        return stops
    
    def get_route_by_id(self, route_id: str) -> Optional[Dict[str, Any]]:
        """Get route details by ID."""
        conn = self._get_db_connection()
        
        cursor = conn.execute(
            "SELECT * FROM routes WHERE route_id = ?", 
            (route_id,)
        )
        route = cursor.fetchone()
        conn.close()
        
        return dict(route) if route else None
    
    def get_routes_by_type(self, route_type: int) -> List[Dict[str, Any]]:
        """Get all routes of specified type."""
        conn = self._get_db_connection()
        
        cursor = conn.execute(
            "SELECT * FROM routes WHERE route_type = ? ORDER BY route_short_name",
            (route_type,)
        )
        routes = [dict(row) for row in cursor.fetchall()]
        conn.close()
        
        return routes
    
    def get_shape_points(self, shape_id: str) -> List[Tuple[float, float]]:
        """
        Get shape coordinates for a given shape ID.
        
        Args:
            shape_id: GTFS shape identifier
            
        Returns:
            List of (lat, lon) coordinate tuples
        """
        conn = self._get_db_connection()
        
        sql = """
            SELECT shape_pt_lat, shape_pt_lon 
            FROM shapes 
            WHERE shape_id = ? 
            ORDER BY shape_pt_sequence
        """
        
        cursor = conn.execute(sql, (shape_id,))
        points = [(row[0], row[1]) for row in cursor.fetchall()]
        conn.close()
        
        return points
    
    def get_trip_shape_id(self, trip_id: str) -> Optional[str]:
        """Get shape ID for a trip."""
        conn = self._get_db_connection()
        
        cursor = conn.execute(
            "SELECT shape_id FROM trips WHERE trip_id = ?",
            (trip_id,)
        )
        result = cursor.fetchone()
        conn.close()
        
        return result[0] if result else None
    
    def get_stops_for_trip(self, trip_id: str) -> List[Dict[str, Any]]:
        """Get all stops for a trip in order."""
        conn = self._get_db_connection()
        
        sql = """
            SELECT s.stop_id, s.stop_name, s.stop_lat, s.stop_lon,
                   st.stop_sequence, st.arrival_time, st.departure_time
            FROM stop_times st
            JOIN stops s ON st.stop_id = s.stop_id
            WHERE st.trip_id = ?
            ORDER BY st.stop_sequence
        """
        
        cursor = conn.execute(sql, (trip_id,))
        stops = [dict(row) for row in cursor.fetchall()]
        conn.close()
        
        return stops


def get_gtfs_loader() -> GTFSLoader:
    """Get global GTFS loader instance."""
    global _gtfs_loader
    if _gtfs_loader is None:
        _gtfs_loader = GTFSLoader()
    return _gtfs_loader


def load_sample_geojson_route(route_name: str = "alamein") -> Dict:
    """Load a sample route as GeoJSON for map display."""
    loader = get_gtfs_loader()
    
    # Try to get real GTFS shape data first
    try:
        # This would need actual route lookup in production
        shape_coords = []
        
        if not shape_coords:
            # Fallback to sample data
            sample_shapes = {
                "alamein": [
                    (-37.8183, 144.9671),  # Flinders Street
                    (-37.8199, 144.9988),  # Richmond
                    (-37.8268, 145.0826),  # Camberwell
                    (-37.8443, 145.0915)   # Alamein
                ],
                "belgrave": [
                    (-37.8183, 144.9671),  # Flinders Street
                    (-37.8199, 144.9988),  # Richmond
                    (-37.8473, 145.1126),  # Box Hill
                    (-37.9104, 145.3528)   # Belgrave
                ]
            }
            shape_coords = sample_shapes.get(route_name.lower(), [])
    
    except Exception as e:
        logger.error(f"Error loading route shape: {e}")
        shape_coords = []
    
    if not shape_coords:
        return {"type": "FeatureCollection", "features": []}
    
    # Convert to GeoJSON LineString
    geojson = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": {
                    "type": "LineString",
                    "coordinates": [[lng, lat] for lat, lng in shape_coords]
                },
                "properties": {
                    "name": route_name.title(),
                    "color": "#00B8E6"
                }
            }
        ]
    }
    
    return geojson