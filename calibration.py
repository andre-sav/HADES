"""
Calibration engine for outcome-driven lead scoring.

Queries historical_outcomes and lead_outcomes tables, computes per-SIC
and per-employee-bucket delivery rates, min-max scales to 20-100, and
compares against current icp.yaml weights.
"""

import re
from collections import defaultdict
from datetime import datetime
from pathlib import Path

import yaml

from utils import load_config

SCORE_MIN = 20
SCORE_MAX = 100
# Sample size thresholds for confidence
CONFIDENCE_HIGH = 100
CONFIDENCE_MEDIUM = 30


def min_max_scale(rate: float, min_rate: float, max_rate: float) -> int:
    """Scale a rate to SCORE_MIN..SCORE_MAX range."""
    if max_rate == min_rate:
        return round((SCORE_MIN + SCORE_MAX) / 2)
    scaled = SCORE_MIN + (rate - min_rate) / (max_rate - min_rate) * (SCORE_MAX - SCORE_MIN)
    return max(SCORE_MIN, min(SCORE_MAX, round(scaled)))


def compute_conversion_rates(db) -> dict:
    """Query both outcome tables and compute per-SIC and per-employee-bucket delivery rates.

    Returns:
        {
            "sic_scores": {sic: {"delivered": N, "total": N, "rate": float, "score": int}, ...},
            "employee_scores": {bucket: {"delivered": N, "total": N, "rate": float, "score": int}, ...},
            "overall": {"delivered": N, "total": N, "rate": float},
        }
    """
    rows = db.get_all_outcomes_for_calibration()

    if not rows:
        return {"sic_scores": {}, "employee_scores": {}, "overall": {"delivered": 0, "total": 0, "rate": 0.0}}

    # --- Per-SIC stats ---
    sic_stats = defaultdict(lambda: {"delivered": 0, "total": 0})
    for r in rows:
        sic = r.get("sic_code")
        if not sic:
            continue
        # Normalize to 4-digit
        m = re.match(r"(\d{4})", str(sic).strip())
        if not m:
            continue
        sic4 = m.group(1)
        sic_stats[sic4]["total"] += 1
        if r.get("outcome") == "delivery":
            sic_stats[sic4]["delivered"] += 1

    # Compute rates, filter to sufficient data (N >= 10)
    MIN_RECORDS = 10
    reliable_sics = {}
    for sic, v in sic_stats.items():
        if v["total"] >= MIN_RECORDS:
            v["rate"] = v["delivered"] / v["total"]
            reliable_sics[sic] = v

    # Min-max scale
    if reliable_sics:
        rates = [v["rate"] for v in reliable_sics.values()]
        min_rate, max_rate = min(rates), max(rates)
        for v in reliable_sics.values():
            v["score"] = min_max_scale(v["rate"], min_rate, max_rate)

    # --- Per-employee-bucket stats ---
    emp_buckets = {
        "50-100": {"delivered": 0, "total": 0},
        "101-500": {"delivered": 0, "total": 0},
        "501+": {"delivered": 0, "total": 0},
    }
    for r in rows:
        emp = r.get("employee_count")
        if emp is None:
            continue
        try:
            emp = int(emp)
        except (ValueError, TypeError):
            continue
        if emp <= 100:
            bucket = "50-100"
        elif emp <= 500:
            bucket = "101-500"
        else:
            bucket = "501+"
        emp_buckets[bucket]["total"] += 1
        if r.get("outcome") == "delivery":
            emp_buckets[bucket]["delivered"] += 1

    # Compute rates and scale
    emp_rates = [v["delivered"] / v["total"] for v in emp_buckets.values() if v["total"] > 0]
    if emp_rates:
        emp_min, emp_max = min(emp_rates), max(emp_rates)
        for v in emp_buckets.values():
            if v["total"] > 0:
                v["rate"] = v["delivered"] / v["total"]
                v["score"] = min_max_scale(v["rate"], emp_min, emp_max)
            else:
                v["rate"] = 0.0
                v["score"] = SCORE_MIN

    # --- Overall ---
    total_d = sum(1 for r in rows if r.get("outcome") == "delivery")
    total_n = len(rows)
    overall = {"delivered": total_d, "total": total_n, "rate": total_d / total_n if total_n else 0.0}

    return {
        "sic_scores": dict(reliable_sics),
        "employee_scores": dict(emp_buckets),
        "overall": overall,
    }


def _confidence_label(n: int) -> str:
    """Return confidence tier based on sample size."""
    if n >= CONFIDENCE_HIGH:
        return "High"
    elif n >= CONFIDENCE_MEDIUM:
        return "Medium"
    return "Low"


def compare_to_current(rates: dict, config_path: str | None = None) -> list[dict]:
    """Compare computed rates to current icp.yaml scores.

    Returns list of dicts:
        [{"dimension": "sic"|"employee", "key": str, "current": int,
          "suggested": int, "delta": int, "n": int, "rate": float,
          "confidence": str}, ...]
    """
    if config_path is None:
        config_path = str(Path(__file__).parent / "config" / "icp.yaml")

    with open(config_path) as f:
        config = yaml.safe_load(f)

    current_sic = config.get("onsite_likelihood", {}).get("sic_scores", {})
    current_emp = config.get("employee_scale", [])
    sic_default = config.get("onsite_likelihood", {}).get("default", 40)

    comparisons = []

    # SIC comparisons
    for sic, v in sorted(rates.get("sic_scores", {}).items()):
        current = current_sic.get(sic, sic_default)
        comparisons.append({
            "dimension": "sic",
            "key": sic,
            "current": current,
            "suggested": v["score"],
            "delta": v["score"] - current,
            "n": v["total"],
            "rate": v["rate"],
            "confidence": _confidence_label(v["total"]),
        })

    # Employee comparisons
    bucket_to_range = {"50-100": (50, 100), "101-500": (101, 500), "501+": (501, 999999)}
    for bucket, v in rates.get("employee_scores", {}).items():
        if v["total"] == 0:
            continue
        min_emp, max_emp = bucket_to_range[bucket]
        # Find matching current score
        current = SCORE_MIN
        for tier in current_emp:
            if tier.get("min") == min_emp and tier.get("max") == max_emp:
                current = tier.get("score", SCORE_MIN)
                break

        comparisons.append({
            "dimension": "employee",
            "key": bucket,
            "current": current,
            "suggested": v["score"],
            "delta": v["score"] - current,
            "n": v["total"],
            "rate": v["rate"],
            "confidence": _confidence_label(v["total"]),
        })

    return comparisons


def apply_calibration(selected_updates: list[dict], config_path: str | None = None,
                      db=None) -> None:
    """Write selected score updates to icp.yaml.

    Args:
        selected_updates: List of dicts from compare_to_current() that user approved
        config_path: Path to icp.yaml (default: config/icp.yaml)
        db: Optional TursoDatabase to record calibration timestamp
    """
    if config_path is None:
        config_path = str(Path(__file__).parent / "config" / "icp.yaml")

    with open(config_path) as f:
        config = yaml.safe_load(f)

    sic_scores = config.setdefault("onsite_likelihood", {}).setdefault("sic_scores", {})
    emp_scale = config.setdefault("employee_scale", [])

    for update in selected_updates:
        if update["dimension"] == "sic":
            sic_scores[update["key"]] = update["suggested"]
        elif update["dimension"] == "employee":
            bucket_to_range = {"50-100": (50, 100), "101-500": (101, 500), "501+": (501, 999999)}
            min_emp, max_emp = bucket_to_range[update["key"]]
            for tier in emp_scale:
                if tier.get("min") == min_emp and tier.get("max") == max_emp:
                    tier["score"] = update["suggested"]
                    break

    with open(config_path, "w") as f:
        yaml.dump(config, f, default_flow_style=False, sort_keys=False)

    # Record calibration timestamp
    if db:
        db.execute_write(
            """INSERT INTO sync_metadata (key, value, updated_at)
               VALUES (?, ?, CURRENT_TIMESTAMP)
               ON CONFLICT(key) DO UPDATE SET value = ?, updated_at = CURRENT_TIMESTAMP""",
            ("last_calibration", datetime.now().isoformat(), datetime.now().isoformat()),
        )
