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

    valid, skipped = parse_manual_zip_list("75201, 75201-1234, 1001, 94116")

    assert valid == ["75201", "01001", "94116"], valid
    assert skipped == []


def test_manual_zips_reports_what_it_could_not_use():
    from utils import parse_manual_zip_list

    valid, skipped = parse_manual_zip_list("75201, notazip, 94116, XX")

    assert valid == ["75201", "94116"], valid
    assert skipped == ["notazip", "XX"], skipped


def test_manual_zips_deduplicates_while_preserving_order():
    from utils import parse_manual_zip_list

    valid, _ = parse_manual_zip_list("75201, 75201-9999, 94116, 75201")

    assert valid == ["75201", "94116"], valid


def test_manual_zips_accepts_newlines_and_whitespace():
    from utils import parse_manual_zip_list

    valid, skipped = parse_manual_zip_list(" 75201 \n94116\n\n 60601 ")

    assert valid == ["75201", "94116", "60601"], valid
    assert skipped == []


def test_manual_zips_on_empty_input():
    from utils import parse_manual_zip_list

    assert parse_manual_zip_list("") == ([], [])
    assert parse_manual_zip_list(None) == ([], [])


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
