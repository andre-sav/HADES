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
