import unittest
import math
from app.geometry import (
    calculate_bearing, 
    calculate_distance, 
    get_segment_midpoint,
    polyline_to_segments
)


class TestGeometry(unittest.TestCase):
    """Test geometry calculations for route analysis."""
    
    def test_calculate_bearing_north(self):
        """Test bearing calculation for northward travel."""
        # Melbourne Central to slightly north
        bearing = calculate_bearing(-37.8136, 144.9631, -37.8100, 144.9631)
        self.assertAlmostEqual(bearing, 0.0, places=1)  # Should be ~0° (North)
    
    def test_calculate_bearing_east(self):
        """Test bearing calculation for eastward travel."""
        # Melbourne Central to slightly east
        bearing = calculate_bearing(-37.8136, 144.9631, -37.8136, 144.9700)
        self.assertAlmostEqual(bearing, 90.0, places=1)  # Should be ~90° (East)
    
    def test_calculate_bearing_south(self):
        """Test bearing calculation for southward travel."""
        # Melbourne Central to slightly south
        bearing = calculate_bearing(-37.8136, 144.9631, -37.8200, 144.9631)
        self.assertAlmostEqual(bearing, 180.0, places=1)  # Should be ~180° (South)
    
    def test_calculate_bearing_west(self):
        """Test bearing calculation for westward travel.""" 
        # Melbourne Central to slightly west
        bearing = calculate_bearing(-37.8136, 144.9631, -37.8136, 144.9500)
        self.assertAlmostEqual(bearing, 270.0, places=1)  # Should be ~270° (West)
    
    def test_calculate_bearing_same_point(self):
        """Test bearing calculation for same point."""
        bearing = calculate_bearing(-37.8136, 144.9631, -37.8136, 144.9631)
        self.assertEqual(bearing, 0.0)
    
    def test_calculate_distance_zero(self):
        """Test distance calculation for same point."""
        distance = calculate_distance(-37.8136, 144.9631, -37.8136, 144.9631)
        self.assertEqual(distance, 0.0)
    
    def test_calculate_distance_known_points(self):
        """Test distance calculation between known Melbourne points."""
        # Melbourne Central to Richmond (approximately)
        distance = calculate_distance(-37.8136, 144.9631, -37.8225, 144.9731)
        # Should be roughly 1.5-2 km
        self.assertTrue(1.0 < distance < 3.0)
    
    def test_get_segment_midpoint(self):
        """Test midpoint calculation."""
        lat1, lon1 = -37.8136, 144.9631  # Melbourne Central
        lat2, lon2 = -37.8225, 144.9731  # Richmond
        
        mid_lat, mid_lon = get_segment_midpoint(lat1, lon1, lat2, lon2)
        
        # Midpoint should be between the two points
        expected_mid_lat = (lat1 + lat2) / 2
        expected_mid_lon = (lon1 + lon2) / 2
        
        self.assertAlmostEqual(mid_lat, expected_mid_lat, places=6)
        self.assertAlmostEqual(mid_lon, expected_mid_lon, places=6)
    
    def test_polyline_to_segments(self):
        """Test polyline to segments conversion."""
        coordinates = [
            (-37.8136, 144.9631),  # Melbourne Central
            (-37.8225, 144.9731),  # Richmond  
            (-37.8342, 144.9764),  # South Yarra
        ]
        
        segments = polyline_to_segments(coordinates)
        
        self.assertEqual(len(segments), 2)  # 3 points = 2 segments
        
        # Check first segment
        seg1 = segments[0]
        self.assertEqual(seg1['start_lat'], -37.8136)
        self.assertEqual(seg1['start_lon'], 144.9631)
        self.assertEqual(seg1['end_lat'], -37.8225)
        self.assertEqual(seg1['end_lon'], 144.9731)
        self.assertTrue(seg1['distance_km'] > 0)
        self.assertTrue(0 <= seg1['bearing'] < 360)
    
    def test_polyline_to_segments_empty(self):
        """Test empty polyline."""
        segments = polyline_to_segments([])
        self.assertEqual(len(segments), 0)
    
    def test_polyline_to_segments_single_point(self):
        """Test single point polyline."""
        coordinates = [(-37.8136, 144.9631)]
        segments = polyline_to_segments(coordinates)
        self.assertEqual(len(segments), 0)


if __name__ == '__main__':
    unittest.main()