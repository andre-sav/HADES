"""
Scoring Calibration Script

Reads enriched HLM Locating data and computes empirical delivery rates
per SIC code and employee bucket. Outputs min-max scaled scores (20-100)
for use in config/icp.yaml.

Usage:
    python calibrate_scoring.py
"""

import csv
import re
from collections import defaultdict
from pathlib import Path

import yaml


DATA_PATH = Path(__file__).parent / "data" / "enriched_locatings.csv"
OVERRIDES_PATH = Path(__file__).parent / "data" / "sic_manual_overrides.csv"
CONFIG_PATH = Path(__file__).parent / "config" / "icp.yaml"

MIN_RECORDS = 10  # Minimum records for reliable per-SIC scoring
SCORE_MIN = 20    # Floor score (worst-converting SIC)
SCORE_MAX = 100   # Ceiling score (best-converting SIC)


def load_icp_sics():
    """Load ICP SIC codes from config/icp.yaml."""
    with open(CONFIG_PATH) as f:
        config = yaml.safe_load(f)
    return set(config.get("hard_filters", {}).get("sic_codes", []))


def load_overrides():
    """Load manual SIC overrides keyed by company_name."""
    overrides = {}
    if not OVERRIDES_PATH.exists():
        return overrides
    with open(OVERRIDES_PATH) as f:
        for row in csv.DictReader(f):
            overrides[row["company_name"].strip()] = row["sic_code"].strip()
    return overrides


def extract_sic(raw):
    """Extract 4-digit SIC from raw value like '7011-01' or '7011'."""
    if not raw or not raw.strip():
        return None
    m = re.match(r"(\d{4})", raw.strip())
    return m.group(1) if m else None


def parse_employees(raw):
    """Parse free-text employee count. Returns midpoint for ranges."""
    if not raw or not raw.strip():
        return None
    raw = raw.strip().replace(",", "")
    # Range: "50 to 99"
    m = re.match(r"(\d+)\s*to\s*(\d+)", raw)
    if m:
        return (int(m.group(1)) + int(m.group(2))) / 2
    # Single number
    m = re.match(r"^(\d+)$", raw)
    if m:
        return int(m.group(1))
    return None


def min_max_scale(rate, min_rate, max_rate):
    """Scale a rate to SCORE_MIN..SCORE_MAX range."""
    if max_rate == min_rate:
        return round((SCORE_MIN + SCORE_MAX) / 2)
    scaled = SCORE_MIN + (rate - min_rate) / (max_rate - min_rate) * (SCORE_MAX - SCORE_MIN)
    return round(scaled)


def main():
    overrides = load_overrides()
    icp_sics = load_icp_sics()

    with open(DATA_PATH) as f:
        rows = list(csv.DictReader(f))

    print(f"Total records: {len(rows)}")

    # --- Data Cleaning ---
    # Filter out records with empty stage
    rows = [r for r in rows if r.get("stage", "").strip()]
    print(f"After removing empty stages: {len(rows)}")

    # --- Classify delivered vs not ---
    for r in rows:
        r["_delivered"] = r["stage"].strip() == "Green/ Delivered"

    delivered_count = sum(1 for r in rows if r["_delivered"])
    print(f"Delivered: {delivered_count}")
    print(f"Not delivered: {len(rows) - delivered_count}")
    print(f"Overall delivery rate: {delivered_count / len(rows) * 100:.1f}%")
    print()

    # --- Resolve SIC codes ---
    for r in rows:
        sic = extract_sic(r.get("vs_sic", ""))
        if not sic and r["_delivered"]:
            # Try manual overrides for delivered records without SIC
            sic = extract_sic(overrides.get(r.get("company_name", "").strip(), ""))
        r["_sic"] = sic

    # Check delivered SIC coverage
    delivered_rows = [r for r in rows if r["_delivered"]]
    delivered_with_sic = sum(1 for r in delivered_rows if r["_sic"])
    delivered_no_sic = sum(1 for r in delivered_rows if not r["_sic"])
    print(f"Delivered SIC coverage: {delivered_with_sic}/{len(delivered_rows)}")
    if delivered_no_sic:
        print(f"  WARNING: {delivered_no_sic} delivered records without SIC:")
        for r in delivered_rows:
            if not r["_sic"]:
                print(f"    {r.get('company_name', '?')}, {r.get('city', '?')}, {r.get('state', '?')}")
    print()

    # --- Per-SIC Delivery Rates ---
    sic_stats = defaultdict(lambda: {"delivered": 0, "total": 0})
    for r in rows:
        sic = r["_sic"]
        if not sic:
            continue
        sic_stats[sic]["total"] += 1
        if r["_delivered"]:
            sic_stats[sic]["delivered"] += 1

    # Separate reliable (N >= MIN_RECORDS) from low-N
    reliable = {s: v for s, v in sic_stats.items() if v["total"] >= MIN_RECORDS}
    low_n = {s: v for s, v in sic_stats.items() if v["total"] < MIN_RECORDS and v["delivered"] > 0}

    # Compute rates
    for s, v in reliable.items():
        v["rate"] = v["delivered"] / v["total"]

    # Overall mean rate (for low-N fallback)
    total_d = sum(v["delivered"] for v in sic_stats.values())
    total_n = sum(v["total"] for v in sic_stats.values())
    mean_rate = total_d / total_n if total_n else 0

    # Min-max scaling
    rates = [v["rate"] for v in reliable.values()]
    min_rate = min(rates)
    max_rate = max(rates)

    for s, v in reliable.items():
        v["score"] = min_max_scale(v["rate"], min_rate, max_rate)

    # --- Employee Scale ---
    emp_buckets = {"50-100": {"delivered": 0, "total": 0},
                   "101-500": {"delivered": 0, "total": 0},
                   "501+": {"delivered": 0, "total": 0}}

    for r in rows:
        emp = parse_employees(r.get("vs_employees", ""))
        if emp is None:
            continue
        if emp <= 100:
            bucket = "50-100"
        elif emp <= 500:
            bucket = "101-500"
        else:
            bucket = "501+"
        emp_buckets[bucket]["total"] += 1
        if r["_delivered"]:
            emp_buckets[bucket]["delivered"] += 1

    for b, v in emp_buckets.items():
        v["rate"] = v["delivered"] / v["total"] if v["total"] else 0

    emp_rates = [v["rate"] for v in emp_buckets.values() if v["total"] > 0]
    emp_min = min(emp_rates)
    emp_max = max(emp_rates)

    for b, v in emp_buckets.items():
        if v["total"] > 0:
            v["score"] = min_max_scale(v["rate"], emp_min, emp_max)
        else:
            v["score"] = SCORE_MIN

    # --- Print Report ---
    print("=" * 70)
    print("PER-SIC DELIVERY RATES (N >= {})".format(MIN_RECORDS))
    print("=" * 70)
    print(f"{'SIC':>6}  {'Del':>4}  {'Tot':>5}  {'Rate':>7}  {'Score':>6}  {'ICP':>5}")
    print("-" * 42)
    for sic in sorted(reliable, key=lambda s: reliable[s]["rate"], reverse=True):
        v = reliable[sic]
        in_icp = sic in icp_sics
        marker = "YES" if in_icp else ""
        if sic in {"4213", "4581", "4731"}:  # Recently added from HLM data
            marker = "NEW"
        print(f"  {sic:>4}  {v['delivered']:>4}  {v['total']:>5}  {v['rate']*100:>6.1f}%  {v['score']:>5}  {marker:>5}")

    print()
    print("Low-N SICs (< {} records, with deliveries):".format(MIN_RECORDS))
    for sic in sorted(low_n, key=lambda s: low_n[s]["delivered"], reverse=True):
        v = low_n[sic]
        print(f"  {sic}: {v['delivered']}/{v['total']}")

    print()
    print("=" * 70)
    print("EMPLOYEE SCALE")
    print("=" * 70)
    for b in ["50-100", "101-500", "501+"]:
        v = emp_buckets[b]
        print(f"  {b:>8}: {v['delivered']:>4}/{v['total']:>5} = {v['rate']*100:>5.1f}%  -> score {v['score']}")

    print()
    print("=" * 70)
    print("ICP EXPANSION CANDIDATES (3+ deliveries, not in current 22)")
    print("=" * 70)
    all_icp = icp_sics
    for sic in sorted(sic_stats, key=lambda s: sic_stats[s]["delivered"], reverse=True):
        v = sic_stats[sic]
        if sic not in all_icp and v["delivered"] >= 3:
            print(f"  {sic}: {v['delivered']}/{v['total']} = {v['delivered']/v['total']*100:.1f}%")

    # --- YAML Snippet ---
    print()
    print("=" * 70)
    print("YAML SNIPPET FOR config/icp.yaml")
    print("=" * 70)
    print()
    print("onsite_likelihood:")
    print("  sic_scores:")
    for sic in sorted(reliable, key=lambda s: int(s)):
        v = reliable[sic]
        print(f'    "{sic}": {v["score"]:>3}    # N={v["total"]}, rate={v["rate"]*100:.1f}%')
    print(f"  default: 40            # Unknown SICs (mean rate: {mean_rate*100:.1f}%)")

    print()
    print("employee_scale:")
    for b in ["50-100", "101-500", "501+"]:
        v = emp_buckets[b]
        if b == "50-100":
            print(f"  - min: 50\n    max: 100\n    score: {v['score']}")
        elif b == "101-500":
            print(f"  - min: 101\n    max: 500\n    score: {v['score']}")
        else:
            print(f"  - min: 501\n    max: 999999\n    score: {v['score']}")


if __name__ == "__main__":
    main()
