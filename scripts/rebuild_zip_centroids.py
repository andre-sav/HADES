"""Rebuild data/zip_centroids.csv from US Census Bureau ZCTA Gazetteer.

Source: https://www.census.gov/geographies/reference-files/time-series/geo/gazetteer-files.html
The Gazetteer file is public domain and updated annually. ZCTA internal points
(INTPTLAT/INTPTLONG) are guaranteed to fall inside the ZCTA polygon.

State is derived from ZIP-3 prefix via utils.ZIP_PREFIX_TO_STATE.

Usage:
    python scripts/rebuild_zip_centroids.py
"""

from __future__ import annotations

import csv
import io
import sys
import urllib.request
import zipfile
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from utils import ZIP_PREFIX_TO_STATE, ZIP_EXCEPTIONS_TO_STATE  # noqa: E402

GAZETTEER_URL = (
    "https://www2.census.gov/geo/docs/maps-data/data/gazetteer/"
    "2024_Gazetteer/2024_Gaz_zcta_national.zip"
)
OUTPUT = ROOT / "data" / "zip_centroids.csv"
MAX_SHARED_COORD = 3  # in-state collision threshold; legitimate overlap is rare


def fetch_gazetteer() -> list[dict]:
    print(f"Downloading {GAZETTEER_URL} ...")
    with urllib.request.urlopen(GAZETTEER_URL) as resp:
        blob = resp.read()
    with zipfile.ZipFile(io.BytesIO(blob)) as zf:
        name = next(n for n in zf.namelist() if n.endswith(".txt"))
        with zf.open(name) as f:
            text = f.read().decode("utf-8")
    rows = []
    reader = csv.DictReader(io.StringIO(text), delimiter="\t")
    for row in reader:
        rows.append({k.strip(): v.strip() for k, v in row.items()})
    print(f"  {len(rows)} ZCTAs in source file")
    return rows


def build_centroids(rows: list[dict]) -> list[dict]:
    out: list[dict] = []
    skipped_no_state = 0
    for row in rows:
        zcta = row["GEOID"].zfill(5)
        # Single-ZIP exceptions (e.g. 06390 Fishers Island NY) override the prefix map
        state = ZIP_EXCEPTIONS_TO_STATE.get(zcta) or ZIP_PREFIX_TO_STATE.get(zcta[:3])
        if state is None:
            skipped_no_state += 1
            continue
        out.append({
            "zip": zcta,
            "lat": float(row["INTPTLAT"]),
            "lng": float(row["INTPTLONG"]),
            "state": state,
        })
    out.sort(key=lambda r: r["zip"])
    print(f"  Built {len(out)} ZIP centroids ({skipped_no_state} non-state ZCTAs skipped)")
    return out


def validate(centroids: list[dict]) -> None:
    """Fail fast on the kind of collapse that broke the previous dataset."""
    print("Validating centroid integrity...")

    # 1. No exact duplicates of (lat, lng) shared by more than MAX_SHARED_COORD ZIPs
    coord_buckets: dict[tuple[float, float], list[str]] = {}
    for r in centroids:
        coord_buckets.setdefault((r["lat"], r["lng"]), []).append(r["zip"])
    worst = sorted(coord_buckets.items(), key=lambda kv: -len(kv[1]))[:5]
    over_limit = [b for b in worst if len(b[1]) > MAX_SHARED_COORD]
    if over_limit:
        for (lat, lng), zips in over_limit:
            print(f"  ❌ ({lat}, {lng}) shared by {len(zips)} ZIPs: {zips[:5]}{'...' if len(zips)>5 else ''}")
        raise SystemExit(f"Centroid collapse detected (>{MAX_SHARED_COORD} ZIPs per coord)")
    print(f"  ✓ Max ZIPs at one coord: {len(worst[0][1])} (limit: {MAX_SHARED_COORD})")

    # 2. State coverage matches expectation (50 states + DC = 51)
    state_counts = Counter(r["state"] for r in centroids)
    if len(state_counts) < 51:
        missing = set(set(ZIP_PREFIX_TO_STATE.values())) - set(state_counts)
        raise SystemExit(f"Missing states: {missing}")
    print(f"  ✓ {len(state_counts)} states covered")

    # 3. CA spot checks (the cases that surfaced this bug)
    by_zip = {r["zip"]: r for r in centroids}
    checks = {
        "90004": (34.077, -118.310, "Koreatown LA"),
        "91355": (34.421, -118.555, "Valencia"),
        "91367": (34.181, -118.640, "Woodland Hills"),
        "91711": (34.107, -117.715, "Claremont"),
        "95816": (38.572, -121.468, "Sacramento"),
    }
    print("  Spot checks:")
    for zip_code, (exp_lat, exp_lng, name) in checks.items():
        if zip_code not in by_zip:
            print(f"    ⚠ {zip_code} ({name}) missing from centroids")
            continue
        got = by_zip[zip_code]
        # Allow some tolerance — INTPTLAT is the internal point, not population centroid
        err = ((got["lat"] - exp_lat) ** 2 + (got["lng"] - exp_lng) ** 2) ** 0.5 * 69
        marker = "✓" if err < 5 else "⚠"
        print(f"    {marker} {zip_code} {name}: got ({got['lat']:.3f},{got['lng']:.3f}), expected ~({exp_lat},{exp_lng}), err {err:.1f}mi")


def write_csv(centroids: list[dict]) -> None:
    print(f"Writing {OUTPUT} ...")
    with open(OUTPUT, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["zip", "lat", "lng", "state"])
        writer.writeheader()
        writer.writerows(centroids)
    print(f"  Wrote {len(centroids)} rows")


def main() -> None:
    rows = fetch_gazetteer()
    centroids = build_centroids(rows)
    validate(centroids)
    write_csv(centroids)
    print("Done.")


if __name__ == "__main__":
    main()
