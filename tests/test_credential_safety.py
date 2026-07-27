"""The test suite must never read real production credentials.

`.streamlit/secrets.toml` on a developer machine holds live values — the
production Turso database URL and token, ZoomInfo and Zoho client secrets, a
GitHub token, the VanillaSoft lead ID. Real streamlit reads that file happily,
so anything under test that reaches `st.secrets` gets production credentials
and can connect to production.

Until HADES-w1k this was prevented only by accident: fifteen test modules
assigned `sys.modules["streamlit"] = MagicMock()` at import time, and whichever
pytest imported first shadowed the real package for the whole session. Modules
that did not do it were unprotected, and the protection vanished the moment the
mocks were removed — which is exactly how this was found. Two credential tests
started returning the real production Turso URL.

conftest.py now neutralises `st.secrets` for every test, in the same shape as
the existing SMTP block. These tests are the standing proof that it works.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parent.parent
SECRETS = ROOT / ".streamlit" / "secrets.toml"

# Keys whose real values must never be visible to a test.
SENSITIVE_KEYS = (
    "TURSO_DATABASE_URL",
    "TURSO_AUTH_TOKEN",
    "ZOOMINFO_CLIENT_SECRET",
    "ZOHO_CLIENT_SECRET",
    "ZOHO_REFRESH_TOKEN",
    "GITHUB_TOKEN",
)


def test_streamlit_secrets_are_empty_during_tests():
    import streamlit as st

    for key in SENSITIVE_KEYS:
        assert not st.secrets.get(key), (
            f"st.secrets exposed a real {key} to the test suite. conftest.py's "
            "_no_real_streamlit_secrets fixture is not doing its job — tests "
            "can now reach production."
        )


def test_credential_loader_finds_nothing_without_env_or_file(monkeypatch):
    """The loader's three sources — env, secrets.toml, st.secrets — must all be
    neutralisable. st.secrets is the one that used to leak."""
    monkeypatch.delenv("TURSO_DATABASE_URL", raising=False)
    monkeypatch.setattr("scripts._credentials.Path.exists", lambda self: False)

    from scripts._credentials import load_credentials

    with pytest.raises(ValueError, match="Missing required credential"):
        load_credentials()


@pytest.mark.skipif(not SECRETS.exists(), reason="no local secrets.toml (CI)")
def test_local_secrets_file_is_not_tracked_by_git():
    """Belt and braces: the file this guards must never be committable."""
    import subprocess

    result = subprocess.run(
        ["git", "check-ignore", str(SECRETS.relative_to(ROOT))],
        cwd=ROOT, capture_output=True, text=True,
    )
    assert result.returncode == 0, (
        ".streamlit/secrets.toml is NOT gitignored — it holds live production "
        "credentials and is one `git add -A` from being published."
    )


@pytest.mark.skipif(not SECRETS.exists(), reason="no local secrets.toml (CI)")
def test_canary_the_real_file_still_holds_the_keys_we_guard():
    """If the real file stops containing these keys, the guard above is testing
    nothing and this reminds us to re-point it rather than trust a vacuous pass.
    """
    keys = set(tomllib.loads(SECRETS.read_text()).keys())

    assert keys & set(SENSITIVE_KEYS), (
        f"secrets.toml no longer holds any of {SENSITIVE_KEYS} — update "
        "SENSITIVE_KEYS so this suite keeps guarding something real."
    )
