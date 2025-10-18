# ☀️ SunSeat - Train Sun Exposure Advisor

A minimal, production-lean web app that tells metro/train passengers which side of the train the sun will hit during their trip, based on route geometry, time, and solar position.

![FastAPI](https://img.shields.io/badge/FastAPI-005571?style=for-the-badge&logo=fastapi)
![Python](https://img.shields.io/badge/python-3.11+-blue.svg)
![HTMX](https://img.shields.io/badge/HTMX-36C?style=for-the-badge&logo=htmx)
![Tailwind](https://img.shields.io/badge/Tailwind_CSS-38B2AC?style=for-the-badge&logo=tailwind-css)

## 🚂 What It Does

Input your journey details:
- Origin and destination stations
- Line/service name  
- Date and departure time
- Carriage facing direction (optional)

Get personalized advice:
- **LEFT/RIGHT/NEITHER** recommendations per route segment
- Visual map with color-coded sun exposure
- Summary like *"Sit on LEFT for 70% of the ride"*
- Segment-by-segment breakdown with solar data

## 🎯 Core Algorithm

1. **Route Analysis**: Extract trip geometry from GTFS shapes or fall back to stop-to-stop bearings
2. **Solar Calculation**: Compute sun azimuth and altitude at each segment's midpoint time/location
3. **Exposure Logic**: 
   - If sun altitude < 10°: **NEITHER** (too low)
   - Calculate relative angle Δ = (solar_azimuth - travel_bearing) mod 360°
   - If 0° < Δ < 180°: **RIGHT** side of travel direction
   - If 180° ≤ Δ < 360°: **LEFT** side of travel direction
   - Adjust for backward-facing carriages (swap LEFT↔RIGHT)

## 🏗️ Tech Stack

- **Backend**: FastAPI + Uvicorn, Python 3.11+
- **Frontend**: HTMX + Tailwind CSS (CDN) + Leaflet maps
- **Data**: GTFS static feeds, Astral (solar calculations), Shapely (geometry)
- **Caching**: FastAPI-Cache2 with Redis fallback
- **Deployment**: Docker with multi-stage build

## 🚀 Quick Start

### Prerequisites

- Python 3.11+
- Docker (optional)
- GTFS data for your transit system (see [Getting GTFS Data](#-getting-gtfs-data))

### Local Development

```bash
# Clone and setup
git clone <repository-url>
cd sundirect

# Install dependencies  
make install
# or: pip install -r requirements.txt

# Run development server with hot reload
make dev
# or: uvicorn app.main:app --reload

# Open browser
open http://localhost:8000
```

### Docker

```bash
# Build image
make build

# Run container
make docker-run

# Development with volume mounts
make docker-dev
```

## 📊 Getting GTFS Data

### Melbourne (PTV)

1. Visit [Victoria Open Data](https://www.data.vic.gov.au/)
2. Search for "GTFS" or "Public Transport Timetables"  
3. Download the latest GTFS static feed
4. Extract to `data/gtfs_sample/`

### Other Cities

- **OpenMobilityData**: https://transitfeeds.com/
- **TransitLand**: https://www.transit.land/
- Search for your city's transit authority website

### Required Files

```
data/gtfs_sample/
├── routes.txt      # Route definitions
├── stops.txt       # Station coordinates  
├── trips.txt       # Trip instances
├── stop_times.txt  # Timetables
└── shapes.txt      # Route geometry (recommended)
```

## 🧪 Testing

```bash
# Run unit tests
make test

# Run with coverage
make test-coverage

# Test core algorithms
python -m pytest tests/test_geometry.py -v
python -m pytest tests/test_advisor.py::TestAdvisor::test_calculate_segment_advice_basic_rules -v
```

### Key Test Cases

The advisor logic is tested with specific scenarios:

```python
# Travel North (0°), Sun from East (90°) → RIGHT side
calculate_segment_advice(bearing=0.0, solar_azimuth=90.0, solar_altitude=45.0)
# Returns: SeatAdvice.RIGHT

# Travel North (0°), Sun from West (270°) → LEFT side  
calculate_segment_advice(bearing=0.0, solar_azimuth=270.0, solar_altitude=45.0)
# Returns: SeatAdvice.LEFT
```

## 🗺️ API Endpoints

 - `GET /stops/options` - Datalist autocomplete options (PTV→GTFS fallback)

## ⚙️ Configuration

 
# Optional: Online sources via OpenStreetMap Overpass
# Enable OSM fallback for station lookups and line geometry when PTV/GTFS are unavailable
OSM_OVERPASS_ENABLED=true
# Override Overpass endpoint if needed (default: overpass-api.de)
OSM_OVERPASS_URL=https://overpass-api.de/api/interpreter
# TTL (seconds) for in-memory OSM cache
OSM_CACHE_TTL=1800
### Environment Variables

 - **Fallback**: Sample Melbourne route if no GTFS data
     - If `OSM_OVERPASS_ENABLED=true`, tries OSM route geometry before sample fallback
# Server
PORT=8000
HOST=0.0.0.0

# Data & Timezone
 3. **OSM Overpass** (optional): Railway route geometry by line name, cut between your stations
 4. **Fallback**: Sample coordinates for demo purposes
TIMEZONE=Australia/Melbourne

 - **Autocomplete**: Datalist + HTMX station suggestions via `/stops/options`

- **Timezone**: Australia/Melbourne
- **Sun altitude threshold**: 10° (configurable in code)
- **Cache TTL**: Configurable via FastAPI-Cache2
- **Fallback**: Sample Melbourne route if no GTFS data

## 🎨 Frontend Features

- **Responsive Design**: Works on mobile and desktop
- **Real-time Updates**: HTMX for smooth interactions
- **Interactive Maps**: Leaflet with segment color-coding
- **Visual Feedback**: Loading states and error handling
- **Accessibility**: Semantic HTML and proper contrast

## 📈 Production Deployment

### Docker

```dockerfile
# Multi-stage build for minimal image size
# Non-root user for security
# Health checks included
```

### Environment Setup

```bash
# Production environment
cp .env.example .env
# Edit configuration

# Run production server
make run
```

### Scaling Considerations

- **Redis**: Use external Redis for multi-instance deployments
- **GTFS Caching**: Large feeds benefit from persistent caching
- **Rate Limiting**: Consider adding rate limiting for public APIs
- **CDN**: Serve static assets via CDN

## 🔍 How It Works

### Solar Position Calculation

Uses the [Astral](https://astral.readthedocs.io/) library for precise solar calculations:

```python
from astral.sun import azimuth, elevation

# Get sun position at specific time/location
solar_azimuth = azimuth(observer, datetime)    # 0-360° (N=0°, E=90°)
solar_altitude = elevation(observer, datetime)  # -90° to +90°
```

### Route Geometry

Priority order for route data:
1. **GTFS Shapes**: High-accuracy polyline from `shapes.txt`
2. **Stop Sequences**: Straight lines between consecutive stops
3. **Fallback**: Sample coordinates for demo purposes

### Bearing Calculation

Great-circle bearing between consecutive points:

```python
def calculate_bearing(lat1, lon1, lat2, lon2):
    # Convert to radians and apply spherical geometry
    # Returns bearing in degrees (0-360°)
```

## 🚨 Limitations & Edge Cases

- **Night Travel**: Low sun altitude (< 10°) results in mostly NEITHER
- **Tunnels**: No automatic tunnel detection (could be added via config)
- **Curved Tracks**: Uses straight-line segments between points
- **Weather**: Assumes clear skies (doesn't account for cloud cover)
- **Carriage Orientation**: Assumes standard forward/backward facing

## 🤝 Contributing

1. Fork the repository
2. Create feature branch: `git checkout -b feature/amazing-feature`
3. Make changes and add tests
4. Run tests: `make test`
5. Format code: `make format`
6. Submit pull request

### Development Workflow

```bash
# Setup development environment
make setup-dev

# Run development server
make dev

# Test your changes
make test

# Format and lint
make format
make lint
```

## 📝 License

MIT License - see LICENSE file for details.

## 🙏 Acknowledgments

- **Astral Library**: Solar position calculations
- **GTFS Community**: Public transit data standards
- **FastAPI Team**: Excellent web framework
- **Leaflet**: Interactive mapping
- **Melbourne PTV**: Public transport data

---

Built with ☀️ for better train journeys in Melbourne and beyond!