#!/usr/bin/env python3
"""Post-deploy synthetic check — is the deployed app actually serving? (HADES-704)

The Executive Summary crash went undetected from deploy until someone happened
to click the page. A scheduled probe bounds that detection window regardless of
whether anyone is using the app.

WHAT IT PROBES, AND WHY THAT ENDPOINT
-------------------------------------
``/_stcore/health`` is the Streamlit **app server's** own health endpoint. It
answers a bare ``ok`` while the app process is up, and stops answering when the
app is down, asleep, or failed to deploy.

It is emphatically NOT ``/healthz``. Verified live on 2026-07-27: ``/healthz``
returns 200 ``{"status":"ok"}`` from Streamlit Cloud's edge for *any* hostname —
a subdomain with no app behind it answers identically. A check built on it can
never fail, which is worse than no check at all.

WHAT IT DOES NOT COVER
----------------------
A single page erroring in-session while the server stays up — the exact shape of
the Executive Summary crash. That class is caught before deploy by
tests/test_page_imports.py (HADES-0h1). This check covers the app-level outage
that no test can catch: a bad deploy, a crashed container, a sleeping app.

WHY THIS FILE IS SELF-CONTAINED
-------------------------------
The verdict logic lives here rather than in monitoring.py, breaking that
module's usual "pure evaluators live together" convention on purpose: importing
monitoring pulls utils -> streamlit, so the workflow would have to pip-install
the whole application on every run. A monitor that depends on the system it
monitors goes red when *requirements* break rather than when the app does, and
that false alarm is precisely what erodes trust in the channel. Stdlib only,
no install step, unit-tested from tests/test_synthetic_check.py.

Usage:
    python scripts/synthetic_check.py [--url https://hades-hlm.streamlit.app]

Exit codes:
    0  app healthy
    1  app unhealthy — the red workflow run is the alert, and the workflow's
       ``if: failure()`` step emails via scripts/notify_failure.py
"""

from __future__ import annotations

import argparse
import os
import sys
import time
import urllib.error
import urllib.request

DEFAULT_URL = "https://hades-hlm.streamlit.app"

# The app server's own endpoint. See the module docstring before changing this —
# /healthz looks equivalent and is not.
HEALTH_PATH = "/_stcore/health"

DEFAULT_ATTEMPTS = 3
DEFAULT_BACKOFF_SECONDS = 5
DEFAULT_TIMEOUT_SECONDS = 20

_STREAMLIT_AUTH_HOST = "share.streamlit.io"


def evaluate_synthetic_probe(status, body, *, location=None, error=None) -> dict:
    """Turn one HTTP probe of /_stcore/health into a verdict.

    Everything that is not a healthy app is "critical" — this check exists to
    bound outage detection time, and a synthetic probe has no ambiguous middle
    ground worth a softer severity.
    """
    if error:
        return {"severity": "critical", "message": f"App unreachable: {error}"}

    if status is not None and 300 <= status < 400:
        target = location or "(no Location header)"
        if _STREAMLIT_AUTH_HOST in target:
            return {
                "severity": "critical",
                "message": (
                    f"App redirected to Streamlit viewer auth ({target}) — the "
                    "synthetic check cannot reach it. Set Streamlit Cloud -> "
                    "Settings -> Sharing back to public; APP_PASSWORD remains "
                    "the gate on the app itself."
                ),
            }
        return {
            "severity": "critical",
            "message": f"App redirected ({status}) to {target}.",
        }

    if status != 200:
        return {
            "severity": "critical",
            "message": f"App health endpoint returned HTTP {status}.",
        }

    payload = (body or "").strip().lower()
    if payload != "ok":
        return {
            "severity": "critical",
            "message": (
                f"App health endpoint returned 200 with unexpected body "
                f"{(body or '')[:80]!r} — expected a bare 'ok'. A JSON payload "
                "here means the probe hit Streamlit's edge /healthz, which "
                "answers for nonexistent apps too."
            ),
        }

    return {"severity": "ok", "message": "App health endpoint responded 'ok'."}


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """Surface 3xx instead of following it.

    Following the redirect would replace the viewer-auth signal with whatever
    the auth host happens to serve, losing the one response that names the
    actual problem.
    """

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _fetch(url: str, timeout: float):
    """One HTTP GET. Returns (status, body, location)."""
    opener = urllib.request.build_opener(_NoRedirect)
    try:
        with opener.open(url, timeout=timeout) as response:
            return (
                response.status,
                response.read().decode("utf-8", "replace"),
                response.headers.get("Location"),
            )
    except urllib.error.HTTPError as exc:  # 3xx (unfollowed), 4xx, 5xx
        return (
            exc.code,
            exc.read().decode("utf-8", "replace"),
            exc.headers.get("Location"),
        )


def probe(
    base_url: str,
    *,
    attempts: int = DEFAULT_ATTEMPTS,
    backoff_seconds: float = DEFAULT_BACKOFF_SECONDS,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
) -> dict:
    """Probe the app's health endpoint, retrying transient failures.

    Retries matter on a 15-minute cron: a single dropped connection, or a cold
    start after the app has been idle, must not page anyone. Only a failure
    that survives every attempt is reported.
    """
    url = base_url.rstrip("/") + HEALTH_PATH
    verdict = {"severity": "critical", "message": "probe never ran"}

    for attempt in range(1, attempts + 1):
        try:
            status, body, location = _fetch(url, timeout)
            verdict = evaluate_synthetic_probe(status, body, location=location)
        except Exception as exc:
            verdict = evaluate_synthetic_probe(None, None, error=str(exc))

        if verdict["severity"] == "ok":
            return verdict
        if attempt < attempts:
            print(f"  attempt {attempt}/{attempts} failed: {verdict['message']}")
            time.sleep(backoff_seconds)

    return verdict


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--url",
        default=os.getenv("APP_URL", DEFAULT_URL),
        help="Base URL of the deployed app (default: %(default)s)",
    )
    parser.add_argument("--attempts", type=int, default=DEFAULT_ATTEMPTS)
    parser.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT_SECONDS)
    args = parser.parse_args(argv)

    print(f"Probing {args.url.rstrip('/')}{HEALTH_PATH} ...")
    verdict = probe(args.url, attempts=args.attempts, timeout=args.timeout)

    if verdict["severity"] == "ok":
        print(f"OK: {verdict['message']}")
        return 0

    print(f"FAIL: {verdict['message']}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
