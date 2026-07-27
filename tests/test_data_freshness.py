"""Data-source freshness badges (HADES-1w2, insurance M8).

Measured against production on 2026-07-27: every one of the 3,041 operators was
last synced from Zoho on 2026-02-18 — **159 days** stale — because the sync cron
has been failing on missing ZOHO_* secrets (HADES-jdi). Operator names, phones,
emails, ZIPs and websites ride on every exported lead, and the Geography page's
own caption said "synced from Zoho CRM" with no indication of when.

The daily red workflow run IS the fail-loud path working correctly. The gap is
where the signal lands: a GitHub Actions email, not the dropdown the operator is
choosing from. These badges close that loop.

Thresholds are deliberately generous — the sync is daily, so 1 day is normal and
7 days is the point where a human should act.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from monitoring import evaluate_data_freshness


NOW = datetime(2026, 7, 27, 12, 0, tzinfo=timezone.utc)


def _ago(**kw) -> str:
    return (NOW - timedelta(**kw)).isoformat()


def test_recent_sync_is_ok():
    verdict = evaluate_data_freshness(_ago(hours=3), now=NOW, label="Zoho operators")

    assert verdict["severity"] == "ok", verdict
    assert verdict["age_days"] == 0


def test_a_few_days_stale_is_a_warning():
    verdict = evaluate_data_freshness(_ago(days=3), now=NOW, label="Zoho operators")

    assert verdict["severity"] == "warning", verdict
    assert "3 days" in verdict["message"], verdict


def test_the_real_production_staleness_is_critical():
    """The actual measured state on 2026-07-27 — this must read as critical,
    not as a soft warning the operator can scroll past.

    158 rather than 159 because NOW is pinned to 12:00 UTC while the live
    measurement ran at ~19:00; the stamp is 158d 19h old at this instant. Age
    floors to whole days, so the badge never overstates staleness.
    """
    verdict = evaluate_data_freshness(
        "2026-02-18T17:18:51.147528+00:00", now=NOW, label="Zoho operators"
    )

    assert verdict["severity"] == "critical", verdict
    assert verdict["age_days"] == 158, verdict
    assert "158 days" in verdict["message"], verdict


def test_never_synced_is_unknown_not_ok():
    """Absent is not fresh. An unreadable signal is never 'ok' — the
    monitoring.py convention."""
    verdict = evaluate_data_freshness(None, now=NOW, label="Zoho operators")

    assert verdict["severity"] == "unknown", verdict
    assert "never" in verdict["message"].lower(), verdict


def test_unparseable_timestamp_is_unknown():
    verdict = evaluate_data_freshness("whenever", now=NOW, label="Zoho operators")

    assert verdict["severity"] == "unknown", verdict


def test_thresholds_are_tunable():
    stamp = _ago(days=3)

    assert evaluate_data_freshness(stamp, now=NOW, warn_days=5)["severity"] == "ok"
    assert evaluate_data_freshness(stamp, now=NOW, critical_days=2)["severity"] == "critical"


def test_naive_timestamps_are_treated_as_utc():
    """SQLite CURRENT_TIMESTAMP text has no offset; it must not crash or be
    read as local time."""
    verdict = evaluate_data_freshness("2026-07-27 09:00:00", now=NOW)

    assert verdict["severity"] == "ok", verdict
    assert verdict["age_days"] == 0


def test_a_future_timestamp_does_not_read_as_ancient():
    """Clock skew between Turso and the app must not flip the badge to
    critical via a negative age."""
    verdict = evaluate_data_freshness(_ago(hours=-2), now=NOW)

    assert verdict["severity"] == "ok", verdict
    assert verdict["age_days"] == 0


def test_message_names_the_source():
    verdict = evaluate_data_freshness(_ago(days=10), now=NOW, label="Centroid data")

    assert "Centroid data" in verdict["message"], verdict


@pytest.mark.parametrize(
    "stamp",
    [
        "2026-07-27T09:00:00+00:00",
        "2026-07-27T09:00:00Z",
        "2026-07-27 09:00:00",
        "2026-07-27T09:00:00.123456+00:00",
    ],
)
def test_every_timestamp_shape_the_codebase_writes_is_parsed(stamp):
    """utc_now_str() writes space-separated, Zoho writes offset-aware ISO, and
    SQLite writes bare CURRENT_TIMESTAMP text. All three reach this."""
    assert evaluate_data_freshness(stamp, now=NOW)["severity"] == "ok"


def test_scheduled_job_freshness_parses_the_same_shapes():
    """Both freshness evaluators share one parser, so a timestamp format that
    works for one cannot silently fail for the other."""
    from monitoring import evaluate_scheduled_job_freshness

    for stamp in ("2026-07-27T09:00:00Z", "2026-07-27 09:00:00"):
        assert evaluate_scheduled_job_freshness(stamp, now=NOW)["severity"] == "ok", stamp
