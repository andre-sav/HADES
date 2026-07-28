"""Post-deploy synthetic check (HADES-704, insurance M5).

The Executive Summary crash went undetected from deploy until someone happened
to click the page. This bounds detection time on an app-level outage.

The probe targets ``/_stcore/health`` — the Streamlit app server's OWN endpoint,
which stops answering when the app is down, asleep or failed to deploy.

It deliberately does NOT target ``/healthz``: that returns 200 {"status":"ok"}
from Streamlit Cloud's edge for ANY hostname, including apps that do not exist
(verified 2026-07-27 against a nonsense subdomain). A check built on it can
never fail, which is worse than no check — it converts "unmonitored" into
"confirmed healthy". ``test_edge_health_payload_is_rejected`` is the guard that
keeps a future edit from quietly repointing the probe at it.
"""

from __future__ import annotations

import pytest

from scripts.synthetic_check import evaluate_synthetic_probe


def test_healthy_app_is_ok():
    verdict = evaluate_synthetic_probe(status=200, body="ok")

    assert verdict["severity"] == "ok", verdict


def test_healthy_app_tolerates_surrounding_whitespace():
    verdict = evaluate_synthetic_probe(status=200, body="  ok\n")

    assert verdict["severity"] == "ok", verdict


def test_edge_health_payload_is_rejected():
    """The /healthz JSON must NOT satisfy the probe.

    It contains 'ok' and returns 200, so a substring check would pass it — and
    would pass it for a deleted app too. Only the app server's bare 'ok' counts.
    """
    verdict = evaluate_synthetic_probe(status=200, body='{"status":"ok"}')

    assert verdict["severity"] == "critical", verdict
    assert "unexpected" in verdict["message"].lower(), verdict


def test_viewer_auth_redirect_is_reported_as_unreachable():
    """The app being put back behind SSO must be named, not read as an outage."""
    verdict = evaluate_synthetic_probe(
        status=303,
        body="",
        location="https://share.streamlit.io/-/auth/app?redirect_uri=https%3A%2F%2Fx",
    )

    assert verdict["severity"] == "critical"
    assert "auth" in verdict["message"].lower(), verdict
    assert "sharing" in verdict["message"].lower(), verdict


def test_other_redirect_is_reported_plainly():
    verdict = evaluate_synthetic_probe(
        status=302, body="", location="https://example.com/elsewhere"
    )

    assert verdict["severity"] == "critical"
    assert "example.com/elsewhere" in verdict["message"], verdict


def test_server_error_is_critical():
    verdict = evaluate_synthetic_probe(status=503, body="Service Unavailable")

    assert verdict["severity"] == "critical"
    assert "503" in verdict["message"], verdict


def test_transport_error_is_critical():
    """A timeout or DNS failure is an outage, not an unknown."""
    verdict = evaluate_synthetic_probe(status=None, body=None, error="timed out")

    assert verdict["severity"] == "critical"
    assert "timed out" in verdict["message"], verdict


def test_verdict_always_carries_a_message():
    for verdict in (
        evaluate_synthetic_probe(status=200, body="ok"),
        evaluate_synthetic_probe(status=404, body=""),
        evaluate_synthetic_probe(status=None, body=None, error="boom"),
    ):
        assert verdict.get("message"), verdict


# --------------------------------------------------------------------------
# The script: retries, exit codes
# --------------------------------------------------------------------------

@pytest.fixture
def probe_module():
    import scripts.synthetic_check as mod
    return mod


def test_probe_retries_then_succeeds(probe_module, monkeypatch):
    """A single transient blip on a 15-minute cron must not page anyone."""
    calls = {"n": 0}

    def flaky(url, timeout):
        calls["n"] += 1
        if calls["n"] < 3:
            raise RuntimeError("connection reset")
        return 200, "ok", None

    monkeypatch.setattr(probe_module, "_fetch", flaky)
    monkeypatch.setattr(probe_module.time, "sleep", lambda s: None)

    verdict = probe_module.probe("https://example.test", attempts=3, backoff_seconds=0)

    assert verdict["severity"] == "ok", verdict
    assert calls["n"] == 3


def test_probe_gives_up_after_all_attempts(probe_module, monkeypatch):
    monkeypatch.setattr(
        probe_module, "_fetch",
        lambda url, timeout: (_ for _ in ()).throw(RuntimeError("connection reset")),
    )
    monkeypatch.setattr(probe_module.time, "sleep", lambda s: None)

    verdict = probe_module.probe("https://example.test", attempts=3, backoff_seconds=0)

    assert verdict["severity"] == "critical", verdict
    assert "connection reset" in verdict["message"]


def test_main_exits_zero_when_healthy(probe_module, monkeypatch):
    monkeypatch.setattr(probe_module, "_fetch", lambda url, timeout: (200, "ok", None))

    assert probe_module.main(["--url", "https://example.test"]) == 0


def test_main_exits_nonzero_when_down(probe_module, monkeypatch):
    """The red run is the alert channel; the workflow's failure() step emails."""
    monkeypatch.setattr(probe_module, "_fetch", lambda url, timeout: (503, "nope", None))
    monkeypatch.setattr(probe_module.time, "sleep", lambda s: None)

    assert probe_module.main(["--url", "https://example.test"]) == 1


def test_main_never_probes_the_edge_health_endpoint(probe_module, monkeypatch):
    """Belt and braces: the default path must remain the app-level endpoint."""
    seen = {}
    monkeypatch.setattr(
        probe_module, "_fetch",
        lambda url, timeout: (seen.setdefault("url", url), (200, "ok", None))[1],
    )

    probe_module.main(["--url", "https://example.test"])

    assert seen["url"].endswith("/_stcore/health"), seen
    assert "/healthz" not in seen["url"], seen
