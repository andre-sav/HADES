"""Tests for observability.py — Sentry error monitoring (HADES-5w0).

HADES handles contact PII (names, phones, emails). The init must be
privacy-safe by construction: no request PII, and no local variables in
stack frames (a crash inside the export loop would otherwise ship whole
lead dicts to a third party).
"""

import sys
from unittest.mock import MagicMock, patch

import pytest

sys.modules.setdefault("libsql_experimental", MagicMock())

import observability


@pytest.fixture(autouse=True)
def _reset_state():
    observability.reset_for_tests()
    yield
    observability.reset_for_tests()


class TestInitSentry:
    def test_no_dsn_is_a_noop(self):
        """Local dev and tests have no DSN — must not crash or init."""
        with patch.object(observability, "_get_dsn", return_value=None), \
             patch.object(observability, "sentry_sdk") as mock_sdk:
            assert observability.init_sentry() is False
            mock_sdk.init.assert_not_called()

    def test_dsn_initializes(self):
        with patch.object(observability, "_get_dsn", return_value="https://k@o.ingest.sentry.io/1"), \
             patch.object(observability, "sentry_sdk") as mock_sdk:
            assert observability.init_sentry() is True
            mock_sdk.init.assert_called_once()

    def test_is_idempotent(self):
        """Streamlit reruns the page script constantly — a second call must
        not re-init (Sentry would duplicate integrations)."""
        with patch.object(observability, "_get_dsn", return_value="https://k@o.ingest.sentry.io/1"), \
             patch.object(observability, "sentry_sdk") as mock_sdk:
            observability.init_sentry()
            observability.init_sentry()
            observability.init_sentry()
            assert mock_sdk.init.call_count == 1

    def test_pii_is_not_sent(self):
        """send_default_pii=False (no IP/cookies) AND
        include_local_variables=False — stack frames in this codebase hold
        lead dicts with names, phones and emails."""
        with patch.object(observability, "_get_dsn", return_value="https://k@o.ingest.sentry.io/1"), \
             patch.object(observability, "sentry_sdk") as mock_sdk:
            observability.init_sentry()
            kwargs = mock_sdk.init.call_args[1]
            assert kwargs["send_default_pii"] is False
            assert kwargs["include_local_variables"] is False

    def test_component_tags_the_environment(self):
        with patch.object(observability, "_get_dsn", return_value="https://k@o.ingest.sentry.io/1"), \
             patch.object(observability, "sentry_sdk") as mock_sdk:
            observability.init_sentry(component="headless-intent")
            kwargs = mock_sdk.init.call_args[1]
            assert kwargs["environment"]
            # component is carried as a tag, not the environment name
            mock_sdk.set_tag.assert_any_call("component", "headless-intent")

    def test_no_performance_tracing_on_free_tier(self):
        with patch.object(observability, "_get_dsn", return_value="https://k@o.ingest.sentry.io/1"), \
             patch.object(observability, "sentry_sdk") as mock_sdk:
            observability.init_sentry()
            kwargs = mock_sdk.init.call_args[1]
            assert kwargs.get("traces_sample_rate", 0) == 0

    def test_import_failure_is_survivable(self):
        """sentry-sdk missing (an old container, a partial install) must not
        take the app down — monitoring is insurance, not a dependency."""
        with patch.object(observability, "_get_dsn", return_value="https://k@o.ingest.sentry.io/1"), \
             patch.object(observability, "sentry_sdk", None):
            assert observability.init_sentry() is False

    def test_init_failure_is_survivable(self):
        with patch.object(observability, "_get_dsn", return_value="https://k@o.ingest.sentry.io/1"), \
             patch.object(observability, "sentry_sdk") as mock_sdk:
            mock_sdk.init.side_effect = RuntimeError("bad dsn")
            assert observability.init_sentry() is False


class TestScrubEvent:
    """A before_send hook is the last line of defence: even with locals
    off, an exception MESSAGE can carry PII (e.g. a formatted lead row)."""

    def test_secrets_are_redacted_from_extra(self):
        event = {"extra": {"ZOOMINFO_CLIENT_SECRET": "shhh", "batch": "B1"}}
        scrubbed = observability.scrub_event(event, {})
        assert scrubbed["extra"]["ZOOMINFO_CLIENT_SECRET"] == "[redacted]"
        assert scrubbed["extra"]["batch"] == "B1"

    def test_token_and_password_keys_redacted_case_insensitively(self):
        event = {"extra": {"auth_token": "t", "APP_PASSWORD": "p", "api_key": "k"}}
        scrubbed = observability.scrub_event(event, {})
        assert all(v == "[redacted]" for v in scrubbed["extra"].values())

    def test_non_dict_event_passes_through(self):
        assert observability.scrub_event(None, {}) is None

    def test_event_without_extra_is_unchanged(self):
        event = {"message": "boom"}
        assert observability.scrub_event(event, {}) == {"message": "boom"}


class TestWiring:
    """Streamlit runs each page as an INDEPENDENT script — app.py does not
    execute when a user opens /Geography_Workflow directly. So the init must
    sit on a path every page traverses, plus each headless entry point."""

    def _src(self, relpath):
        from pathlib import Path
        return (Path(__file__).resolve().parent.parent / relpath).read_text()

    def test_require_auth_initializes_sentry(self):
        """require_auth() is the universal page-boot gate (all 11 pages +
        app.py call it first), so it is where per-page coverage comes from."""
        src = self._src("utils.py")
        assert "init_sentry" in src

    def test_headless_entry_points_initialize_sentry(self):
        for script in ("scripts/run_intent_pipeline.py",
                       "scripts/check_zoominfo_health.py",
                       "scripts/run_zoho_operator_sync.py"):
            assert "init_sentry" in self._src(script), f"{script} missing Sentry init"

    def test_headless_scripts_tag_their_component(self):
        """Issues must be filterable by origin — a cron failure and a UI
        failure need different responses."""
        assert 'component="headless-intent"' in self._src("scripts/run_intent_pipeline.py")
        assert 'component="health-check"' in self._src("scripts/check_zoominfo_health.py")


class TestRequirementsDeclared:
    def test_sentry_sdk_declared_in_requirements(self):
        """Streamlit Cloud installs from requirements.txt only."""
        from pathlib import Path
        reqs = (Path(__file__).resolve().parent.parent / "requirements.txt").read_text()
        assert "sentry-sdk" in reqs

    def test_sentry_sdk_declared_in_lock_file(self):
        """GitHub Actions installs from requirements-lock.txt — a dep in
        requirements.txt alone leaves every cron run unmonitored."""
        from pathlib import Path
        lock = (Path(__file__).resolve().parent.parent / "requirements-lock.txt").read_text()
        assert "sentry-sdk==" in lock
