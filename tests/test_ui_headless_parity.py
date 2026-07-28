"""UI/headless drift (HADES-7qi).

Three places where the automated daily run behaved differently from the same
workflow driven by hand — the worst kind of difference, because the operator
validates the UI path and the cron silently does something else.

  1. Contact auto-selection: the UI re-ranks with the operator's learned title
     preferences; headless took contacts[0] on accuracy alone, so the cron
     picked contacts the operator would not have.
  2. The page cap was a bare literal at three call sites plus a differing
     default on the function itself.
  3. Headless failures never reached the error_log the Pipeline Health page
     reads, so a cron failure was invisible on the page built to show failures.
"""

from __future__ import annotations

from unittest.mock import MagicMock

from db._title_prefs import normalize_title
from expand_search import select_best_contacts


def _c(pid, title, accuracy):
    return {"personId": pid, "jobTitle": title, "contactAccuracyScore": accuracy}


def _by_company(*contacts):
    return {"c1": {"company_name": "Acme", "contacts": list(contacts)}}


def test_accuracy_still_dominates():
    """Title preference is a TIEBREAKER, not an override — a clearly better
    contact must not be displaced by a mildly preferred title."""
    grouped = _by_company(
        _c("p1", "Facilities Manager", 98),
        _c("p2", "Office Manager", 80),
    )
    prefs = {normalize_title("Office Manager"): 1.0,
             normalize_title("Facilities Manager"): 0.0}

    assert select_best_contacts(grouped, prefs)["c1"]["personId"] == "p1"


def test_title_preference_breaks_an_accuracy_tie():
    grouped = _by_company(
        _c("p1", "Office Manager", 95),
        _c("p2", "Facilities Manager", 95),
    )
    prefs = {normalize_title("Facilities Manager"): 0.9,
             normalize_title("Office Manager"): 0.1}

    assert select_best_contacts(grouped, prefs)["c1"]["personId"] == "p2"


def test_without_preferences_it_matches_the_old_headless_behaviour():
    """No preferences learned yet must leave the cron's choice unchanged —
    first contact, which build_contacts_by_company has already sorted."""
    grouped = _by_company(_c("p1", "A", 95), _c("p2", "B", 90))

    assert select_best_contacts(grouped, {})["c1"]["personId"] == "p1"
    assert select_best_contacts(grouped, None)["c1"]["personId"] == "p1"


def test_unknown_titles_score_neutral_not_zero():
    """A title nobody has ranked must not lose to one actively skipped."""
    grouped = _by_company(
        _c("p1", "Never Seen Before", 95),
        _c("p2", "Rejected Title", 95),
    )
    prefs = {normalize_title("Rejected Title"): 0.0}

    assert select_best_contacts(grouped, prefs)["c1"]["personId"] == "p1"


def test_messy_accuracy_values_do_not_crash_selection():
    grouped = _by_company(_c("p1", "A", "95%"), _c("p2", "B", None))

    assert select_best_contacts(grouped, {})["c1"]["personId"] == "p1"


def test_companies_with_no_contacts_are_skipped():
    grouped = {"c1": {"company_name": "Acme", "contacts": []}}

    assert select_best_contacts(grouped, {}) == {}


# --------------------------------------------------------------------------
# 2. One page cap, not four
# --------------------------------------------------------------------------

def test_the_page_cap_is_a_single_shared_constant():
    """Three call sites hardcoded 5 while search_contacts_all_pages defaulted
    to 10, so whichever path forgot to pass it swept twice as deep."""
    import inspect

    from zoominfo_client import DEFAULT_SEARCH_MAX_PAGES, ZoomInfoClient

    signature = inspect.signature(ZoomInfoClient.search_contacts_all_pages)
    assert signature.parameters["max_pages"].default == DEFAULT_SEARCH_MAX_PAGES

    for module in ("expand_search", "scripts.run_intent_pipeline"):
        source = inspect.getsource(__import__(module, fromlist=["x"]))
        assert "max_pages=5" not in source, f"{module} still hardcodes the cap"


# --------------------------------------------------------------------------
# 3. Headless failures must reach the error_log the health page reads
# --------------------------------------------------------------------------

def test_headless_failures_are_written_to_the_error_log():
    """Pipeline Health reads error_log. Only pages/ ever wrote to it, so a
    failed cron run left that panel empty — the page built to surface failures
    was blind to the unattended ones."""
    from scripts.run_intent_pipeline import log_pipeline_error

    db = MagicMock(name="db")
    log_pipeline_error(db, RuntimeError("boom"), recoverable=False)

    assert db.log_error.called, "headless error was not recorded"
    kwargs = db.log_error.call_args.kwargs
    assert kwargs["workflow_type"] == "intent"
    assert "boom" in kwargs["technical_message"]


def test_error_logging_never_raises_secondary_failures():
    """The pipeline is already failing; logging must not make it worse."""
    from scripts.run_intent_pipeline import log_pipeline_error

    db = MagicMock(name="db")
    db.log_error.side_effect = RuntimeError("db is down too")

    log_pipeline_error(db, RuntimeError("boom"), recoverable=True)  # must not raise


def test_the_pipeline_actually_calls_the_error_logger():
    """A logging helper nobody calls is worse than none — it reads as covered.
    Both top-level handlers must record before re-raising."""
    import inspect

    from scripts import run_intent_pipeline as mod

    source = inspect.getsource(mod.run_pipeline)
    assert source.count("log_pipeline_error(db") >= 2, (
        "run_pipeline does not record its failures to error_log"
    )
