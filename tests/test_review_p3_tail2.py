"""Second 7qi cluster: operator-facing silent losses and monitoring ordering.

Three findings that each lose something quietly:

  1. Round-robin Contact Owner restarted at agents[0] on every export, so the
     front of the agent list got systematically more leads.
  2. Manual-ZIP mode discarded any token that was not exactly five digits —
     including ZIP+4 and zero-dropped forms that normalize_zip can recover —
     and said nothing.
  3. The ZoomInfo health check was scheduled at the same minute as the intent
     pipeline it is meant to run *before*.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock



ROOT = Path(__file__).resolve().parent.parent


# --------------------------------------------------------------------------
# 1. Round-robin Contact Owner skew
# --------------------------------------------------------------------------

def _fake_db_with_cursor(start=0):
    db = MagicMock(name="db")
    store = {"export_owner_cursor": str(start)} if start else {}
    db.get_sync_value.side_effect = lambda k: store.get(k)
    db.set_sync_value.side_effect = lambda k, v: store.__setitem__(k, v)
    # generate_batch_id() runs a real query and formats the sequence as an int.
    db.execute.return_value = [(1,)]
    return db, store


def _owners(csv_text: str) -> list[str]:
    import csv as _csv
    import io
    return [r["Contact Owner"] for r in _csv.DictReader(io.StringIO(csv_text))]


AGENTS = ["a@x.com", "b@x.com", "c@x.com", "d@x.com", "e@x.com"]


def test_round_robin_resumes_where_the_last_export_stopped():
    """Three exports of 3 leads each, 5 agents. Restarting at agents[0] every
    time gives a, b, c three times over and never touches d or e."""
    from export import export_leads_to_csv

    db, _ = _fake_db_with_cursor()
    leads = [{"companyName": f"Co{i}"} for i in range(3)]

    seen = []
    for _ in range(3):
        csv_text, _fn, _bid = export_leads_to_csv(
            leads, operator=None, workflow_type="geography", db=db, agents=AGENTS
        )
        seen += _owners(csv_text)

    assert len(set(seen)) == len(AGENTS), (
        f"only {len(set(seen))} of {len(AGENTS)} agents were ever assigned: {seen}"
    )


def test_round_robin_still_cycles_within_a_single_export():
    from export import export_leads_to_csv

    db, _ = _fake_db_with_cursor()
    leads = [{"companyName": f"Co{i}"} for i in range(5)]

    csv_text, _fn, _bid = export_leads_to_csv(
        leads, operator=None, workflow_type="geography", db=db, agents=AGENTS
    )

    assert _owners(csv_text) == AGENTS


def test_round_robin_survives_a_missing_db():
    """CSV-only exports pass db=None; they must not crash, just start at 0."""
    from export import export_leads_to_csv

    csv_text, _fn, _bid = export_leads_to_csv(
        [{"companyName": "Co"}], operator=None, workflow_type="geography",
        db=None, agents=AGENTS,
    )

    assert _owners(csv_text) == [AGENTS[0]]


def test_round_robin_tolerates_a_corrupt_cursor():
    from export import export_leads_to_csv

    db = MagicMock(name="db")
    db.get_sync_value.side_effect = lambda k: "not a number"
    db.execute.return_value = [(1,)]

    csv_text, _fn, _bid = export_leads_to_csv(
        [{"companyName": "Co"}], operator=None, workflow_type="geography",
        db=db, agents=AGENTS,
    )

    assert _owners(csv_text) == [AGENTS[0]]


def test_no_agents_configured_leaves_owner_blank():
    from export import export_leads_to_csv

    csv_text, _fn, _bid = export_leads_to_csv(
        [{"companyName": "Co"}], operator=None, workflow_type="geography",
        db=None, agents=[],
    )

    assert _owners(csv_text) == [""]


# --------------------------------------------------------------------------
# 2. Manual-ZIP mode discarded tokens silently
# --------------------------------------------------------------------------

def test_manual_zips_recovers_the_shapes_normalize_zip_understands():
    """Pasting from freemaptools or a spreadsheet yields ZIP+4 and zero-dropped
    forms. Dropping them loses search coverage the operator asked for."""
    from utils import parse_manual_zip_list

    valid, skipped, _adj = parse_manual_zip_list("75201, 75201-1234, 1001, 94116")

    assert valid == ["75201", "01001", "94116"], valid
    assert skipped == []


def test_manual_zips_reports_what_it_could_not_use():
    from utils import parse_manual_zip_list

    valid, skipped, _adj = parse_manual_zip_list("75201, notazip, 94116, XX")

    assert valid == ["75201", "94116"], valid
    assert skipped == ["notazip", "XX"], skipped


def test_manual_zips_deduplicates_while_preserving_order():
    from utils import parse_manual_zip_list

    valid, _skip, _adj = parse_manual_zip_list("75201, 75201-9999, 94116, 75201")

    assert valid == ["75201", "94116"], valid


def test_manual_zips_accepts_newlines_and_whitespace():
    from utils import parse_manual_zip_list

    valid, skipped, _adj = parse_manual_zip_list(" 75201 \n94116\n\n 60601 ")

    assert valid == ["75201", "94116", "60601"], valid
    assert skipped == []


def test_manual_zips_on_empty_input():
    from utils import parse_manual_zip_list

    assert parse_manual_zip_list("") == ([], [], [])
    assert parse_manual_zip_list(None) == ([], [], [])


# --------------------------------------------------------------------------
# 3. The health check must PRECEDE the pipeline it guards
# --------------------------------------------------------------------------

def _cron_of(workflow: str) -> str:
    import re
    text = (ROOT / ".github" / "workflows" / workflow).read_text()
    match = re.search(r"^\s*-\s*cron:\s*'([^']+)'", text, re.M)
    assert match, f"no active cron in {workflow}"
    return match.group(1)


def test_health_check_runs_before_the_intent_pipeline():
    """zoominfo-health-check exists so a credit/entitlement problem is flagged
    BEFORE the team pulls lists. Scheduled at the same minute as intent-poll it
    cannot do that — GitHub gives no ordering guarantee between workflows, and
    both would hit the ZoomInfo API simultaneously.
    """
    health_hour = int(_cron_of("zoominfo-health-check.yml").split()[1])
    poll_hour = int(_cron_of("intent-poll.yml").split()[1])

    assert health_hour < poll_hour, (
        f"health check runs at {health_hour}:00 UTC, intent poll at "
        f"{poll_hour}:00 UTC — it must run strictly earlier"
    )


def test_anomaly_check_runs_after_the_zoho_sync():
    """Documented in CLAUDE.md: the anomaly check measures Zoho linkage, so it
    must run after the sync or it grades yesterday's state."""
    anomaly_hour = int(_cron_of("data-anomaly-check.yml").split()[1])
    sync_hour = int(_cron_of("zoho-operator-sync.yml").split()[1])

    assert sync_hour < anomaly_hour, (anomaly_hour, sync_hour)


# --------------------------------------------------------------------------
# 4. Suffix stripping was single-pass and order-dependent
# --------------------------------------------------------------------------

def test_the_reviews_exact_case_now_matches():
    """"Acme Corp, LLC" vs "Acme Corporation" scored 61.5 and was treated as
    two different companies, so the duplicate was pushed as a new lead.

    Cause: COMPANY_SUFFIXES is applied once each in list order and every
    pattern is $-anchored. Stripping " LLC" leaves "acme corp," — but the
    "corp" pattern sits EARLIER in the list and has already been passed, so
    the second suffix never gets removed.
    """
    from dedup import normalize_company_name

    assert normalize_company_name("Acme Corp, LLC") == normalize_company_name("Acme Corporation")


def test_stacked_suffixes_strip_regardless_of_order():
    from dedup import normalize_company_name

    assert normalize_company_name("Widget Co., Ltd.") == normalize_company_name("Widget")
    assert normalize_company_name("Widget LLC Inc") == normalize_company_name("Widget Inc LLC")


def test_single_suffix_forms_still_agree():
    from dedup import normalize_company_name

    base = normalize_company_name("Acme")
    for variant in ("Acme Inc", "Acme Inc.", "Acme Incorporated", "Acme, Inc.",
                    "Acme Corp", "Acme Corporation", "Acme LLC", "Acme Company"):
        assert normalize_company_name(variant) == base, variant


def test_stripping_never_empties_a_name():
    """A name that is nothing BUT a suffix must keep something to match on —
    an empty key would collide with every other empty key."""
    from dedup import normalize_company_name

    for name in ("LLC", " Inc.", "Company"):
        assert normalize_company_name(name), f"{name!r} normalised to empty"


def test_suffix_words_inside_a_name_are_preserved():
    """Only trailing suffixes are legal entity markers. "Corporate Express" and
    "Company Store" are just names."""
    from dedup import normalize_company_name

    assert "corporate" in normalize_company_name("Corporate Express")
    assert "company" in normalize_company_name("Company Store")
    assert normalize_company_name("Incorporated Sundries") != normalize_company_name("Sundries")


def test_normalisation_is_idempotent():
    """Running it twice must not strip more than running it once — otherwise
    keys built at different points in the pipeline disagree."""
    from dedup import normalize_company_name

    for name in ("Acme Corp, LLC", "Widget Co., Ltd.", "Plain Name"):
        once = normalize_company_name(name)
        assert normalize_company_name(once) == once, name


def test_vs_dedup_ignores_a_stale_persisted_company_norm():
    """vanillasoft_leads.company_norm was computed by normalize_company_name at
    IMPORT time and stored. Any change to that function — like the suffix fix
    above — leaves 18k+ persisted keys that no freshly-normalised name can ever
    match, and dedup silently stops catching them.

    The lookup must therefore re-derive the key from company_name rather than
    trust the stored column. A persisted derived value cannot be trusted when
    the deriving function is still evolving.
    """
    from export_dedup import get_previously_exported

    db = MagicMock(name="db")
    db.get_exported_company_ids.return_value = {}
    db.get_vs_dedup_index.return_value = [{
        "company_name": "Acme Corp, LLC",
        "company_norm": "acme corp",          # what the OLD function produced
        "phone_business": "", "phone_mobile": "", "phone_home": "",
        "zip": "75201", "state": "TX", "lead_status": "New",
        "added_date": "2026-07-01",
    }]

    lookup = get_previously_exported(db, days_back=365)

    from dedup import normalize_company_name
    fresh_key = normalize_company_name("Acme Corporation")
    assert fresh_key in lookup["vs_by_name"], (
        f"stale stored key blocked the match; index holds "
        f"{list(lookup['vs_by_name'])} but a fresh name normalises to {fresh_key!r}"
    )


def test_vs_dedup_falls_back_to_the_stored_norm_when_the_name_is_missing():
    """Messy imports do occur — a row with no company_name must still index."""
    from export_dedup import get_previously_exported

    db = MagicMock(name="db")
    db.get_exported_company_ids.return_value = {}
    db.get_vs_dedup_index.return_value = [{
        "company_name": "", "company_norm": "legacy key",
        "phone_business": "", "phone_mobile": "", "phone_home": "",
        "zip": "", "state": "", "lead_status": "", "added_date": "2026-07-01",
    }]

    lookup = get_previously_exported(db, days_back=365)

    assert "legacy key" in lookup["vs_by_name"]


def test_vs_zip_corroboration_normalises_both_sides():
    """vanillasoft_leads.zip is normalize_zip() output PERSISTED at import
    time, and the franchise-safety corroboration compares it against a freshly
    normalised contact ZIP. Same trap as company_norm: a change to
    normalize_zip strands the stored side, the ZIP check stops corroborating,
    and the dedup match is rejected — a duplicate lead ships.

    Measured exposure today is nil (all 293k stored ZIPs are 5-digit and
    re-normalise to themselves), but the class has now bitten twice, so the
    comparison normalises both sides rather than trusting the stored value.
    """
    from export_dedup import _match_vs_lead

    entry = {"zip": "1001", "phone_business": "5551112222"}  # un-normalised
    contact = {"zipCode": "01001", "phone": "555-111-2222"}

    match = _match_vs_lead(
        contact, vs_by_name={}, vs_by_phone={},
        vs_by_company_phone={"5551112222": entry},
    )

    assert match is entry, "a differently-formatted stored ZIP blocked corroboration"


def test_vs_name_branch_also_normalises_the_stored_zip():
    """Three call sites compare the stored ZIP; the name branch is the one a
    regex sweep missed. Sibling paths need enumerating, not pattern-matching."""
    from export_dedup import _match_vs_lead
    from dedup import normalize_company_name

    entry = {"zip": "1001", "company_name": "Acme"}
    match = _match_vs_lead(
        {"companyName": "Acme", "zipCode": "01001"},
        vs_by_name={normalize_company_name("Acme"): [entry]},
        vs_by_phone={}, vs_by_company_phone={},
    )

    assert match is entry


def test_a_genuinely_different_zip_still_blocks_the_match():
    """The corroboration must keep working — normalising both sides must not
    turn the franchise guard into a rubber stamp."""
    from export_dedup import _match_vs_lead
    from dedup import normalize_company_name

    entry = {"zip": "90210", "company_name": "Acme"}
    match = _match_vs_lead(
        {"companyName": "Acme", "zipCode": "01001"},
        vs_by_name={normalize_company_name("Acme"): [entry]},
        vs_by_phone={}, vs_by_company_phone={},
    )

    assert match is None, "different ZIPs must not corroborate"


def test_manual_zips_reports_entries_it_had_to_reinterpret():
    """Padding "1001" to "01001" is right for a spreadsheet that ate a leading
    zero — but an operator halfway through typing "75201" gets "07520", a real
    ZIP in New Jersey. The transformation has to be visible, not silent."""
    from utils import parse_manual_zip_list

    valid, skipped, adjusted = parse_manual_zip_list("75201, 1001, 75201-1234")

    assert valid == ["75201", "01001"], valid
    assert ("1001", "01001") in adjusted
    assert ("75201-1234", "75201") in adjusted
    assert not any(raw == "75201" for raw, _ in adjusted), "unchanged entries must not be listed"
