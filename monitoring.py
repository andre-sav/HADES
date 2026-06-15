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
