import unittest
from datetime import datetime
from zoneinfo import ZoneInfo
from app.advisor import calculate_segment_advice, generate_trip_advice
from app.models import SeatAdvice, CarriageFacing


class TestAdvisor(unittest.TestCase):
    """Test the core sun exposure advice logic."""
    
    def test_calculate_segment_advice_basic_rules(self):
        """Test the basic LEFT/RIGHT decision rules."""
        # Sun altitude above threshold
        solar_altitude = 45.0
        
        # Test Case 1: Travel North (0°), Sun from East (90°)
        # Relative angle = (90 - 0) % 360 = 90° → RIGHT side
        advice = calculate_segment_advice(
            bearing=0.0,           # North
            solar_azimuth=90.0,    # East  
            solar_altitude=solar_altitude
        )
        self.assertEqual(advice, SeatAdvice.RIGHT)
        
        # Test Case 2: Travel North (0°), Sun from West (270°) 
        # Relative angle = (270 - 0) % 360 = 270° → LEFT side
        advice = calculate_segment_advice(
            bearing=0.0,           # North
            solar_azimuth=270.0,   # West
            solar_altitude=solar_altitude
        )
        self.assertEqual(advice, SeatAdvice.LEFT)
        
        # Test Case 3: Travel East (90°), Sun from South (180°)
        # Relative angle = (180 - 90) % 360 = 90° → RIGHT side  
        advice = calculate_segment_advice(
            bearing=90.0,          # East
            solar_azimuth=180.0,   # South
            solar_altitude=solar_altitude
        )
        self.assertEqual(advice, SeatAdvice.RIGHT)
        
        # Test Case 4: Travel East (90°), Sun from North (0°)
        # Relative angle = (0 - 90) % 360 = 270° → LEFT side
        advice = calculate_segment_advice(
            bearing=90.0,          # East
            solar_azimuth=0.0,     # North
            solar_altitude=solar_altitude
        )
        self.assertEqual(advice, SeatAdvice.LEFT)
    
    def test_calculate_segment_advice_low_sun(self):
        """Test advice when sun is too low (below threshold)."""
        # Sun below threshold altitude
        advice = calculate_segment_advice(
            bearing=0.0,
            solar_azimuth=90.0,
            solar_altitude=5.0  # Below 10° threshold
        )
        self.assertEqual(advice, SeatAdvice.NEITHER)
        
        # Sun at exactly threshold
        advice = calculate_segment_advice(
            bearing=0.0,
            solar_azimuth=90.0,
            solar_altitude=10.0  # At 10° threshold
        )
        self.assertEqual(advice, SeatAdvice.NEITHER)
        
        # Sun just above threshold 
        advice = calculate_segment_advice(
            bearing=0.0,
            solar_azimuth=90.0,
            solar_altitude=10.1  # Just above threshold
        )
        self.assertEqual(advice, SeatAdvice.RIGHT)
    
    def test_calculate_segment_advice_sun_ahead_behind(self):
        """Test advice when sun is directly ahead or behind."""
        solar_altitude = 45.0
        
        # Sun directly ahead (same direction as travel)
        advice = calculate_segment_advice(
            bearing=90.0,          # Travel East
            solar_azimuth=90.0,    # Sun also East
            solar_altitude=solar_altitude
        )
        self.assertEqual(advice, SeatAdvice.NEITHER)
        
        # Sun directly behind (opposite direction) 
        advice = calculate_segment_advice(
            bearing=90.0,          # Travel East
            solar_azimuth=270.0,   # Sun West (opposite)
            solar_altitude=solar_altitude
        )
        self.assertEqual(advice, SeatAdvice.NEITHER)
    
    def test_calculate_segment_advice_carriage_facing_backward(self):
        """Test advice adjustment for backward-facing carriage."""
        solar_altitude = 45.0
        
        # Normal case: Travel North, Sun East → RIGHT
        advice_forward = calculate_segment_advice(
            bearing=0.0,
            solar_azimuth=90.0, 
            solar_altitude=solar_altitude,
            facing=CarriageFacing.FORWARD
        )
        self.assertEqual(advice_forward, SeatAdvice.RIGHT)
        
        # Backward case: Should swap to LEFT
        advice_backward = calculate_segment_advice(
            bearing=0.0,
            solar_azimuth=90.0,
            solar_altitude=solar_altitude,
            facing=CarriageFacing.BACKWARD
        )
        self.assertEqual(advice_backward, SeatAdvice.LEFT)
        
        # Test the opposite swap
        advice_forward_2 = calculate_segment_advice(
            bearing=0.0,
            solar_azimuth=270.0,
            solar_altitude=solar_altitude,
            facing=CarriageFacing.FORWARD
        )
        self.assertEqual(advice_forward_2, SeatAdvice.LEFT)
        
        advice_backward_2 = calculate_segment_advice(
            bearing=0.0, 
            solar_azimuth=270.0,
            solar_altitude=solar_altitude,
            facing=CarriageFacing.BACKWARD
        )
        self.assertEqual(advice_backward_2, SeatAdvice.RIGHT)
        
        # NEITHER should remain NEITHER regardless of facing
        advice_neither = calculate_segment_advice(
            bearing=0.0,
            solar_azimuth=0.0,  # Sun ahead
            solar_altitude=solar_altitude,
            facing=CarriageFacing.BACKWARD
        )
        self.assertEqual(advice_neither, SeatAdvice.NEITHER)
    
    def test_generate_trip_advice_basic(self):
        """Test full trip advice generation."""
        melbourne_tz = ZoneInfo("Australia/Melbourne")
        
        # Simple 2-point route
        coordinates = [
            (-37.8136, 144.9631),  # Melbourne Central
            (-37.8225, 144.9731),  # Richmond
        ]
        
        # Summer midday (high sun)
        start_time = datetime(2024, 1, 15, 12, 0, tzinfo=melbourne_tz)
        
        advice = generate_trip_advice(
            coordinates=coordinates,
            start_time=start_time,
            total_duration_minutes=10.0,
            stop_names=["Melbourne Central", "Richmond"]
        )
        
        # Check basic structure
        self.assertIsInstance(advice.total_distance_km, float)
        self.assertIsInstance(advice.total_duration_minutes, float)
        self.assertTrue(advice.total_distance_km > 0)
        self.assertTrue(advice.total_duration_minutes > 0)
        
        # Should have 1 segment for 2 points
        self.assertEqual(len(advice.segments), 1)
        
        # Percentages should sum to ~100%
        total_percentage = (advice.left_percentage + 
                          advice.right_percentage + 
                          advice.neither_percentage)
        self.assertAlmostEqual(total_percentage, 100.0, places=1)
        
        # Check segment data
        segment = advice.segments[0]
        self.assertEqual(segment.start_stop, "Melbourne Central")
        self.assertEqual(segment.end_stop, "Richmond")
        self.assertIn(segment.advice, [SeatAdvice.LEFT, SeatAdvice.RIGHT, SeatAdvice.NEITHER])
    
    def test_generate_trip_advice_empty_coordinates(self):
        """Test trip advice with empty coordinates."""
        melbourne_tz = ZoneInfo("Australia/Melbourne")
        start_time = datetime(2024, 1, 15, 12, 0, tzinfo=melbourne_tz)
        
        advice = generate_trip_advice(
            coordinates=[],
            start_time=start_time,
            total_duration_minutes=10.0
        )
        
        self.assertEqual(advice.total_distance_km, 0.0)
        self.assertEqual(advice.total_duration_minutes, 0.0)
        self.assertEqual(len(advice.segments), 0)
        self.assertEqual(advice.neither_percentage, 100.0)
    
    def test_generate_trip_advice_night_time(self):
        """Test trip advice during night (low sun altitude)."""
        melbourne_tz = ZoneInfo("Australia/Melbourne")
        
        coordinates = [
            (-37.8136, 144.9631),  # Melbourne Central
            (-37.8225, 144.9731),  # Richmond  
            (-37.8342, 144.9764),  # South Yarra
        ]
        
        # Midnight (sun well below horizon)
        start_time = datetime(2024, 1, 15, 0, 0, tzinfo=melbourne_tz)
        
        advice = generate_trip_advice(
            coordinates=coordinates,
            start_time=start_time,
            total_duration_minutes=20.0
        )
        
        # Should mostly be NEITHER due to low sun
        self.assertTrue(advice.neither_percentage > 80)
        
        # All segments should likely be NEITHER
        for segment in advice.segments:
            # Most should be NEITHER due to low altitude
            self.assertTrue(segment.solar_altitude < 10)


if __name__ == '__main__':
    unittest.main()