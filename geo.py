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
        math.sin(delta_lat / 2) ** 2
        + math.cos(lat1_rad) * math.cos(lat2_rad) * math.sin(delta_lng / 2) ** 2
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

    center_lat, center_lng, _ = centroids[center_zip]

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
        List of state codes, most frequent first, then alphabetical
    """
    if not zips:
        return []

    # Count ZIPs per state
    state_counts: dict[str, int] = {}
    for z in zips:
        state = z["state"]
        state_counts[state] = state_counts.get(state, 0) + 1

    # Sort by count (desc), then alphabetically
    return sorted(state_counts.keys(), key=lambda s: (-state_counts[s], s))


def get_state_counts_from_zips(zips: list[dict]) -> dict[str, int]:
    """
    Get count of ZIPs per state.

    Args:
        zips: List of ZIP dicts (from get_zips_in_radius)

    Returns:
        Dict mapping state code to ZIP count, e.g. {"TX": 142, "OK": 5}
    """
    if not zips:
        return {}

    state_counts: dict[str, int] = {}
    for z in zips:
        state = z["state"]
        state_counts[state] = state_counts.get(state, 0) + 1

    return state_counts
