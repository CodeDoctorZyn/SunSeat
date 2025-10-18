"""
SunSeat FastAPI application.
Provides REST API and web interface for public transport sun exposure prediction.
"""

from fastapi import FastAPI, Request, Form, HTTPException, Query, Depends
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from datetime import datetime, timedelta
import os
import logging
from typing import Optional, List
import json
import pandas as pd
from fastapi import Response

from app.models import (
    TripQuery, CarriageFacing, AdviceSummary, APIResponse, APIError,
    StopSearchResult, SystemStatus, TransportMode
)
from app.deps import get_timezone, init_cache
from app.gtfs import get_gtfs_loader
from app.advisor import generate_trip_advice_from_query, get_disruption_alerts, validate_trip_query
# Optional integrations: guard imports so app can run without these modules present
try:
    from app.ptv_client import create_ptv_client, RouteType
except Exception:  # pragma: no cover - fallback when module not available
    create_ptv_client = None

    class RouteType:  # minimal placeholder
        TRAIN = 0
        TRAM = 1
        BUS = 2
        VLINE_TRAIN = 3

try:
    from app.realtime import get_realtime_client
except Exception:  # pragma: no cover - fallback when module not available
    def get_realtime_client():
        class _Dummy:
            def get_all_service_alerts(self):
                return []

        return _Dummy()

from app.solar import get_solar_api
from functools import lru_cache

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Initialize FastAPI app
app = FastAPI(
    title="SunSeat",
    description="Public transport sunlight-side predictor for Victoria, Australia. "
                "Predicts which side of the vehicle (LEFT or RIGHT) will face the sun during your journey.",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc"
)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Configure appropriately for production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Initialize cache
init_cache()

# Setup templates and static files
templates = Jinja2Templates(directory="app/templates")
app.mount("/static", StaticFiles(directory="app/static"), name="static")


# Dependency for error handling
def handle_api_errors(func):
    """Decorator to handle API errors consistently."""
    async def wrapper(*args, **kwargs):
        try:
            return await func(*args, **kwargs)
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"API error in {func.__name__}: {e}")
            raise HTTPException(status_code=500, detail=str(e))
    return wrapper


# Web Interface Routes
@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    """Render the main form page."""
    # Get current time in Melbourne timezone for defaults
    melbourne_tz = get_timezone()
    now = datetime.now(melbourne_tz)
    
    # Get system status for health indicators
    try:
        gtfs_loader = get_gtfs_loader()
        realtime_client = get_realtime_client()
        
        system_status = {
            "gtfs_status": "Connected",
            "realtime_status": "Connected", 
            "solar_api_status": "Connected" if os.getenv("SOLCAST_API_KEY") else "Fallback Mode"
        }
    except Exception as e:
        logger.error(f"Error getting system status: {e}")
        system_status = {
            "gtfs_status": "Error",
            "realtime_status": "Error",
            "solar_api_status": "Error"
        }
    
    return templates.TemplateResponse("index.html", {
        "request": request,
        "default_date": now.strftime("%Y-%m-%d"),
        "default_time": now.strftime("%H:%M"),
        "system_status": system_status
    })


@app.post("/advice", response_class=HTMLResponse)
async def get_advice_web(
    request: Request,
    origin_station: str = Form(...),
    destination_station: str = Form(...),
    line: str = Form(...),
    departure_date: str = Form(...),
    departure_time: str = Form(...),
    facing: str = Form(CarriageFacing.UNKNOWN.value)
):
    """Get seat advice via web form (returns HTML partial)."""
    try:
        # Create trip query
        trip_query = TripQuery(
            origin_station=origin_station,
            destination_station=destination_station,
            line=line,
            departure_date=departure_date,
            departure_time=departure_time,
            facing=CarriageFacing(facing)
        )
        
        # Validate query
        is_valid, error_msg = validate_trip_query(trip_query)
        if not is_valid:
            return templates.TemplateResponse("advice_partial.html", {
                "request": request,
                "error": error_msg
            })
        
        # Generate advice
        advice_summary = generate_trip_advice_from_query(trip_query)
        
        # Get disruption alerts
        disruptions = get_disruption_alerts(line)
        
        return templates.TemplateResponse("advice_partial.html", {
            "request": request,
            "advice": advice_summary,
            "disruptions": disruptions,
            "query": trip_query
        })
        
    except Exception as e:
        logger.error(f"Error generating advice: {e}")
        return templates.TemplateResponse("advice_partial.html", {
            "request": request,
            "error": f"Unable to generate advice: {str(e)}"
        })


@app.get("/map", response_class=HTMLResponse)
async def get_map(
    request: Request,
    origin: Optional[str] = Query(None),
    destination: Optional[str] = Query(None),
    route_data: Optional[str] = Query(None)
):
    """Return map partial with route visualization."""
    try:
        # Determine route coordinates from provided data or fallback sample
        coordinates = None
        if route_data:
            try:
                parsed = json.loads(route_data)
                # Accept either {"coordinates": [[lat, lon], ...]} or a raw list
                if isinstance(parsed, dict) and "coordinates" in parsed:
                    coordinates = parsed["coordinates"]
                elif isinstance(parsed, list) and (len(parsed) == 0 or isinstance(parsed[0], list)):
                    coordinates = parsed
            except Exception:
                coordinates = None

        if not coordinates:
            # Fallback to a built-in sample route (Melbourne area)
            from app.gtfs import load_sample_geojson_route
            coordinates = load_sample_geojson_route()

        # Build colored segments with basic sun-side advice for visualization
        from app.geometry import polyline_to_segments
        from app.advisor import calculate_segment_advice
        from app.solar import get_solar_position_cached
        from app.deps import get_timezone
        from datetime import datetime as _dt

        segments_geo = polyline_to_segments(coordinates)

        # Compute advice per segment using current Melbourne time at segment midpoint
        mel_tz = get_timezone()
        now = _dt.now(mel_tz)
        viz_segments = []
        for seg in segments_geo:
            # Use midpoint values already computed in polyline_to_segments
            az, alt, _irr = get_solar_position_cached(
                seg["midpoint_lat"], seg["midpoint_lon"], now, include_irradiance=True
            )
            advice_enum, _meta = calculate_segment_advice(
                seg["bearing"], az, alt
            )
            viz_segments.append({
                "start_lat": seg["start_lat"],
                "start_lon": seg["start_lon"],
                "end_lat": seg["end_lat"],
                "end_lon": seg["end_lon"],
                "advice": str(advice_enum)
            })

        # Compute a reasonable map center
        if coordinates:
            avg_lat = sum(pt[0] for pt in coordinates) / len(coordinates)
            avg_lon = sum(pt[1] for pt in coordinates) / len(coordinates)
        else:
            avg_lat, avg_lon = -37.8136, 144.9631  # Melbourne CBD fallback

        return templates.TemplateResponse("map_partial.html", {
            "request": request,
            "coordinates": coordinates,
            "segments": viz_segments,
            "center_lat": avg_lat,
            "center_lon": avg_lon,
            "origin": origin,
            "destination": destination
        })
        
    except Exception as e:
        logger.error(f"Error generating map: {e}")
        return templates.TemplateResponse("map_partial.html", {
            "request": request,
            "error": "Unable to load map data"
        })


# API Routes
@app.post("/api/advice", response_model=APIResponse)
@handle_api_errors
async def get_advice_api(trip_query: TripQuery):
    """Get seat advice via JSON API."""
    # Validate query
    is_valid, error_msg = validate_trip_query(trip_query)
    if not is_valid:
        return APIResponse(
            success=False,
            error=APIError(error=error_msg, error_code="INVALID_QUERY")
        )
    
    # Generate advice
    advice_summary = generate_trip_advice_from_query(trip_query)
    
    return APIResponse(
        success=True,
        data=advice_summary
    )


@app.get("/api/stops", response_model=APIResponse)
@handle_api_errors
async def search_stops(
    q: str = Query(..., description="Search term"),
    limit: int = Query(10, description="Maximum results", ge=1, le=50),
    transport_types: Optional[str] = Query(None, description="Comma-separated transport types (train,tram,bus)")
):
    """Search for stops by name."""
    try:
        ptv_client = create_ptv_client()
        
        # Parse transport types
        route_types = None
        if transport_types:
            type_mapping = {
                'train': RouteType.TRAIN,
                'tram': RouteType.TRAM,
                'bus': RouteType.BUS,
                'vline': RouteType.VLINE_TRAIN
            }
            route_types = []
            for t in transport_types.split(','):
                if t.strip().lower() in type_mapping:
                    route_types.append(type_mapping[t.strip().lower()])
        
        # Search stops
        stops = ptv_client.search_stops(q, route_types=route_types, max_results=limit)
        
        # Convert to our model format
        stop_results = []
        for stop in stops:
            stop_result = StopSearchResult(
                stop_id=str(stop['stop_id']),
                stop_name=stop['stop_name'],
                stop_lat=stop.get('stop_latitude', 0.0),
                stop_lon=stop.get('stop_longitude', 0.0),
                zone_id=stop.get('zone_id'),
                route_types=stop.get('route_types', [])
            )
            stop_results.append(stop_result)
        
        return APIResponse(success=True, data=stop_results)
        
    except Exception as e:
        logger.error(f"Error searching stops: {e}")
        
        # Fallback to GTFS data
        try:
            gtfs_loader = get_gtfs_loader()
            stops = gtfs_loader.search_stops(q, limit)
            
            stop_results = []
            for stop in stops:
                stop_result = StopSearchResult(
                    stop_id=stop['stop_id'],
                    stop_name=stop['stop_name'],
                    stop_lat=stop.get('stop_lat', 0.0),
                    stop_lon=stop.get('stop_lon', 0.0),
                    zone_id=stop.get('zone_id')
                )
                stop_results.append(stop_result)
            
            return APIResponse(success=True, data=stop_results)
            
        except Exception as e2:
            logger.error(f"Fallback stop search failed: {e2}")
            raise HTTPException(status_code=500, detail="Stop search unavailable")


    @app.get("/stops/options", response_class=HTMLResponse)
    async def stop_options(q: str = Query("", description="Search term"), limit: int = Query(10, ge=1, le=50)):
        """Return HTML <option> list for datalist autocomplete of stops."""
        items: List[dict] = []
        # Try PTV first
        try:
            if create_ptv_client:
                ptv = create_ptv_client()
                for s in ptv.search_stops(q, max_results=limit):
                    name = s.get('stop_name')
                    if name:
                        items.append({'name': name})
        except Exception:
            items = []
        # Fallback to GTFS
        if not items:
            try:
                gtfs = get_gtfs_loader()
                for s in gtfs.find_stops(q)[:limit]:
                    name = s.get('stop_name')
                    if name:
                        items.append({'name': name})
            except Exception:
                pass
        # Render simple option list
        options_html = "\n".join([f"<option value=\"{item['name']}\"></option>" for item in items])
        return HTMLResponse(content=options_html)


@app.get("/api/routes", response_model=APIResponse)
@handle_api_errors
async def get_routes(
    transport_type: Optional[TransportMode] = Query(None, description="Filter by transport type")
):
    """Get available routes/lines."""
    # First try PTV if available; otherwise fall back to GTFS/static list
    try:
        if create_ptv_client:
            ptv_client = create_ptv_client()
            # Map transport mode to PTV route type
            route_type_filter = None
            if transport_type:
                type_mapping = {
                    TransportMode.TRAIN: RouteType.TRAIN,
                    TransportMode.TRAM: RouteType.TRAM,
                    TransportMode.BUS: RouteType.BUS,
                    TransportMode.VLINE: RouteType.VLINE_TRAIN
                }
                rt = type_mapping.get(transport_type)
                route_type_filter = [rt] if rt is not None else None
            routes = ptv_client.get_routes(route_types=route_type_filter)
            return APIResponse(success=True, data=routes)
    except Exception as e:
        logger.warning(f"PTV routes unavailable, falling back to GTFS: {e}")

    # GTFS/static fallback
    try:
        gtfs = get_gtfs_loader()
        routes_df = gtfs.routes
        routes_list = []
        if not routes_df.empty:
            # Attempt to include a route_type if present; default to Rail (2)
            has_type = 'route_type' in routes_df.columns
            for _, r in routes_df.iterrows():
                routes_list.append({
                    'route_id': str(r.get('route_id', '')),
                    'route_name': r.get('route_long_name') or r.get('route_short_name') or '',
                    'route_short_name': r.get('route_short_name') or '',
                    'route_type': int(r.get('route_type')) if has_type and not pd.isna(r.get('route_type')) else 2
                })
        else:
            # Minimal static list for Melbourne trains (includes Craigieburn)
            static_trains = [
                "Alamein","Belgrave","Craigieburn","Cranbourne","Frankston","Glen Waverley",
                "Hurstbridge","Lilydale","Mernda","Pakenham","Sandringham","Sunbury","Upfield",
                "Werribee","Williamstown"
            ]
            routes_list = [
                {
                    'route_id': name.lower(),
                    'route_name': f"{name} Line",
                    'route_short_name': name,
                    'route_type': 2
                }
                for name in static_trains
            ]
        return APIResponse(success=True, data=routes_list)
    except Exception as e:
        logger.error(f"Fallback routes failed: {e}")
        raise HTTPException(status_code=500, detail="Routes unavailable")


@app.get("/routes/options", response_class=HTMLResponse)
async def get_route_options(
    request: Request,
    transport_type: Optional[TransportMode] = Query(None)
):
    """Return HTML <option> list for the Line/Service select, using routes data."""
    # Reuse the JSON endpoint logic directly
    try:
        api_resp = await get_routes(transport_type)
        routes = api_resp.data if isinstance(api_resp, APIResponse) else []
    except Exception:
        routes = []

    # Ensure we have a simple list even if structures differ
    normalized = []
    for r in routes or []:
        # Accept both snake_case and PTV shapes
        route_name = r.get('route_long_name') or r.get('route_name') or r.get('route_short_name') or ''
        short_name = r.get('route_short_name') or route_name
        route_type = r.get('route_type', 2)
        normalized.append({'name': route_name, 'short': short_name, 'type': route_type})

    # Render simple options block
    return templates.TemplateResponse("route_options.html", {
        "request": request,
        "routes": normalized
    })


@app.get("/api/disruptions", response_model=APIResponse)
@handle_api_errors
async def get_disruptions(
    route_name: Optional[str] = Query(None, description="Filter by route name")
):
    """Get current service disruptions."""
    try:
        if route_name:
            disruptions = get_disruption_alerts(route_name)
        else:
            # Get all disruptions
            realtime_client = get_realtime_client()
            alerts = realtime_client.get_all_service_alerts()
            
            disruptions = []
            for alert in alerts:
                disruptions.append({
                    'title': alert.header_text,
                    'description': alert.description_text,
                    'severity': alert.severity,
                    'affected_routes': alert.affected_routes
                })
        
        return APIResponse(success=True, data=disruptions)
        
    except Exception as e:
        logger.error(f"Error getting disruptions: {e}")
        return APIResponse(success=True, data=[])  # Return empty list on error


@app.get("/api/status", response_model=APIResponse)
async def get_system_status():
    """Get system health status."""
    try:
        status = SystemStatus()
        
        # Check GTFS status
        try:
            gtfs_loader = get_gtfs_loader()
            if gtfs_loader.last_update_file.exists():
                with open(gtfs_loader.last_update_file, 'r') as f:
                    status.gtfs_last_updated = datetime.fromisoformat(f.read().strip())
        except:
            pass
        
        # Check realtime status
        try:
            realtime_client = get_realtime_client()
            status.realtime_status = True
        except:
            status.realtime_status = False
        
        # Check solar API status
        try:
            solar_api = get_solar_api()
            status.solar_api_status = solar_api.solcast_api_key is not None
        except:
            status.solar_api_status = False
        
        # Check PTV API status
        try:
            ptv_client = create_ptv_client()
            status.ptv_api_status = True
        except:
            status.ptv_api_status = False
        
        return APIResponse(success=True, data=status)
        
    except Exception as e:
        logger.error(f"Error getting system status: {e}")
        raise HTTPException(status_code=500, detail="Status unavailable")


# Health check endpoint
@app.get("/health")
async def health_check():
    """Simple health check endpoint."""
    return {"status": "healthy", "timestamp": datetime.now().isoformat()}


# Background task to update GTFS data
@app.on_event("startup")
async def startup_event():
    """Initialize application on startup."""
    logger.info("Starting SunSeat application...")
    
    try:
        # Initialize GTFS data (non-blocking)
        gtfs_loader = get_gtfs_loader()
        logger.info("GTFS loader initialized")
        
        # Initialize real-time client
        realtime_client = get_realtime_client()
        logger.info("Real-time client initialized")
        
        logger.info("SunSeat application started successfully")
        
    except Exception as e:
        logger.error(f"Error during startup: {e}")


@app.on_event("shutdown")
async def shutdown_event():
    """Cleanup on application shutdown."""
    logger.info("Shutting down SunSeat application...")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=int(os.getenv("PORT", 8000)),
        reload=os.getenv("ENVIRONMENT") == "development"
    )