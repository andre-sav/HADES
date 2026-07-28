"""config/icp.yaml's `cache:` block was inert (HADES-7qi).

`cache.ttl_days` and `cache.enabled` sat in the config file looking
authoritative while nothing read them: `get_cache_config()` had zero callers,
`cache_results()` took a hardcoded `ttl_days=7` default that the one call site
never overrode, and `enabled` was never consulted at all.

Config that lies is worse than no config — setting `enabled: false` to stop
serving stale intent results would have appeared to work and changed nothing.
"""

from __future__ import annotations


import pytest

from db._cache import CacheMixin


class _Cache(CacheMixin):
    """CacheMixin with the DB calls captured instead of executed."""

    def __init__(self):
        self.executed = []
        self.rows = []

    def execute(self, query, params=()):
        self.executed.append((query, params))
        return self.rows

    def execute_write(self, query, params=()):
        self.executed.append((query, params))


@pytest.fixture
def cache(monkeypatch):
    return _Cache()


def _set_config(monkeypatch, **cache_cfg):
    monkeypatch.setattr("db._cache.get_cache_config", lambda: cache_cfg)


def test_ttl_comes_from_config_not_a_hardcoded_default(cache, monkeypatch):
    _set_config(monkeypatch, ttl_days=30, enabled=True)

    cache.cache_results(cache_id="k", workflow_type="intent",
                        query_params={}, leads=[{"a": 1}])

    params = cache.executed[-1][1]
    assert any("30" not in str(p) for p in params)  # sanity: params exist
    stored_expiry = [p for p in params if isinstance(p, str) and "-" in p and ":" in p]
    assert stored_expiry, params
    # 30-day TTL must land well beyond the old hardcoded 7.
    from datetime import datetime, timedelta, timezone
    expiry = datetime.strptime(stored_expiry[-1], "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
    assert expiry - datetime.now(timezone.utc) > timedelta(days=20)


def test_an_explicit_ttl_argument_still_wins(cache, monkeypatch):
    """Callers that pass a TTL deliberately must not be overridden by config."""
    _set_config(monkeypatch, ttl_days=30, enabled=True)

    cache.cache_results(cache_id="k", workflow_type="intent",
                        query_params={}, leads=[{"a": 1}], ttl_days=1)

    from datetime import datetime, timedelta, timezone
    stored = [p for p in cache.executed[-1][1] if isinstance(p, str) and ":" in p][-1]
    expiry = datetime.strptime(stored, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
    assert expiry - datetime.now(timezone.utc) < timedelta(days=2)


def test_disabling_the_cache_stops_writes(cache, monkeypatch):
    _set_config(monkeypatch, ttl_days=7, enabled=False)

    cache.cache_results(cache_id="k", workflow_type="intent",
                        query_params={}, leads=[{"a": 1}])

    assert cache.executed == [], "cache.enabled=false must stop writing"


def test_disabling_the_cache_stops_reads(cache, monkeypatch):
    """The dangerous half: a disabled cache that still SERVES is exactly the
    stale-results problem someone would set the flag to escape."""
    _set_config(monkeypatch, ttl_days=7, enabled=False)
    cache.rows = [("[]",)]

    assert cache.get_cached_results("k") is None
    assert cache.executed == []


def test_cache_is_enabled_by_default(cache, monkeypatch):
    """A config missing the block entirely must keep today's behaviour."""
    _set_config(monkeypatch)

    cache.cache_results(cache_id="k", workflow_type="intent",
                        query_params={}, leads=[{"a": 1}])

    assert cache.executed, "cache should default to enabled"


def test_shipped_config_still_declares_both_keys():
    """If the block is removed from icp.yaml, these tests are guarding nothing."""
    from utils import get_cache_config

    cfg = get_cache_config()
    assert "ttl_days" in cfg and "enabled" in cfg, cfg


# --------------------------------------------------------------------------
# The scheduled-run countdown must follow the cron, not a hardcoded hour
# --------------------------------------------------------------------------

def test_next_run_is_derived_from_the_utc_cron_not_a_fixed_et_hour():
    """intent-poll runs at '0 12 * * 1-5' — 12:00 UTC. That is 8 AM ET in
    summer and 7 AM ET in winter. The dashboard hardcoded 7 AM ET, so for the
    ~8 months of DST it told the operator the wrong hour and counted down to
    the wrong moment.
    """
    from datetime import datetime, timezone
    from zoneinfo import ZoneInfo

    import importlib
    mod = importlib.import_module("automation_schedule")

    # A summer instant (EDT, UTC-4)
    summer = datetime(2026, 7, 27, 6, 0, tzinfo=ZoneInfo("America/New_York"))
    label, _countdown, run_at = mod.next_scheduled_run(now=summer)
    assert run_at.astimezone(timezone.utc).hour == 12, run_at
    assert "8" in label, label

    # A winter instant (EST, UTC-5)
    winter = datetime(2026, 1, 12, 5, 0, tzinfo=ZoneInfo("America/New_York"))
    label, _countdown, run_at = mod.next_scheduled_run(now=winter)
    assert run_at.astimezone(timezone.utc).hour == 12, run_at
    assert "7" in label, label


def test_next_run_skips_the_weekend():
    from datetime import datetime
    from zoneinfo import ZoneInfo
    import importlib
    mod = importlib.import_module("automation_schedule")

    saturday = datetime(2026, 7, 25, 18, 0, tzinfo=ZoneInfo("America/New_York"))
    _label, _countdown, run_at = mod.next_scheduled_run(now=saturday)

    assert run_at.weekday() < 5, run_at


def test_outcome_row_without_person_id_is_logged(caplog):
    """The (batch_id, person_id) unique index cannot deduplicate a NULL
    person_id — SQLite treats NULLs as distinct — so a re-export would insert
    a duplicate. No current path produces one (0 of 612 live rows), so the
    condition is made visible rather than migrated around."""
    import logging as _logging
    from db._outcomes import OutcomesMixin

    with caplog.at_level(_logging.WARNING):
        row = OutcomesMixin.build_outcome_row(
            {"companyName": "Acme"}, "B1", "geography", "2026-07-27 00:00:00"
        )

    assert row[3] is None
    assert "person_id" in caplog.text and "Acme" in caplog.text


def test_outcome_row_with_person_id_is_quiet(caplog):
    import logging as _logging
    from db._outcomes import OutcomesMixin

    with caplog.at_level(_logging.WARNING):
        row = OutcomesMixin.build_outcome_row(
            {"companyName": "Acme", "personId": "p1"}, "B1", "geography",
            "2026-07-27 00:00:00",
        )

    assert row[3] == "p1"
    assert caplog.records == []
