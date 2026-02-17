"""
Shared credential loader for headless scripts.

Priority: environment variables → .streamlit/secrets.toml → st.secrets fallback.
"""

import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def load_credentials() -> dict:
    """Load credentials from env vars, falling back to secrets.toml.

    Returns:
        Dict with all credential keys. SMTP keys may be None if not configured.
    """
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        pass

    # Try secrets.toml as fallback source
    secrets = {}
    secrets_path = PROJECT_ROOT / ".streamlit" / "secrets.toml"
    if secrets_path.exists():
        import tomllib
        with open(secrets_path, "rb") as f:
            secrets = tomllib.load(f)

    # Try Streamlit secrets (when running inside Streamlit app)
    st_secrets = {}
    try:
        import streamlit as st
        if hasattr(st, "secrets") and st.secrets:
            st_secrets = dict(st.secrets)
    except Exception:
        pass

    def _get(key: str, required: bool = False) -> str | None:
        val = os.environ.get(key) or secrets.get(key) or st_secrets.get(key)
        if required and not val:
            raise ValueError(f"Missing required credential: {key}. "
                             f"Set via environment or .streamlit/secrets.toml")
        return val

    return {
        # Required — pipeline cannot run without these
        "TURSO_DATABASE_URL": _get("TURSO_DATABASE_URL", required=True),
        "TURSO_AUTH_TOKEN": _get("TURSO_AUTH_TOKEN", required=True),
        "ZOOMINFO_CLIENT_ID": _get("ZOOMINFO_CLIENT_ID", required=True),
        "ZOOMINFO_CLIENT_SECRET": _get("ZOOMINFO_CLIENT_SECRET", required=True),
        # Optional — email delivery skipped if missing
        "SMTP_USER": _get("SMTP_USER"),
        "SMTP_PASSWORD": _get("SMTP_PASSWORD"),
        "EMAIL_RECIPIENTS": _get("EMAIL_RECIPIENTS"),
        "EMAIL_FROM": _get("EMAIL_FROM"),
    }
