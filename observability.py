"""Sentry error monitoring (HADES-5w0).

Replaces "the operator emails us an error message" with "the engineer sees
the exception the moment it happens, with context." Both prior silent
failures (Company Enrich, the blank-enrichment incident) would have been
visible in real time.

Privacy: HADES handles contact PII (names, phones, emails). This init is
privacy-safe by construction — no request PII, NO local variables in stack
frames (a crash inside the export loop would otherwise ship whole lead
dicts to a third party), plus a before_send hook that redacts credential
keys. The cost is slightly thinner tracebacks; the trade is deliberate.

Never fatal: a missing DSN (local dev, tests) or a broken sentry-sdk is a
no-op. Monitoring is insurance, not a dependency.
"""
from __future__ import annotations

import logging
import os

try:  # optional dependency — never take the app down over monitoring
    import sentry_sdk
except Exception:  # pragma: no cover - exercised via patching
    sentry_sdk = None

logger = logging.getLogger(__name__)

_initialized = False

# Substrings that mark a value as a credential. Matched case-insensitively
# against event `extra` keys.
_SECRET_MARKERS = ("secret", "token", "password", "api_key", "apikey", "dsn", "auth")

_REDACTED = "[redacted]"


def reset_for_tests() -> None:
    """Clear the idempotence latch (tests only)."""
    global _initialized
    _initialized = False


def _get_dsn() -> str | None:
    """SENTRY_DSN from env, falling back to Streamlit secrets.

    Mirrors scripts/_credentials.py: env wins so headless/cron runs work
    without a secrets file.
    """
    dsn = os.environ.get("SENTRY_DSN")
    if dsn:
        return dsn
    try:
        import streamlit as st
        return st.secrets.get("SENTRY_DSN")
    except Exception:
        return None


def _environment() -> str:
    return os.environ.get("SENTRY_ENVIRONMENT") or "production"


def _release() -> str | None:
    """Release tag — the deployed git SHA when the platform exposes one."""
    return (os.environ.get("SENTRY_RELEASE")
            or os.environ.get("GITHUB_SHA")
            or None)


def scrub_event(event, _hint):
    """before_send hook: redact credential-shaped keys from event extras.

    Last line of defence — locals are already off, but application code can
    still attach context explicitly.
    """
    if not isinstance(event, dict):
        return event
    extra = event.get("extra")
    if isinstance(extra, dict):
        for key in list(extra):
            if any(m in key.lower() for m in _SECRET_MARKERS):
                extra[key] = _REDACTED
    return event


def init_sentry(component: str = "streamlit") -> bool:
    """Initialize Sentry once per process. Returns True when active.

    Safe to call on every Streamlit rerun and at the top of every headless
    script: subsequent calls are no-ops.

    Args:
        component: tag identifying the caller (``streamlit``,
            ``headless-intent``, ``health-check``) so issues can be filtered
            by where they fired.
    """
    global _initialized
    if _initialized:
        return True

    dsn = _get_dsn()
    if not dsn:
        return False  # local dev / tests / DSN not yet configured
    if sentry_sdk is None:
        logger.warning("SENTRY_DSN set but sentry-sdk is not installed — "
                       "error monitoring is OFF")
        return False

    try:
        sentry_sdk.init(
            dsn=dsn,
            environment=_environment(),
            release=_release(),
            # Free tier: errors only, no performance transactions.
            traces_sample_rate=0,
            # PII controls — see module docstring.
            send_default_pii=False,
            include_local_variables=False,
            before_send=scrub_event,
        )
        sentry_sdk.set_tag("component", component)
    except Exception:
        logger.warning("Sentry init failed — continuing without error "
                       "monitoring", exc_info=True)
        return False

    _initialized = True
    logger.info("Sentry initialized (environment=%s, component=%s)",
                _environment(), component)
    return True
