"""Next-scheduled-run arithmetic for the Automation dashboard (HADES-7qi).

Extracted from pages/10_Automation.py so the DST behaviour is testable.

The intent poll is a GitHub Actions cron: `0 12 * * 1-5`. GitHub crons are UTC
and have no DST awareness, so the run lands at 08:00 ET in summer and 07:00 ET
in winter. The dashboard used to hardcode "7:00 AM ET", which was right for
about four months a year and silently an hour out for the other eight — both in
the label and in the countdown the operator plans around.

Deriving everything from the UTC hour keeps the display honest for free.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

try:
    from zoneinfo import ZoneInfo

    ET = ZoneInfo("America/New_York")
except ImportError:  # pragma: no cover - stdlib since 3.9
    ET = timezone(timedelta(hours=-5))

# Must match .github/workflows/intent-poll.yml — `0 12 * * 1-5`.
INTENT_POLL_UTC_HOUR = 12


def next_scheduled_run(now: datetime | None = None) -> tuple[str, str, datetime]:
    """Return (label, countdown, run_at) for the next weekday intent poll.

    `run_at` is timezone-aware in ET; the label renders the ET hour that
    actually applies on that date, so it flips between 7 and 8 AM with DST
    rather than asserting one of them year-round.
    """
    current = now or datetime.now(ET)
    if current.tzinfo is None:
        current = current.replace(tzinfo=ET)

    # Anchor on the UTC hour the cron really fires, then view it in ET.
    utc_now = current.astimezone(timezone.utc)
    candidate = utc_now.replace(
        hour=INTENT_POLL_UTC_HOUR, minute=0, second=0, microsecond=0
    )
    if candidate <= utc_now:
        candidate += timedelta(days=1)
    while candidate.astimezone(ET).weekday() >= 5:
        candidate += timedelta(days=1)

    run_at = candidate.astimezone(ET)

    delta = candidate - utc_now
    total = int(delta.total_seconds())
    hours, minutes = total // 3600, (total % 3600) // 60
    countdown = f"{hours}h {minutes}m" if hours < 24 else f"{hours // 24}d {hours % 24}h"

    hour_12 = run_at.strftime("%I").lstrip("0")
    label = f"{run_at.strftime('%a %b')} {run_at.day} · {hour_12} {run_at.strftime('%p')} ET"
    return label, countdown, run_at
