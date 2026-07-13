"""Tests for scripts/check_zoominfo_health.py exit-code semantics (HADES-2oe).

A critical verdict whose alert email cannot be delivered must FAIL the run —
otherwise the condition vanishes into a green scheduled workflow.
"""

import sys
from unittest.mock import MagicMock, patch

# Mock Streamlit and libsql before importing modules
sys.modules["streamlit"] = MagicMock()
sys.modules["libsql_experimental"] = MagicMock()

import scripts.check_zoominfo_health as health


def _run_main(severity: str, alert_sent: bool) -> int:
    verdict = {"severity": severity, "message": "msg", "breaches": []}
    with patch.object(health, "ZoomInfoClient"), \
         patch.object(health, "evaluate_usage", return_value=verdict), \
         patch.object(health, "send_alert", return_value=alert_sent) as mock_alert, \
         patch("scripts._credentials.load_credentials", return_value={
             "ZOOMINFO_CLIENT_ID": "x", "ZOOMINFO_CLIENT_SECRET": "y",
         }):
        code = health.main()
    return code, mock_alert


def test_ok_verdict_exits_zero():
    code, mock_alert = _run_main("ok", alert_sent=False)
    assert code == 0
    mock_alert.assert_not_called()


def test_critical_with_delivered_alert_exits_zero():
    """The email IS the signal — delivered alert means green run."""
    code, mock_alert = _run_main("critical", alert_sent=True)
    assert code == 0
    mock_alert.assert_called_once()


def test_critical_with_undeliverable_alert_exits_nonzero():
    """SMTP unconfigured + critical verdict must NOT be a green run."""
    code, _ = _run_main("critical", alert_sent=False)
    assert code == 1


def test_unknown_with_undeliverable_alert_exits_nonzero():
    code, _ = _run_main("unknown", alert_sent=False)
    assert code == 1


def test_warning_with_undeliverable_alert_stays_green():
    """Warnings are advisory; only critical/unknown force a red run."""
    code, _ = _run_main("warning", alert_sent=False)
    assert code == 0
