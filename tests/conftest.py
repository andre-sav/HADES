"""Shared test fixtures.

The pipeline tests drive run_pipeline() all the way to its email step with
real-shaped SMTP credentials, so the suite was opening genuine TCP
connections to smtp.gmail.com on every run — authenticating with fake
credentials from whatever IP happened to run the tests. The pipeline's
broad ``except Exception: summary["email_failed"] = True`` swallowed the
result, so the tests still passed and the behaviour stayed invisible.

Blocking it here rather than per-test means a future test cannot
reintroduce it by forgetting a patch (review N2-11).
"""

import smtplib
from unittest.mock import MagicMock

import pytest


@pytest.fixture(autouse=True)
def _no_outbound_smtp(monkeypatch):
    """Neutralise SMTP for every test. Opt back in explicitly if a test
    genuinely needs to assert on SMTP behaviour, by patching the symbol it
    imports rather than undoing this.
    """
    monkeypatch.setattr(smtplib, "SMTP", MagicMock(name="SMTP"))
    monkeypatch.setattr(smtplib, "SMTP_SSL", MagicMock(name="SMTP_SSL"))
    yield


@pytest.fixture(autouse=True)
def _no_real_streamlit_secrets(monkeypatch):
    """Neutralise st.secrets for every test.

    `.streamlit/secrets.toml` on a developer machine holds LIVE production
    values — Turso URL and token, ZoomInfo and Zoho secrets, a GitHub token —
    and real streamlit reads it happily. Anything under test that reaches
    st.secrets therefore gets production credentials and can connect to
    production.

    Until HADES-w1k this was prevented only by accident: fifteen test modules
    assigned sys.modules["streamlit"] = MagicMock() at import time, and
    whichever pytest imported first shadowed the real package session-wide.
    Modules that did not do it were never protected. Removing those mocks made
    two credential tests return the real production Turso URL, which is how the
    gap surfaced.

    Blocking it here, like SMTP above, means a future test cannot reintroduce
    the exposure by forgetting a patch. A test that genuinely needs populated
    secrets should patch the symbol it reads (see
    test_run_intent_pipeline.TestCredentialLoading.test_streamlit_secrets_fallback,
    which swaps the whole module inside a `with patch.dict` block).
    """
    import streamlit

    monkeypatch.setattr(streamlit, "secrets", {}, raising=False)
    yield
