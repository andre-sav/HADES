#!/usr/bin/env python3
"""Send a workflow-failure notification email.

Designed to be invoked from a GitHub Actions `if: failure()` step. Reads SMTP
config from env (same secrets the intent pipeline already uses) and emails
EMAIL_RECIPIENTS a plain-text summary with a link to the failed run.

Always exits 0 — failure to send the alert must not chain-fail the workflow
(that would just nest a second alert no one reads).

Usage (in a workflow step):
    - name: Notify on failure
      if: failure()
      env:
        SMTP_USER: ${{ secrets.SMTP_USER }}
        SMTP_PASSWORD: ${{ secrets.SMTP_PASSWORD }}
        EMAIL_RECIPIENTS: ${{ secrets.EMAIL_RECIPIENTS }}
        EMAIL_FROM: ${{ secrets.EMAIL_FROM }}
      run: python scripts/notify_failure.py --workflow "Zoho Operator Sync"
"""

from __future__ import annotations

import argparse
import os
import smtplib
import sys
from email.mime.text import MIMEText

SMTP_HOST = "smtp.gmail.com"
SMTP_PORT = 587


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--workflow", required=True, help="Human-readable workflow name")
    parser.add_argument("--message", default="", help="Optional extra context")
    args = parser.parse_args()

    smtp_user = os.environ.get("SMTP_USER")
    smtp_password = os.environ.get("SMTP_PASSWORD")
    recipients = os.environ.get("EMAIL_RECIPIENTS")

    if not (smtp_user and smtp_password and recipients):
        # No alerting configured — silently no-op. The workflow already failed;
        # GitHub will email the repo owner via its default mechanism.
        print("notify_failure: SMTP secrets not configured, skipping email", file=sys.stderr)
        return 0

    server_url = os.environ.get("GITHUB_SERVER_URL", "https://github.com")
    repo = os.environ.get("GITHUB_REPOSITORY", "")
    run_id = os.environ.get("GITHUB_RUN_ID", "")
    run_attempt = os.environ.get("GITHUB_RUN_ATTEMPT", "")
    ref = os.environ.get("GITHUB_REF_NAME", "")
    sha_short = os.environ.get("GITHUB_SHA", "")[:8]

    run_url = (
        f"{server_url}/{repo}/actions/runs/{run_id}"
        if (server_url and repo and run_id)
        else "(run URL unavailable)"
    )

    body_lines = [
        f"Workflow failed: {args.workflow}",
        "",
        f"Run URL:    {run_url}",
        f"Branch:     {ref or '(unknown)'}",
        f"Commit:     {sha_short or '(unknown)'}",
        f"Attempt:    {run_attempt or '1'}",
        "",
        "Open the run URL to see logs. If this is recurring, check first:",
        "  - SMTP / ZoomInfo / Zoho credential rotation",
        "  - Turso connection health (run: bd doctor against the live DB)",
        "  - GitHub Actions runner availability",
    ]
    if args.message:
        body_lines.extend(["", "Extra context:", args.message])
    body = "\n".join(body_lines)

    msg = MIMEText(body, "plain")
    msg["Subject"] = f"[HADES] Workflow failed: {args.workflow}"
    msg["From"] = os.environ.get("EMAIL_FROM") or smtp_user
    msg["To"] = recipients

    try:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=30) as server:
            server.starttls()
            server.login(smtp_user, smtp_password)
            server.send_message(msg)
        print(f"notify_failure: alert sent to {recipients}", file=sys.stderr)
    except Exception as exc:
        # Belt-and-suspenders: don't chain-fail the workflow if alerting itself fails.
        print(f"notify_failure: send failed ({exc!r}) — workflow log is the source of truth", file=sys.stderr)

    return 0


if __name__ == "__main__":
    sys.exit(main())
