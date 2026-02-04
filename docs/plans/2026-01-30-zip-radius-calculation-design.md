# ZIP Radius Calculation Design

**Date:** 2026-01-30
**Status:** Approved for implementation

## Problem

When operators are near state borders, a radius search can extend into neighboring states. Currently, the state filter is manually entered and defaults to the operator's state only, causing leads in neighboring states to be missed.

Additionally, we're relying on ZoomInfo's interpretation of radius searches. By calculating explicit ZIP codes ourselves, we gain full control over the search area.

## Solution

Calculate all ZIP codes within the specified radius locally using ZIP centroid coordinates, then send an explicit ZIP list to ZoomInfo. States are derived directly from the ZIP list.

## Data

**File:** `data/zip_centroids.csv` (~800KB)

**Source:** simplemaps.com Basic (free, commercial-use license)

**Schema:**
```csv
zip,lat,lng,state
75201,32.7872,-96.7985,TX
71854,33.4318,-94.0743,AR
```

## New Module: `geo.py`

```python
"""Geographic utilities for ZIP radius calculations."""

import csv
import math
from functools import lru_cache
from pathlib import Path

DATA_DIR = Path(__file__).parent / "data"


@lru_cache(maxsize=1)
def load_zip_centroids() -> dict[str, tuple[float, float, str]]:
    """
    Load ZIP centroid data.

    Returns:
        Dict mapping ZIP code to (lat, lng, state)
    """
    centroids = {}
    csv_path = DATA_DIR / "zip_centroids.csv"

    with open(csv_path, "r") as f:
        reader = csv.DictReader(f)
        for row in reader:
            centroids[row["zip"]] = (
                float(row["lat"]),
                float(row["lng"]),
                row["state"],
            )

    return centroids


def haversine_distance(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """
    Calculate distance in miles between two coordinates using Haversine formula.

    Args:
        lat1, lng1: First point (degrees)
        lat2, lng2: Second point (degrees)

    Returns:
        Distance in miles
    """
    R = 3959  # Earth's radius in miles

    lat1_rad = math.radians(lat1)
    lat2_rad = math.radians(lat2)
    delta_lat = math.radians(lat2 - lat1)
    delta_lng = math.radians(lng2 - lng1)

    a = (
        math.sin(delta_lat / 2) ** 2 +
        math.cos(lat1_rad) * math.cos(lat2_rad) * math.sin(delta_lng / 2) ** 2
    )
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))

    return R * c


def get_zips_in_radius(center_zip: str, radius_miles: float) -> list[dict]:
    """
    Get all ZIP codes within radius of a center ZIP.

    Args:
        center_zip: 5-digit ZIP code (center point)
        radius_miles: Search radius in miles

    Returns:
        List of dicts with keys: zip, state, lat, lng, distance_miles
        Sorted by distance (center ZIP first at 0.0 miles).
        Returns empty list if center_zip not found.
    """
    centroids = load_zip_centroids()

    if center_zip not in centroids:
        return []

    center_lat, center_lng, center_state = centroids[center_zip]

    results = []
    for zip_code, (lat, lng, state) in centroids.items():
        distance = haversine_distance(center_lat, center_lng, lat, lng)

        if distance <= radius_miles:
            results.append({
                "zip": zip_code,
                "state": state,
                "lat": lat,
                "lng": lng,
                "distance_miles": round(distance, 2),
            })

    # Sort by distance
    results.sort(key=lambda x: x["distance_miles"])
    return results


def get_states_from_zips(zips: list[dict]) -> list[str]:
    """
    Extract unique states from ZIP list, ordered by frequency.

    Args:
        zips: List of ZIP dicts (from get_zips_in_radius)

    Returns:
        List of state codes, most frequent first
    """
    if not zips:
        return []

    # Count ZIPs per state
    state_counts = {}
    for z in zips:
        state = z["state"]
        state_counts[state] = state_counts.get(state, 0) + 1

    # Sort by count (desc), then alphabetically
    return sorted(state_counts.keys(), key=lambda s: (-state_counts[s], s))
```

## UI Changes: `pages/2_Geography_Workflow.py`

### Radius Options

Replace current radius dropdown with:

```python
RADIUS_OPTIONS = {
    10.0: "10 miles",
    12.5: "12.5 miles",
    15.0: "15 miles (Recommended)",
    "custom": "Custom...",
}
```

When "Custom" selected, show number input (1-50 miles, 0.5 step).

### Updated Flow

```
┌─────────────────────────────────────────────────────────┐
│  Center ZIP: [75201]     Radius: [15 miles ▼]           │
├─────────────────────────────────────────────────────────┤
│  📍 203 ZIP codes in radius                             │
│  States: TX (198), OK (5)                               │
│  [Show ZIP codes ▼]                                     │
├─────────────────────────────────────────────────────────┤
│  [Quality Filters ▼]                                    │
│  [Industry Filters ▼]                                   │
│  [API Request Preview ▼]                                │
└─────────────────────────────────────────────────────────┘
```

### Key Changes

1. **ZIP calculation on input change:**
   - When center ZIP or radius changes, call `get_zips_in_radius()`
   - Store result in session state
   - Display ZIP count and state breakdown

2. **States auto-derived:**
   - Remove manual state input field
   - States come from `get_states_from_zips()`
   - Display as read-only info (e.g., "States: TX (198), OK (5)")

3. **API request uses explicit ZIP list:**
   - `zipCodeRadiusList`: one entry per ZIP with `radius: 0`
   - Shows full ZIP count in preview

4. **Manual ZIP mode unchanged:**
   - User pastes ZIP list
   - States derived from pasted ZIPs using same function

## Files to Create/Modify

| File | Action |
|------|--------|
| `data/zip_centroids.csv` | Create (download from simplemaps) |
| `geo.py` | Create |
| `pages/2_Geography_Workflow.py` | Modify |
| `tests/test_geo.py` | Create |

## Test Cases

```python
def test_haversine_distance():
    # Dallas to Fort Worth ~30 miles
    distance = haversine_distance(32.7767, -96.7970, 32.7555, -97.3308)
    assert 29 < distance < 31

def test_get_zips_in_radius_center_included():
    zips = get_zips_in_radius("75201", 10)
    assert zips[0]["zip"] == "75201"
    assert zips[0]["distance_miles"] == 0.0

def test_get_zips_in_radius_invalid_zip():
    zips = get_zips_in_radius("00000", 10)
    assert zips == []

def test_get_states_from_zips_ordering():
    zips = [
        {"zip": "1", "state": "TX"},
        {"zip": "2", "state": "TX"},
        {"zip": "3", "state": "OK"},
    ]
    states = get_states_from_zips(zips)
    assert states == ["TX", "OK"]

def test_border_zip_includes_multiple_states():
    # Texarkana, TX is on AR border
    zips = get_zips_in_radius("75501", 15)
    states = get_states_from_zips(zips)
    assert "TX" in states
    assert "AR" in states
```

## Dependencies

None new. Pure Python standard library (csv, math).

## Data Maintenance

ZIP centroid data is relatively static. Recommend annual refresh from simplemaps.com or US Census.
