"""Proactive ZoomInfo health detection (HADES-1d3).

The 2026-06-15 blank-enrichment incident was caught by the operator, not the
system. These pure evaluators let a scheduled job (or the pipeline) detect the
two failure shapes BEFORE blank rows reach a human:

  - credit/entitlement exhaustion  -> evaluate_usage(client.get_usage())
  - degraded (fieldless) enrichment -> evaluate_enrichment_batch(records)

Both return a verdict dict with a "severity" of "ok" | "warning" | "critical" |
"unknown" and a human-readable "message". "unknown" (e.g. an API error or empty
usage payload) is deliberately NOT "ok" — an unreadable health signal is itself
worth surfacing, never silently treated as healthy.
"""

from __future__ import annotations

from export import contact_has_core_data

# Limit types ZoomInfo reports; recordLimit is the one that maps to enrichment
# credits, but any breaching limit is worth an alert.
_USAGE_LIMIT_LABELS = {
    "requestLimit": "API Requests",
    "recordLimit": "Records",
    "uniqueIdLimit": "Unique IDs",
}


def evaluate_usage(usage: dict, *, warn_pct: float = 80.0, crit_pct: float = 95.0) -> dict:
    """Evaluate a ZoomInfo get_usage() payload against warn/critical thresholds.

    Returns {"severity", "breaches": [...], "message"}. Severity is driven by the
    most-constrained limit. An error/empty payload is "unknown", never "ok".
    """
    if not isinstance(usage, dict) or usage.get("error"):
        detail = usage.get("error") if isinstance(usage, dict) else "no usage payload"
        return {
            "severity": "unknown",
            "breaches": [],
            "message": f"Could not read ZoomInfo usage ({detail}) — health unknown.",
        }

    rows = usage.get("usage") or []
    limits = []
    for item in rows:
        limit = item.get("totalLimit", 0) or 0
        if limit <= 0:
            continue  # 0 = no limit / unknown; can't compute a pct, don't false-alarm
        used = item.get("currentUsage", 0) or 0
        lt = item.get("limitType", "")
        limits.append({
            "limit_type": lt,
            "label": _USAGE_LIMIT_LABELS.get(lt, lt),
            "used": used,
            "limit": limit,
            "remaining": item.get("usageRemaining", limit - used),
            "pct": used / limit * 100.0,
        })

    if not limits:
        return {
            "severity": "unknown",
            "breaches": [],
            "message": "ZoomInfo usage payload had no measurable limits — health unknown.",
        }

    severity = "ok"
    breaches = []
    for lim in limits:
        if lim["pct"] >= crit_pct:
            lim_sev = "critical"
        elif lim["pct"] >= warn_pct:
            lim_sev = "warning"
        else:
            continue
        breaches.append(lim)
        if lim_sev == "critical":
            severity = "critical"
        elif severity != "critical":
            severity = "warning"

    if severity == "ok":
        worst = max(limits, key=lambda x: x["pct"])
        message = f"ZoomInfo usage healthy (most-used: {worst['label']} at {worst['pct']:.0f}%)."
    else:
        worst = max(breaches, key=lambda x: x["pct"])
        message = (
            f"ZoomInfo {severity.upper()}: {worst['label']} at {worst['pct']:.0f}% "
            f"({worst['used']:,}/{worst['limit']:,}, {worst['remaining']:,} left). "
            "Enrichment may return fieldless records when credits are exhausted."
        )

    return {"severity": severity, "breaches": breaches, "message": message}


def evaluate_enrichment_batch(records: list[dict], *, empty_fraction_threshold: float = 0.5) -> dict:
    """Evaluate a batch of enriched contacts for the fieldless-record signature.

    Returns {"severity", "total", "empty", "fraction", "message"}. All-empty is
    "critical" (the incident shape); >= threshold empty is "warning".
    """
    total = len(records)
    if total == 0:
        return {"severity": "ok", "total": 0, "empty": 0, "fraction": 0.0,
                "message": "No enriched records to evaluate."}

    empty = sum(1 for r in records if not contact_has_core_data(r))
    fraction = empty / total

    if empty == total:
        severity = "critical"
    elif fraction >= empty_fraction_threshold:
        severity = "warning"
    else:
        severity = "ok"

    if severity == "ok":
        message = f"Enrichment healthy: {total - empty}/{total} records carry contact data."
    else:
        message = (
            f"Enrichment {severity.upper()}: {empty}/{total} records came back with no "
            "contact data — likely a ZoomInfo credit/entitlement issue."
        )

    return {"severity": severity, "total": total, "empty": empty, "fraction": fraction,
            "message": message}


# ---------------------------------------------------------------------------
# Data-drift anomaly detection (HADES-e7j)
#
# Early warning for the slow failure modes nothing else catches: an operator
# mass-delete, a Zoho sync degrading silently, a yield collapse after a filter
# change. All pure — scripts/data_anomaly_check.py supplies the DB reads.
# ---------------------------------------------------------------------------

_SEVERITY_RANK = {"ok": 0, "warning": 1, "unknown": 2, "critical": 3}

def evaluate_row_count_drop(table: str, current: int, baseline: int | None,
                            *, threshold_pct: float = 5.0) -> dict:
    """Flag a table shrinking since the last baseline.

    No baseline (first ever run) is "ok" — crying wolf on day one would
    train the operator to ignore the channel.
    """
    if baseline is None or baseline <= 0:
        return {"severity": "ok", "message": f"{table}: {current} rows (no baseline yet)."}

    dropped = baseline - current
    if dropped <= 0:
        return {"severity": "ok", "message": f"{table}: {current} rows (was {baseline})."}

    pct = dropped / baseline * 100.0
    if current == 0:
        severity = "critical"
    elif pct >= threshold_pct:
        severity = "warning"
    else:
        severity = "ok"

    if severity == "ok":
        return {"severity": "ok", "message": f"{table}: {current} rows (was {baseline})."}
    return {
        "severity": severity,
        "message": (f"{table}: row count fell {dropped} ({pct:.1f}%) — "
                    f"{baseline} -> {current}."),
    }


def evaluate_linkage_drop(current_fraction: float, baseline_fraction: float | None,
                          *, threshold_pct: float = 5.0, label: str = "Zoho-linked operators") -> dict:
    """Flag a linked/synced percentage regressing (silent sync degradation)."""
    if baseline_fraction is None:
        return {"severity": "ok",
                "message": f"{label}: {current_fraction:.0%} (no baseline yet)."}

    drop_points = (baseline_fraction - current_fraction) * 100.0
    if drop_points < threshold_pct:
        return {"severity": "ok",
                "message": f"{label}: {current_fraction:.0%} (was {baseline_fraction:.0%})."}
    return {
        "severity": "warning",
        "message": (f"{label}: fell {drop_points:.1f} points — "
                    f"{baseline_fraction:.0%} -> {current_fraction:.0%}."),
    }


def evaluate_export_volume(measured_count: int, history: list[int],
                           *, min_samples: int = 10, sigmas: float = 2.0) -> dict:
    """Flag a completed day's export volume collapsing versus history.

    Callers must pass a COMPLETED day (see data_anomaly_check): the daily
    job runs at 07:00 UTC, so the in-progress day is always empty and would
    alarm every morning (N2-04).

    Uses a 2σ floor, with guards: too few samples can't support the claim,
    a zero-variance history would otherwise fire on any dip, and the floor
    is clamped above zero so a high-variance history can't disable it.
    """
    import statistics

    if len(history) < min_samples:
        return {"severity": "ok",
                "message": f"Exports (last completed day): {measured_count} "
                           "— history too short to judge."}

    mean = statistics.fmean(history)
    stdev = statistics.pstdev(history)
    floor = mean - sigmas * stdev if stdev > 0 else mean * 0.5
    # Clamp above zero (N2-14): a history with genuine zero-volume days makes
    # stdev exceed mean/sigmas, driving the floor negative — every possible
    # count then clears it and detection is silently disabled. A floor at or
    # below zero means "only an actual zero is anomalous".
    if floor <= 0:
        floor = 0.5

    if measured_count >= floor:
        return {"severity": "ok",
                "message": (f"Exports (last completed day): {measured_count} "
                            f"(30-day mean {mean:.1f}).")}

    severity = "critical" if measured_count == 0 and mean > 0 else "warning"
    return {
        "severity": severity,
        "message": (f"Exports (last completed day): {measured_count}, far below "
                    f"the 30-day mean {mean:.1f} (floor {floor:.1f})."),
    }


def evaluate_mutation_burst(mutations: list[dict], *, threshold: int = 100,
                            window_seconds: int = 60) -> dict:
    """Flag a burst of DELETEs in a short window (mass-delete signature).

    Inserts are excluded: a VanillaSoft import legitimately writes many rows
    at once. Unparseable timestamps are skipped rather than crashing the check.
    """
    from datetime import datetime

    deletes = []
    for m in mutations:
        if m.get("op") != "delete":
            continue
        ts = m.get("ts")
        if not ts:
            continue
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S"):
            try:
                deletes.append(datetime.strptime(str(ts)[:19], fmt))
                break
            except ValueError:
                continue

    if len(deletes) < threshold:
        return {"severity": "ok",
                "message": f"Mutation log: {len(deletes)} delete(s) in the window."}

    deletes.sort()
    # Sliding window: any `threshold` deletes inside `window_seconds`.
    for i in range(len(deletes) - threshold + 1):
        span = (deletes[i + threshold - 1] - deletes[i]).total_seconds()
        if span <= window_seconds:
            return {
                "severity": "critical",
                "message": (f"Mutation log: {threshold}+ delete operations within "
                            f"{window_seconds}s — possible mass delete."),
            }
    return {"severity": "ok",
            "message": f"Mutation log: {len(deletes)} delete(s), none bursty."}


def summarise_verdicts(verdicts: list[dict]) -> dict:
    """Combine verdicts into one, worst-severity-wins.

    The message lists only the non-ok lines — an alert should say what is
    wrong, not recite everything that is fine.
    """
    if not verdicts:
        return {"severity": "ok", "message": "No checks ran.", "verdicts": []}

    worst = max(verdicts, key=lambda v: _SEVERITY_RANK.get(v.get("severity", "ok"), 0))
    severity = worst.get("severity", "ok")
    problems = [v["message"] for v in verdicts if v.get("severity") != "ok"]
    message = "\n".join(problems) if problems else "All data-health checks passed."
    return {"severity": severity, "message": message, "verdicts": verdicts}
