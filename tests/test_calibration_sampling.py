"""Calibration sampling guards (HADES-7qi).

compute_conversion_rates applies a MIN_RECORDS=10 threshold to per-SIC rates
but applied NOTHING to the employee buckets. Any bucket with a single record
therefore produced a rate of 0.0 or 1.0, took the extreme of the min-max range,
and — because that range is computed from the bucket rates themselves —
rescaled the other two buckets around a number backed by one lead.

These scores are written into config/icp.yaml by the Score Calibration page and
drive 20% of the geography composite, so an under-sampled bucket silently
re-weights live scoring.
"""

from __future__ import annotations

from unittest.mock import MagicMock

from calibration import compute_conversion_rates


def _db_with(rows):
    db = MagicMock(name="db")
    db.get_all_outcomes_for_calibration.return_value = rows
    return db


def _row(sic="7011", employees=75, delivered=False):
    return {
        "sic_code": sic,
        "employee_count": employees,
        "outcome": "delivery" if delivered else "no_answer",
    }


def _rows_for_bucket(employees, n, delivered):
    return [_row(employees=employees, delivered=delivered) for _ in range(n)]


def test_a_single_record_bucket_does_not_earn_a_score():
    """One lucky lead must not become a 100."""
    rows = (
        _rows_for_bucket(75, 20, delivered=False)
        + _rows_for_bucket(75, 5, delivered=True)      # 50-100: 25 records
        + _rows_for_bucket(1000, 1, delivered=True)    # 501+ : ONE record, 100%
    )

    result = compute_conversion_rates(_db_with(rows))
    buckets = result["employee_scores"]

    assert buckets["501+"].get("score") is None, (
        "a one-record bucket was scored: " + repr(buckets["501+"])
    )


def test_an_undersampled_bucket_does_not_rescale_the_others():
    """The min-max range must be built only from reliable buckets — otherwise
    one record moves every other bucket's score."""
    reliable = (
        _rows_for_bucket(75, 15, delivered=True) + _rows_for_bucket(75, 5, delivered=False)
        + _rows_for_bucket(300, 5, delivered=True) + _rows_for_bucket(300, 15, delivered=False)
    )

    without = compute_conversion_rates(_db_with(reliable))["employee_scores"]
    with_noise = compute_conversion_rates(
        _db_with(reliable + _rows_for_bucket(1000, 1, delivered=True))
    )["employee_scores"]

    for bucket in ("50-100", "101-500"):
        assert without[bucket]["score"] == with_noise[bucket]["score"], (
            f"{bucket} moved from {without[bucket]['score']} to "
            f"{with_noise[bucket]['score']} because of one unrelated record"
        )


def test_a_well_sampled_bucket_is_still_scored():
    rows = (
        _rows_for_bucket(75, 15, delivered=True) + _rows_for_bucket(75, 5, delivered=False)
        + _rows_for_bucket(1000, 5, delivered=True) + _rows_for_bucket(1000, 15, delivered=False)
    )

    buckets = compute_conversion_rates(_db_with(rows))["employee_scores"]

    assert buckets["50-100"]["score"] is not None
    assert buckets["501+"]["score"] is not None
    assert buckets["50-100"]["score"] > buckets["501+"]["score"]


def test_bucket_counts_are_always_reported_even_when_unscored():
    """The page shows sample sizes; suppressing the score must not hide the
    evidence that a bucket is thin."""
    rows = _rows_for_bucket(1000, 3, delivered=True)

    buckets = compute_conversion_rates(_db_with(rows))["employee_scores"]

    assert buckets["501+"]["total"] == 3
    assert buckets["501+"]["delivered"] == 3


def test_no_outcomes_at_all_is_handled():
    result = compute_conversion_rates(_db_with([]))

    assert result["sic_scores"] == {}
    assert result["overall"]["total"] == 0
