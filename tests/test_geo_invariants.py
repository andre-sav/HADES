"""Runtime output invariants for Geography search (HADES-av6, insurance M1).

The session-51 centroid corruption — 452 SoCal ZIPs collapsed onto Torrance's
coordinates — ran silently for months because nothing checked the search's
OUTPUT, only its inputs. These evaluators are the check.

A note on what makes an invariant worth having: it must have an oracle
INDEPENDENT of the computation it audits. Re-running haversine over the same
centroid table that produced the results is self-referential — collapsed ZIPs
report distance 0.0 and sail through. So the radius invariant leans on two
independent signals as well: coordinate-sharing density (the actual signature
of a collapse) and ``utils.get_state_from_zip``, which derives state from the
ZIP prefix rather than from the CSV under audit.
"""

from __future__ import annotations

import logging

import pytest

from geo import haversine_distance
from monitoring import evaluate_lead_states, evaluate_radius_invariants


# Dallas, TX — the centre used across these fixtures.
CENTER_ZIP = "75201"
CENTER_LAT, CENTER_LNG = 32.7815, -96.7955


def _row(zip_code: str, lat: float, lng: float, state: str) -> dict:
    """Build a result row with a truthful distance, as get_zips_in_radius does."""
    return {
        "zip": zip_code,
        "state": state,
        "lat": lat,
        "lng": lng,
        "distance_miles": round(
            haversine_distance(CENTER_LAT, CENTER_LNG, lat, lng), 2
        ),
    }


@pytest.fixture
def clean_results() -> list[dict]:
    """Four genuine Dallas-area ZIPs, all inside a 15-mile radius."""
    return [
        _row(CENTER_ZIP, CENTER_LAT, CENTER_LNG, "TX"),
        _row("75204", 32.8010, -96.7870, "TX"),
        _row("75219", 32.8110, -96.8100, "TX"),
        _row("75207", 32.7860, -96.8300, "TX"),
    ]


# --------------------------------------------------------------------------
# evaluate_radius_invariants
# --------------------------------------------------------------------------

def test_clean_radius_results_are_ok(clean_results):
    verdict = evaluate_radius_invariants(CENTER_ZIP, 15.0, clean_results)

    assert verdict["severity"] == "ok", verdict
    assert verdict["violations"] == []


def test_empty_results_are_ok():
    """An unknown centre ZIP legitimately returns nothing — not an anomaly."""
    verdict = evaluate_radius_invariants("00000", 15.0, [])

    assert verdict["severity"] == "ok", verdict


def test_zip_outside_radius_is_flagged(clean_results):
    """A row beyond the requested radius means the distance filter failed."""
    clean_results.append(_row("77002", 29.7590, -95.3620, "TX"))  # Houston, ~225mi

    verdict = evaluate_radius_invariants(CENTER_ZIP, 15.0, clean_results)

    assert verdict["severity"] != "ok"
    assert any("77002" in v for v in verdict["violations"]), verdict


def test_lying_distance_field_is_flagged(clean_results):
    """distance_miles disagreeing with the coordinates means a units or
    filter bug upstream — the row claims to be near, its coordinates are not."""
    clean_results[1]["distance_miles"] = 0.5
    clean_results[1]["lat"] = 35.5  # ~190 miles north, still claiming 0.5mi

    verdict = evaluate_radius_invariants(CENTER_ZIP, 15.0, clean_results)

    assert verdict["severity"] != "ok"
    assert any("75204" in v for v in verdict["violations"]), verdict


def test_centroid_collapse_is_critical(clean_results):
    """The session-51 signature: many distinct ZIPs sharing one coordinate.

    Every collapsed ZIP reports distance 0.0, so the distance check alone
    passes — this is the oracle that actually catches the corruption.
    """
    for zip_code in ("90501", "90502", "90503", "90504", "90505"):
        clean_results.append(_row(zip_code, CENTER_LAT, CENTER_LNG, "CA"))

    verdict = evaluate_radius_invariants(CENTER_ZIP, 15.0, clean_results)

    assert verdict["severity"] == "critical", verdict
    assert any("share" in v.lower() for v in verdict["violations"]), verdict


def test_collapse_check_tolerates_legitimate_coordinate_sharing(clean_results):
    """A couple of ZIPs at one point is normal (PO-box ZIPs); don't cry wolf."""
    clean_results.append(_row("75202", CENTER_LAT, CENTER_LNG, "TX"))

    verdict = evaluate_radius_invariants(CENTER_ZIP, 15.0, clean_results)

    assert verdict["severity"] == "ok", verdict


def test_state_disagreeing_with_zip_prefix_is_flagged(clean_results):
    """Independent oracle: the ZIP prefix implies the state, not the CSV."""
    clean_results[2]["state"] = "CA"  # 75219 is unambiguously TX

    verdict = evaluate_radius_invariants(CENTER_ZIP, 15.0, clean_results)

    assert verdict["severity"] != "ok"
    assert any("75219" in v for v in verdict["violations"]), verdict


def test_missing_center_zip_is_flagged(clean_results):
    """get_zips_in_radius always returns the centre at 0.0 miles when found."""
    verdict = evaluate_radius_invariants("75204", 15.0, [clean_results[0]])

    assert verdict["severity"] != "ok"
    assert any("75204" in v for v in verdict["violations"]), verdict


def test_violation_list_is_capped_for_readability():
    """A wholesale corruption must not emit thousands of log lines."""
    rows = [_row(CENTER_ZIP, CENTER_LAT, CENTER_LNG, "TX")]
    for i in range(200):
        rows.append(_row(f"9{i:04d}", 29.7590, -95.3620, "TX"))  # all far away

    verdict = evaluate_radius_invariants(CENTER_ZIP, 15.0, rows)

    assert verdict["severity"] != "ok"
    assert len(verdict["violations"]) <= 12, len(verdict["violations"])
    assert "more" in verdict["message"] or any(
        "more" in v for v in verdict["violations"]
    ), verdict


# --------------------------------------------------------------------------
# End-to-end: the session-51 incident, replayed through the real search
# --------------------------------------------------------------------------

def test_session51_collapse_is_caught_through_the_real_search(monkeypatch):
    """Replay the incident: SoCal ZIPs collapsed onto one coordinate.

    This drives the genuine get_zips_in_radius() over a corrupted centroid
    table, which is the only way to prove the claim the bead rests on — that
    the invariant would have failed on the first search after the bad deploy
    instead of running silently for months.

    It also demonstrates why the distance check alone is not enough: every
    collapsed ZIP reports 0.0 miles and is comfortably 'inside' the radius.
    """
    import geo

    torrance_lat, torrance_lng = 33.8358, -118.3406
    corrupted = {
        "90501": (torrance_lat, torrance_lng, "CA"),
        # 90210 Beverly Hills, 92101 San Diego, 93001 Ventura, 91711 Claremont
        # — all distinct places, all collapsed onto Torrance's coordinate.
        "90210": (torrance_lat, torrance_lng, "CA"),
        "92101": (torrance_lat, torrance_lng, "CA"),
        "93001": (torrance_lat, torrance_lng, "CA"),
        "91711": (torrance_lat, torrance_lng, "CA"),
    }
    monkeypatch.setattr(geo, "load_zip_centroids", lambda: corrupted)

    results = geo.get_zips_in_radius("90501", 15.0)

    # The corruption is invisible to a distance check: every ZIP reports 0.0mi.
    assert results, "sanity: the corrupted search should still return rows"
    assert all(r["distance_miles"] == 0.0 for r in results)

    verdict = evaluate_radius_invariants("90501", 15.0, results)

    assert verdict["severity"] == "critical", verdict
    assert any("share coordinate" in v for v in verdict["violations"]), verdict


@pytest.mark.parametrize(
    "center",
    [
        "75201",  # Dallas
        "20147",  # Ashburn VA
        "90001",  # Los Angeles
        "10001",  # New York
        "75501",  # Texarkana — genuinely spans the TX/AR line
        "96813",  # Honolulu
        "99501",  # Anchorage
        "02108",  # Boston — 4-digit-ZIP state
    ],
)
def test_real_centroid_data_produces_no_violations(center):
    """The shipped dataset must be quiet, or the banner trains operators to
    ignore it. Doubles as a CI gate on data/zip_centroids.csv itself: a future
    corrupted or reverted CSV fails here instead of in production.
    """
    from geo import get_zips_in_radius

    results = get_zips_in_radius(center, 15.0)
    assert results, f"{center} returned nothing — is it missing from the dataset?"

    verdict = evaluate_radius_invariants(center, 15.0, results)

    assert verdict["severity"] == "ok", verdict


# --------------------------------------------------------------------------
# evaluate_lead_states
# --------------------------------------------------------------------------

def test_leads_all_in_expected_states_are_ok():
    leads = [
        {"company": {"name": "Acme"}, "state": "TX"},
        {"company": {"name": "Globex"}, "state": "AR"},
    ]

    verdict = evaluate_lead_states(leads, ["TX", "AR"])

    assert verdict["severity"] == "ok", verdict


def test_lead_outside_expected_states_is_flagged():
    leads = [
        {"company": {"name": "Acme"}, "state": "TX"},
        {"company": {"name": "Wrongco"}, "state": "NY"},
    ]

    verdict = evaluate_lead_states(leads, ["TX", "AR"])

    assert verdict["severity"] != "ok"
    assert any("Wrongco" in v or "NY" in v for v in verdict["violations"]), verdict


def test_lead_state_comparison_is_case_and_space_insensitive():
    leads = [{"company": {"name": "Acme"}, "state": " tx "}]

    verdict = evaluate_lead_states(leads, ["TX"])

    assert verdict["severity"] == "ok", verdict


def test_blank_lead_state_is_not_a_violation():
    """Messy data is expected; a blank state is the enrichment-quality check's
    job (evaluate_enrichment_batch), not this one's."""
    leads = [
        {"company": {"name": "Acme"}, "state": "TX"},
        {"company": {"name": "Blankco"}, "state": ""},
        {"company": {"name": "Noneco"}, "state": None},
    ]

    verdict = evaluate_lead_states(leads, ["TX"])

    assert verdict["severity"] == "ok", verdict


def test_lead_state_falls_back_to_company_state():
    """ZoomInfo populates state at the contact OR the company level."""
    leads = [{"company": {"name": "Acme", "state": "NY"}}]

    verdict = evaluate_lead_states(leads, ["TX"])

    assert verdict["severity"] != "ok", verdict


def test_company_as_list_does_not_crash():
    """Known messy shape: 'company' arrives as a list instead of a dict."""
    leads = [{"company": [], "state": "TX"}]

    verdict = evaluate_lead_states(leads, ["TX"])

    assert verdict["severity"] == "ok", verdict


def test_no_expected_states_is_ok():
    """Manual-ZIP mode may not derive states; nothing to judge against."""
    verdict = evaluate_lead_states([{"state": "NY"}], [])

    assert verdict["severity"] == "ok", verdict


# --------------------------------------------------------------------------
# surface_data_anomaly — the shared adapter every call site uses
# --------------------------------------------------------------------------

def test_ok_verdict_surfaces_nothing(caplog):
    from utils import surface_data_anomaly

    state: dict = {}
    with caplog.at_level(logging.ERROR):
        surfaced = surface_data_anomaly(
            {"severity": "ok", "message": "fine", "violations": []},
            context="radius search",
            store=state,
        )

    assert surfaced is False
    assert state == {}
    assert caplog.records == []


def test_violation_logs_and_sets_the_banner_flag(caplog):
    from utils import surface_data_anomaly

    state: dict = {}
    verdict = {
        "severity": "critical",
        "message": "5 ZIPs share one coordinate",
        "violations": ["90501, 90502 share (32.78, -96.79)"],
    }
    with caplog.at_level(logging.ERROR):
        surfaced = surface_data_anomaly(verdict, context="radius search", store=state)

    assert surfaced is True
    assert state.get("data_anomaly")
    # The banner text the operator sees must point at the logs.
    assert "log" in state["data_anomaly"].lower()
    # The log line must carry the detail the banner deliberately omits.
    logged = "\n".join(r.getMessage() for r in caplog.records)
    assert "radius search" in logged
    assert "90501" in logged


def test_repeat_surfacing_logs_once_per_store(caplog):
    """Streamlit reruns the page on every keystroke. A persistent anomaly must
    not emit an identical log line — and Sentry event — on each one.
    """
    from utils import surface_data_anomaly

    state: dict = {}
    verdict = {"severity": "warning", "message": "same every time", "violations": []}
    with caplog.at_level(logging.ERROR):
        first = surface_data_anomaly(verdict, context="radius search", store=state)
        second = surface_data_anomaly(verdict, context="radius search", store=state)

    assert first is True
    assert second is True, "the banner must stay up even when the log is suppressed"
    assert len(caplog.records) == 1, [r.getMessage() for r in caplog.records]
    assert state.get("data_anomaly")


def test_a_different_anomaly_still_logs(caplog):
    """Deduplication must key on the anomaly, not merely on having seen one."""
    from utils import surface_data_anomaly

    state: dict = {}
    with caplog.at_level(logging.ERROR):
        surface_data_anomaly(
            {"severity": "warning", "message": "first", "violations": []},
            context="radius search", store=state,
        )
        surface_data_anomaly(
            {"severity": "warning", "message": "second", "violations": []},
            context="radius search", store=state,
        )

    assert len(caplog.records) == 2, [r.getMessage() for r in caplog.records]


def test_surfacing_never_raises_without_a_store():
    """Headless callers (expand_search) have no session_state; still must log."""
    from utils import surface_data_anomaly

    assert surface_data_anomaly(
        {"severity": "warning", "message": "m", "violations": []},
        context="expansion",
        store=None,
    ) is True
