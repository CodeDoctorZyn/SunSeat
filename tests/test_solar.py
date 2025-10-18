import unittest
from datetime import datetime
from zoneinfo import ZoneInfo
from app.solar import get_solar_position, is_sun_visible, get_sun_times


class TestSolar(unittest.TestCase):
    """Test solar position calculations."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.melbourne_tz = ZoneInfo("Australia/Melbourne")
        self.melbourne_lat = -37.8136
        self.melbourne_lon = 144.9631
        
        # Test times
        self.noon_summer = datetime(2024, 1, 15, 12, 0, tzinfo=self.melbourne_tz)  # Summer noon
        self.noon_winter = datetime(2024, 7, 15, 12, 0, tzinfo=self.melbourne_tz)  # Winter noon  
        self.sunrise_approx = datetime(2024, 1, 15, 6, 0, tzinfo=self.melbourne_tz)
        self.sunset_approx = datetime(2024, 1, 15, 20, 0, tzinfo=self.melbourne_tz)
        self.midnight = datetime(2024, 1, 15, 0, 0, tzinfo=self.melbourne_tz)
    
    def test_get_solar_position_noon_summer(self):
        """Test solar position at summer noon."""
        azimuth, altitude = get_solar_position(
            self.melbourne_lat, 
            self.melbourne_lon, 
            self.noon_summer
        )
        
        # At summer noon in Melbourne, sun should be roughly north and high
        self.assertTrue(0 <= azimuth <= 360)
        self.assertTrue(altitude > 50)  # Should be quite high in summer
        
        # In summer, sun should be more northerly (closer to 0° or 360°)
        self.assertTrue(azimuth < 90 or azimuth > 270)
    
    def test_get_solar_position_noon_winter(self):
        """Test solar position at winter noon."""
        azimuth, altitude = get_solar_position(
            self.melbourne_lat,
            self.melbourne_lon, 
            self.noon_winter
        )
        
        # At winter noon, sun should be lower than summer
        self.assertTrue(0 <= azimuth <= 360)
        self.assertTrue(20 < altitude < 50)  # Lower than summer but still visible
    
    def test_get_solar_position_midnight(self):
        """Test solar position at midnight (sun below horizon)."""
        azimuth, altitude = get_solar_position(
            self.melbourne_lat,
            self.melbourne_lon,
            self.midnight
        )
        
        # At midnight, sun should be well below horizon
        self.assertTrue(0 <= azimuth <= 360)
        self.assertTrue(altitude < 0)  # Below horizon
    
    def test_is_sun_visible_high_altitude(self):
        """Test sun visibility for high altitude."""
        self.assertTrue(is_sun_visible(45.0))  # 45° - clearly visible
        self.assertTrue(is_sun_visible(15.0))  # 15° - visible above threshold
        self.assertTrue(is_sun_visible(10.1))  # Just above threshold
    
    def test_is_sun_visible_low_altitude(self):
        """Test sun visibility for low altitude."""
        self.assertFalse(is_sun_visible(9.9))   # Just below threshold
        self.assertFalse(is_sun_visible(5.0))   # Below threshold
        self.assertFalse(is_sun_visible(0.0))   # At horizon
        self.assertFalse(is_sun_visible(-10.0)) # Below horizon
    
    def test_is_sun_visible_custom_threshold(self):
        """Test sun visibility with custom threshold."""
        self.assertTrue(is_sun_visible(15.0, threshold=10.0))   # Above custom threshold
        self.assertFalse(is_sun_visible(5.0, threshold=10.0))   # Below custom threshold
        self.assertTrue(is_sun_visible(25.0, threshold=20.0))   # Above higher threshold
        self.assertFalse(is_sun_visible(15.0, threshold=20.0))  # Below higher threshold
    
    def test_get_sun_times(self):
        """Test sunrise/sunset calculation."""
        sun_times = get_sun_times(
            self.melbourne_lat,
            self.melbourne_lon, 
            self.noon_summer
        )
        
        self.assertIn('sunrise', sun_times)
        self.assertIn('sunset', sun_times)
        
        sunrise = sun_times['sunrise']
        sunset = sun_times['sunset']
        
        # Basic sanity checks
        self.assertIsInstance(sunrise, datetime)
        self.assertIsInstance(sunset, datetime)
        self.assertTrue(sunrise < sunset)  # Sunrise before sunset
        
        # Should be on the same date
        self.assertEqual(sunrise.date(), self.noon_summer.date())
        self.assertEqual(sunset.date(), self.noon_summer.date())
        
        # Rough time checks for Melbourne summer
        self.assertTrue(4 <= sunrise.hour <= 7)   # Sunrise between 4-7 AM
        self.assertTrue(19 <= sunset.hour <= 22)  # Sunset between 7-10 PM
    
    def test_naive_datetime_handling(self):
        """Test that naive datetimes are handled properly."""
        # Create naive datetime
        naive_dt = datetime(2024, 1, 15, 12, 0)  # No timezone
        
        # Should not raise an error and should assume Melbourne timezone
        azimuth, altitude = get_solar_position(
            self.melbourne_lat,
            self.melbourne_lon,
            naive_dt
        )
        
        self.assertTrue(0 <= azimuth <= 360)
        self.assertIsInstance(altitude, float)


if __name__ == '__main__':
    unittest.main()