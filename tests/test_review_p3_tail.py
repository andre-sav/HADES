"""Data-correctness cluster from the 2026-07-11 accuracy/efficiency review (HADES-7qi).

Four findings that corrupt lead data or silently degrade matching. All are the
"messy external data" class CLAUDE.md calls out, and none need a live API:

  1. normalize_zip corrupts 8-digit zero-dropped ZIP+4 into a DIFFERENT valid
     ZIP in another state.
  2. HTML entities are never decoded, so dedup misses real duplicates and the
     CRM receives double-escaped text.
  3. A string signalScore is silently ignored, collapsing intent scoring back
     to the coarse categorical band.
  4. _execute_multi_row_insert truncates everything after the VALUES clause,
     so an upsert would silently lose its ON CONFLICT.
"""

from __future__ import annotations

from datetime import datetime, timezone

from unittest.mock import MagicMock

import pytest

from dedup import normalize_company_name
from scoring import score_intent_leads
from utils import normalize_zip


# --------------------------------------------------------------------------
# 1. normalize_zip — 8-digit zero-dropped ZIP+4
# --------------------------------------------------------------------------

def test_eight_digit_zip_is_read_as_zero_dropped_zip_plus_four():
    """"10011234" is Agawam MA 01001-1234 with the leading zero eaten by Excel.

    Truncating to the first five gives 10011 — Manhattan. That is not a
    formatting nit: it puts the lead in the wrong state, and geo/state
    derivation follows it downstream.
    """
    assert normalize_zip("10011234") == "01001"


def test_nine_digit_zip_is_still_plain_zip_plus_four():
    """9 digits is an unambiguous ZIP+4 and must keep its first five."""
    assert normalize_zip("100111234") == "10011"


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("75201", "75201"),
        ("75201-1234", "75201"),
        ("75201 1234", "75201"),
        (75201, "75201"),
        (1001, "01001"),        # 4-digit MA ZIP, leading zero dropped
        ("  75201  ", "75201"),
        ("=\"75201\"", "75201"),  # Excel formatting
        (None, None),
        ("", None),
    ],
)
def test_existing_normalize_zip_behaviour_is_unchanged(raw, expected):
    assert normalize_zip(raw) == expected


# --------------------------------------------------------------------------
# 2. HTML entities
# --------------------------------------------------------------------------

def test_html_entities_do_not_break_company_matching():
    """ZoomInfo returns HTML-escaped names. Undecoded, "&amp;" survives
    punctuation-stripping as the token "amp", which drags the fuzzy ratio under
    the 85 threshold and the duplicate is pushed as a new lead.
    """
    assert normalize_company_name("Smith &amp; Sons") == normalize_company_name("Smith & Sons")


def test_common_entities_are_decoded():
    assert normalize_company_name("Tom&#39;s Diner") == normalize_company_name("Tom's Diner")
    assert normalize_company_name("A &lt;B&gt; C") == normalize_company_name("A <B> C")


def test_export_does_not_double_escape_into_the_crm():
    """Raw "&amp;" reaching VanillaSoft renders as "&amp;amp;" downstream."""
    from export import build_vanillasoft_row

    row = build_vanillasoft_row({"companyName": "Smith &amp; Sons"})

    assert "&amp;" not in row["Company"], row["Company"]
    assert row["Company"] == "Smith & Sons"


# --------------------------------------------------------------------------
# 3. String signalScore
# --------------------------------------------------------------------------

def _intent_lead(**over):
    lead = {
        "companyName": "Acme",
        "intentStrength": "Low",   # categorical fallback scores LOW
        "sicCode": "7011",
        # A missing date is treated as 999 days old and excluded as stale, so
        # the fixture needs a fresh one or score_intent_leads returns nothing.
        "intentDate": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    lead.update(over)
    return lead


def test_string_signal_score_is_used_not_silently_ignored():
    """ZoomInfo sends numerics as strings (documented in CLAUDE.md). An
    isinstance check on (int, float) drops them to the coarse band, so every
    lead in a batch collapses to the same signal score and differentiation —
    the entire point of signalScore — is lost.
    """
    high = score_intent_leads([_intent_lead(signalScore="95")])[0]
    low = score_intent_leads([_intent_lead(signalScore="10")])[0]

    assert high["_score"] > low["_score"], (high["_score"], low["_score"])


def test_percent_suffixed_signal_score_is_parsed():
    """"95%" is a documented ZoomInfo wire shape."""
    with_pct = score_intent_leads([_intent_lead(signalScore="95%")])[0]
    plain = score_intent_leads([_intent_lead(signalScore="95")])[0]

    assert with_pct["_score"] == plain["_score"]


def test_unparseable_signal_score_falls_back_to_the_categorical_band():
    """Messy data must degrade to the old behaviour, not crash or score 0."""
    for junk in ("", None, "n/a", "junk"):
        scored = score_intent_leads([_intent_lead(signalScore=junk)])[0]
        assert scored["_score"] >= 0

    weak = score_intent_leads([_intent_lead(signalScore="junk", intentStrength="Low")])[0]
    strong = score_intent_leads([_intent_lead(signalScore="junk", intentStrength="High")])[0]
    assert strong["_score"] > weak["_score"]


# --------------------------------------------------------------------------
# 4. Multi-row INSERT must not silently drop a trailing clause
# --------------------------------------------------------------------------

def _core_with_fake_connection():
    from db import TursoDatabase

    db = TursoDatabase.__new__(TursoDatabase)
    import threading
    db._lock = threading.RLock()
    db._in_transaction = False
    db._conn = MagicMock(name="connection")
    return db


def test_upsert_suffix_is_not_silently_discarded():
    """`INSERT ... VALUES (?) ON CONFLICT ... DO UPDATE` collapsed to a plain
    INSERT loses its conflict handling entirely — and says nothing.

    No caller writes one today, so this is latent; it is exactly the trap the
    next person to write an upsert would fall into.
    """
    db = _core_with_fake_connection()
    query = (
        "INSERT INTO t (a, b) VALUES (?, ?) "
        "ON CONFLICT(a) DO UPDATE SET b = excluded.b"
    )

    db.execute_many(query, [(1, "x"), (2, "y")])

    executed = " ".join(
        str(call.args[0]) for call in db._conn.execute.call_args_list
    ).upper()
    assert "ON CONFLICT" in executed, (
        "the ON CONFLICT clause was dropped:\n" + executed
    )


def test_plain_multi_row_insert_still_batches_into_one_round_trip():
    """The optimisation must survive the fix — that is the whole point of it."""
    db = _core_with_fake_connection()

    db.execute_many("INSERT INTO t (a, b) VALUES (?, ?)", [(1, "x"), (2, "y")])

    assert db._conn.execute.call_count == 1, db._conn.execute.call_args_list
    sql = db._conn.execute.call_args_list[0].args[0]
    assert sql.count("(?, ?)") == 2, sql


# --------------------------------------------------------------------------
# 5. Intent UI spent credits before cross-session dedup
# --------------------------------------------------------------------------

def _lookup_with(name=None, company_id=None):
    from dedup import normalize_company_name
    lookup = {"by_id": {}, "by_name": {}, "vs_by_name": {}, "vs_by_phone": {}}
    if name:
        lookup["by_name"][normalize_company_name(name)] = {
            "company_name": name, "exported_at": "2026-07-01", "workflow_type": "intent",
        }
    if company_id:
        lookup["by_id"][str(company_id)] = {
            "company_name": "x", "exported_at": "2026-07-01", "workflow_type": "intent",
        }
    return lookup


def test_previously_exported_company_is_dropped_before_enrichment():
    """The headless pipeline filters before enriching; the UI filtered only at
    export time, so every already-exported company was enriched — real credits
    spent on leads that were then discarded.
    """
    from export_dedup import partition_companies_for_enrichment

    companies = {
        "hid_a": {"companyName": "Acme Vending"},
        "hid_b": {"companyName": "Fresh Co"},
    }

    keep, skip = partition_companies_for_enrichment(
        companies, cached_ids={}, lookup=_lookup_with(name="Acme Vending")
    )

    assert set(keep) == {"hid_b"}, keep
    assert len(skip) == 1 and skip[0]["companyName"] == "Acme Vending"


def test_cached_numeric_id_is_used_for_matching_when_available():
    """Companies whose numeric ID is already cached can match by ID, which is
    stronger than the name fallback."""
    from export_dedup import partition_companies_for_enrichment

    keep, skip = partition_companies_for_enrichment(
        {"hid_a": {"companyName": "Totally Different Name"}},
        cached_ids={"hid_a": {"numeric_id": "12345"}},
        lookup=_lookup_with(company_id="12345"),
    )

    assert keep == {}, keep
    assert len(skip) == 1


def test_nothing_previously_exported_keeps_everything():
    from export_dedup import partition_companies_for_enrichment

    companies = {"hid_a": {"companyName": "Acme"}, "hid_b": {"companyName": "Beta"}}

    keep, skip = partition_companies_for_enrichment(companies, {}, _lookup_with())

    assert keep == companies
    assert skip == []


def test_partition_preserves_the_original_lead_objects():
    """The kept map feeds straight into enrichment — it must not lose fields."""
    from export_dedup import partition_companies_for_enrichment

    companies = {"hid_a": {"companyName": "Acme", "recommendedContacts": [{"id": "p1"}]}}

    keep, _ = partition_companies_for_enrichment(companies, {}, _lookup_with())

    assert keep["hid_a"]["recommendedContacts"] == [{"id": "p1"}]


# --------------------------------------------------------------------------
# 6. Scheduled-job liveness — GitHub disables crons after 60 days idle
# --------------------------------------------------------------------------

def test_recent_scheduled_run_is_ok():
    from monitoring import evaluate_scheduled_job_freshness

    now = datetime(2026, 7, 27, 12, 0, tzinfo=timezone.utc)
    verdict = evaluate_scheduled_job_freshness("2026-07-27 07:00:00", now=now)

    assert verdict["severity"] == "ok", verdict


def test_stale_scheduled_run_is_flagged():
    """GitHub silently disables scheduled workflows after 60 days of repo
    inactivity. No run means no failure means no alert — the outage is pure
    silence, so it has to be detected by absence rather than by an error.
    """
    from monitoring import evaluate_scheduled_job_freshness

    now = datetime(2026, 7, 27, 12, 0, tzinfo=timezone.utc)
    verdict = evaluate_scheduled_job_freshness("2026-07-24 07:00:00", now=now)

    assert verdict["severity"] != "ok"
    assert "77" in verdict["message"] or "3 day" in verdict["message"], verdict


def test_never_run_is_unknown_not_ok():
    """No stamp at all must not read as healthy — an unreadable signal is
    'unknown', never 'ok' (the monitoring.py convention)."""
    from monitoring import evaluate_scheduled_job_freshness

    verdict = evaluate_scheduled_job_freshness(None)

    assert verdict["severity"] == "unknown", verdict


def test_unparseable_stamp_is_unknown():
    from monitoring import evaluate_scheduled_job_freshness

    verdict = evaluate_scheduled_job_freshness("not a date")

    assert verdict["severity"] == "unknown", verdict


def test_freshness_window_is_tunable():
    from monitoring import evaluate_scheduled_job_freshness

    now = datetime(2026, 7, 27, 12, 0, tzinfo=timezone.utc)
    stamp = "2026-07-26 07:00:00"  # 29h old

    assert evaluate_scheduled_job_freshness(stamp, now=now, max_age_hours=48)["severity"] == "ok"
    assert evaluate_scheduled_job_freshness(stamp, now=now, max_age_hours=24)["severity"] != "ok"


# --------------------------------------------------------------------------
# 7. SIC lookup was exact-string — every messy shape scored the default
# --------------------------------------------------------------------------

def _a_real_sic() -> tuple[str, int]:
    """A SIC code that genuinely carries an explicit score in icp.yaml."""
    from utils import load_config
    scores = load_config()["onsite_likelihood"]["sic_scores"]
    key = sorted(scores)[0]
    return key, scores[key]


def test_sic_lookup_tolerates_the_documented_messy_shapes():
    """on-site likelihood is 25% of BOTH composites, so a missed lookup does
    not fail — it silently mis-scores the lead at the default 40. ZoomInfo
    sends SIC as an int, suffixed ("3599-01"), whitespace-padded and
    zero-padded; all of them missed the exact-string lookup.
    """
    from utils import get_onsite_likelihood_score

    key, expected = _a_real_sic()

    assert get_onsite_likelihood_score(key) == expected
    assert get_onsite_likelihood_score(int(key)) == expected
    assert get_onsite_likelihood_score(f"{key}-01") == expected
    assert get_onsite_likelihood_score(f"  {key}  ") == expected
    assert get_onsite_likelihood_score(f"{key}.0") == expected
    assert get_onsite_likelihood_score(key.zfill(5)) == expected


def test_unknown_sic_still_falls_back_to_the_default():
    from utils import get_onsite_likelihood_score, load_config

    default = load_config()["onsite_likelihood"]["default"]

    assert get_onsite_likelihood_score("9999") == default
    assert get_onsite_likelihood_score("") == default
    assert get_onsite_likelihood_score(None) == default
    assert get_onsite_likelihood_score("not a sic") == default


# --------------------------------------------------------------------------
# 8. Scoring weights were never validated to sum to 1.0
# --------------------------------------------------------------------------

def test_shipped_weights_sum_to_one():
    """Calibration rewrites icp.yaml, so this is a live drift risk, not a
    hypothetical one. Weights that do not sum to 1 rescale every composite
    silently — nothing errors, the numbers are just wrong."""
    from utils import validate_scoring_weights

    for workflow in ("intent", "geography"):
        verdict = validate_scoring_weights(workflow)
        assert verdict["severity"] == "ok", verdict


def test_weight_drift_is_detected():
    from utils import validate_scoring_weights

    verdict = validate_scoring_weights(
        "intent", weights={"signal_strength": 0.5, "onsite_likelihood": 0.25}
    )

    assert verdict["severity"] != "ok"
    assert "0.75" in verdict["message"], verdict


def test_empty_weights_are_reported_not_treated_as_valid():
    from utils import validate_scoring_weights

    verdict = validate_scoring_weights("intent", weights={})

    assert verdict["severity"] != "ok", verdict


# --------------------------------------------------------------------------
# 9. score_intent_contacts had no 100-clamp
# --------------------------------------------------------------------------

def test_intent_contact_score_is_clamped_to_100():
    """calculate_intent_score and calculate_geography_score both clamp with
    min(100, ...); score_intent_contacts rounded the raw composite. With
    weights that drift above 1.0 — which nothing validated — it could emit
    scores over 100 and break every downstream priority band."""
    from scoring import score_intent_contacts

    contacts = [{
        "id": "p1", "companyId": "c1", "companyName": "Acme",
        "jobTitle": "Chief Executive Officer",
        "contactAccuracyScore": "100",
        "mobilePhone": "555-111-2222", "directPhone": "555-333-4444",
    }]
    company_scores = {"c1": {"_score": 100}}

    scored = score_intent_contacts(
        contacts, company_scores,
        weights={"company_intent": 0.9, "authority": 0.9, "accuracy": 0.9, "phone": 0.9},
    )

    assert scored[0]["_score"] <= 100, scored[0]["_score"]
