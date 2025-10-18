# GTFS Sample Data

This directory is where you should place your GTFS static feed data for Melbourne (or other) train networks.

## Getting Melbourne GTFS Data

1. **Public Transport Victoria (PTV)**
   - Visit: https://www.data.vic.gov.au/
   - Search for "GTFS" or "Public Transport Timetables"
   - Download the latest GTFS static feed
   
2. **Alternative Sources**
   - OpenMobilityData: https://transitfeeds.com/
   - Search for "Melbourne" or "Victoria"

## Required GTFS Files

Place these CSV files in this directory (`data/gtfs_sample/`):

- `routes.txt` - Train lines/routes information
- `stops.txt` - Station locations and details  
- `trips.txt` - Individual trip instances
- `stop_times.txt` - Stop times for each trip
- `shapes.txt` - Route geometry (optional but recommended)

## File Structure

```
data/gtfs_sample/
├── routes.txt
├── stops.txt  
├── trips.txt
├── stop_times.txt
├── shapes.txt (optional)
├── calendar.txt (optional)
└── agency.txt (optional)
```

## Testing Without GTFS Data

If you don't have GTFS data, the app includes sample route data for testing:
- Sample Melbourne train route coordinates
- Fallback route generation between stations
- Basic demo functionality

## Notes

- The app prioritizes `shapes.txt` for accurate route geometry
- Without shapes, it falls back to straight lines between stops
- For best results, ensure your GTFS feed includes shape data
- Large GTFS feeds may require more memory and processing time