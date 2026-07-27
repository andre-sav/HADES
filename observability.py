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
import re

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


# Contact PII patterns. Sentry's default LoggingIntegration turns every
# logger.error into an event (message + exception text verbatim) and every
# logger.info/warning into a breadcrumb — none of which pass through an
# `extra`-only scrubber. These run over that free text (review N2-03).
_EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
# 10/11-digit phone runs, with or without separators. Anchored on word
# boundaries so batch ids and counts are untouched.
_PHONE_RE = re.compile(r"\b(?:\+?1[\s.-]?)?\(?\d{3}\)?[\s.-]?\d{3}[\s.-]?\d{4}\b")
# Name-shaped dict keys as they appear in a formatted lead repr.
_NAME_FIELD_RE = re.compile(
    r"(['\"]?(?:firstName|lastName|fullName|contactName)['\"]?\s*[:=]\s*)"
    r"(['\"])([^'\"]{1,80})\2",
    re.IGNORECASE,
)


def _scrub_text(text):
    """Redact contact PII from free text, preserving diagnostic value."""
    if not isinstance(text, str) or not text:
        return text
    text = _EMAIL_RE.sub(_REDACTED, text)
    text = _PHONE_RE.sub(_REDACTED, text)
    text = _NAME_FIELD_RE.sub(lambda m: f"{m.group(1)}{m.group(2)}{_REDACTED}{m.group(2)}", text)
    return text


def scrub_breadcrumb(crumb, _hint):
    """before_breadcrumb hook: log records become breadcrumbs verbatim."""
    if not isinstance(crumb, dict):
        return crumb
    if "message" in crumb:
        crumb["message"] = _scrub_text(crumb.get("message"))
    data = crumb.get("data")
    if isinstance(data, dict):
        for k, v in list(data.items()):
            if any(m in str(k).lower() for m in _SECRET_MARKERS):
                data[k] = _REDACTED
            elif isinstance(v, str):
                data[k] = _scrub_text(v)
    return crumb


def scrub_event(event, _hint):
    """before_send hook: redact credentials AND contact PII.

    Covers the paths that actually carry data:
      - event["extra"]        explicit context (credential-shaped keys)
      - event["logentry"]     the LoggingIntegration's formatted message
      - event["exception"]    exception .value text, e.g. a formatted lead row

    Locals are already suppressed via include_local_variables=False; this is
    the layer that catches free text (review N2-03).
    """
    if not isinstance(event, dict):
        return event

    extra = event.get("extra")
    if isinstance(extra, dict):
        for key in list(extra):
            if any(m in key.lower() for m in _SECRET_MARKERS):
                extra[key] = _REDACTED
            elif isinstance(extra[key], str):
                extra[key] = _scrub_text(extra[key])

    logentry = event.get("logentry")
    if isinstance(logentry, dict) and logentry.get("message"):
        logentry["message"] = _scrub_text(logentry["message"])

    if isinstance(event.get("message"), str):
        event["message"] = _scrub_text(event["message"])

    exception = event.get("exception")
    if isinstance(exception, dict):
        values = exception.get("values")
        if isinstance(values, list):
            for v in values:
                if isinstance(v, dict) and isinstance(v.get("value"), str):
                    v["value"] = _scrub_text(v["value"])

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
            before_breadcrumb=scrub_breadcrumb,
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
