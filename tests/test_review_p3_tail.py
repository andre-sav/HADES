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
