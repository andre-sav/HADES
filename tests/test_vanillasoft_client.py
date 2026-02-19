import pytest
from unittest.mock import patch, MagicMock

import requests

from vanillasoft_client import (
    PushResult,
    PushSummary,
    VANILLASOFT_XML_FIELDS,
    _build_xml,
    push_lead,
    push_leads,
)


def test_push_result_success():
    r = PushResult(success=True, lead_name="John Smith", company="Acme", error=None)
    assert r.success is True
    assert r.error is None


def test_push_result_failure():
    r = PushResult(success=False, lead_name="Jane Doe", company="Widgetco", error="missing phone")
    assert r.success is False
    assert r.error == "missing phone"


def test_push_result_carries_person_id():
    """PushResult should carry person_id for unique matching."""
    r = PushResult(success=True, lead_name="John Smith", company="Acme", person_id="123456")
    assert r.person_id == "123456"


def test_push_result_person_id_defaults_none():
    """PushResult person_id should default to None for backwards compat."""
    r = PushResult(success=True, lead_name="John Smith", company="Acme")
    assert r.person_id is None


def test_push_summary_counts():
    ok = PushResult(success=True, lead_name="A", company="B", error=None)
    fail = PushResult(success=False, lead_name="C", company="D", error="err")
    s = PushSummary(succeeded=[ok], failed=[fail], total=2)
    assert len(s.succeeded) == 1
    assert len(s.failed) == 1
    assert s.total == 2


def test_xml_fields_covers_all_mapped_columns():
    """Every non-skipped VanillaSoft column has an XML tag mapping."""
    from utils import VANILLASOFT_COLUMNS
    skipped = {"Square Footage", "Best Appts Time", "Unavailable for appointments"}
    for col in VANILLASOFT_COLUMNS:
        if col not in skipped:
            assert col in VANILLASOFT_XML_FIELDS, f"Missing XML mapping for '{col}'"


def test_build_xml_basic():
    row = {
        "First Name": "John",
        "Last Name": "Smith",
        "Company": "Acme Corp",
        "Email": "john@acme.com",
    }
    xml = _build_xml(row)
    assert "<FirstName>John</FirstName>" in xml
    assert "<LastName>Smith</LastName>" in xml
    assert "<Company>Acme Corp</Company>" in xml
    assert "<Email>john@acme.com</Email>" in xml
    assert xml.startswith("<Lead>")
    assert xml.endswith("</Lead>")


def test_build_xml_escapes_special_chars():
    row = {"Company": "AT&T <Corp>", "First Name": 'O"Brien'}
    xml = _build_xml(row)
    assert "&amp;" in xml
    assert "&lt;" in xml
    assert xml.startswith("<Lead>")


def test_build_xml_skips_empty_fields():
    row = {"First Name": "John", "Last Name": "", "Email": None, "Company": "  "}
    xml = _build_xml(row)
    assert "<FirstName>John</FirstName>" in xml
    assert "LastName" not in xml
    assert "Email" not in xml
    assert "Company" not in xml


def test_build_xml_skips_unmapped_columns():
    """Square Footage etc. should not appear in XML."""
    row = {"Square Footage": "5000", "First Name": "John"}
    xml = _build_xml(row)
    assert "SquareFootage" not in xml
    assert "5000" not in xml
    assert "<FirstName>John</FirstName>" in xml


def test_build_xml_ignores_person_id_metadata():
    """_personId metadata should not appear in XML payload."""
    row = {"First Name": "John", "Company": "Acme", "_personId": "98765"}
    xml = _build_xml(row)
    assert "personId" not in xml.lower()
    assert "98765" not in xml


@pytest.fixture
def sample_row():
    return {
        "First Name": "Andrew",
        "Last Name": "Helmer",
        "Company": "Hershey Entertainment",
        "Email": "ahelmer@hersheypa.com",
        "Business": "(717) 534-3828",
    }


class TestPushLead:
    @patch("vanillasoft_client.requests.post")
    def test_success(self, mock_post, sample_row):
        mock_post.return_value = MagicMock(
            status_code=200,
            text="<ReturnValue>Success</ReturnValue>",
        )
        result = push_lead(sample_row, web_lead_id="test-id-123")
        assert result.success is True
        assert result.lead_name == "Andrew Helmer"
        assert result.company == "Hershey Entertainment"
        assert result.error is None
        mock_post.assert_called_once()
        call_args = mock_post.call_args
        assert "post.aspx" in call_args[0][0]
        assert "id=test-id-123" in call_args[0][0]
        assert "typ=XML" in call_args[0][0]

    @patch("vanillasoft_client.requests.post")
    def test_success_uppercase(self, mock_post, sample_row):
        """VanillaSoft returns SUCCESS in all caps."""
        mock_post.return_value = MagicMock(
            status_code=200,
            text='<ReturnValue>SUCCESS</ReturnValue><ContactID>1199070750</ContactID>',
        )
        result = push_lead(sample_row, web_lead_id="test-id-123")
        assert result.success is True
        assert result.error is None

    @patch("vanillasoft_client.requests.post")
    def test_failure_response(self, mock_post, sample_row):
        mock_post.return_value = MagicMock(
            status_code=200,
            text="<ReturnValue>FAILURE</ReturnValue><ReturnReason>Missing required field: Phone</ReturnReason>",
        )
        result = push_lead(sample_row, web_lead_id="test-id-123")
        assert result.success is False
        assert "Missing required field: Phone" in result.error

    @patch("vanillasoft_client.requests.post")
    def test_http_error(self, mock_post, sample_row):
        mock_post.return_value = MagicMock(status_code=500, text="Internal Server Error")
        result = push_lead(sample_row, web_lead_id="test-id-123")
        assert result.success is False
        assert "HTTP 500" in result.error

    @patch("vanillasoft_client.requests.post")
    def test_timeout(self, mock_post, sample_row):
        mock_post.side_effect = requests.exceptions.Timeout("Connection timed out")
        result = push_lead(sample_row, web_lead_id="test-id-123")
        assert result.success is False
        assert "timed out" in result.error.lower()

    @patch("vanillasoft_client.requests.post")
    def test_network_error(self, mock_post, sample_row):
        mock_post.side_effect = requests.exceptions.ConnectionError("DNS resolution failed")
        result = push_lead(sample_row, web_lead_id="test-id-123")
        assert result.success is False
        assert result.error

    @patch("vanillasoft_client.requests.post")
    def test_person_id_propagated_from_row(self, mock_post):
        """push_lead should extract _personId from row and include in PushResult."""
        mock_post.return_value = MagicMock(
            status_code=200,
            text="<ReturnValue>Success</ReturnValue>",
        )
        row = {"First Name": "John", "Last Name": "Smith", "Company": "Acme", "_personId": "98765"}
        result = push_lead(row, web_lead_id="test-id")
        assert result.person_id == "98765"

    @patch("vanillasoft_client.requests.post")
    def test_person_id_none_when_missing(self, mock_post):
        """push_lead should set person_id=None when _personId not in row."""
        mock_post.return_value = MagicMock(
            status_code=200,
            text="<ReturnValue>Success</ReturnValue>",
        )
        row = {"First Name": "John", "Last Name": "Smith", "Company": "Acme"}
        result = push_lead(row, web_lead_id="test-id")
        assert result.person_id is None


class TestPushLeads:
    @patch("vanillasoft_client.requests.post")
    @patch("vanillasoft_client.time.sleep")
    def test_all_succeed(self, mock_sleep, mock_post):
        mock_post.return_value = MagicMock(
            status_code=200, text="<ReturnValue>Success</ReturnValue>"
        )
        rows = [
            {"First Name": "A", "Last Name": "One", "Company": "C1"},
            {"First Name": "B", "Last Name": "Two", "Company": "C2"},
        ]
        summary = push_leads(rows, web_lead_id="test-id")
        assert summary.total == 2
        assert len(summary.succeeded) == 2
        assert len(summary.failed) == 0

    @patch("vanillasoft_client.requests.post")
    @patch("vanillasoft_client.time.sleep")
    def test_partial_failure(self, mock_sleep, mock_post):
        mock_post.side_effect = [
            MagicMock(status_code=200, text="<ReturnValue>Success</ReturnValue>"),
            MagicMock(status_code=200, text="<ReturnValue>FAILURE</ReturnValue><ReturnReason>bad</ReturnReason>"),
            MagicMock(status_code=200, text="<ReturnValue>Success</ReturnValue>"),
        ]
        rows = [
            {"First Name": "A", "Last Name": "One", "Company": "C1"},
            {"First Name": "B", "Last Name": "Two", "Company": "C2"},
            {"First Name": "C", "Last Name": "Three", "Company": "C3"},
        ]
        summary = push_leads(rows, web_lead_id="test-id")
        assert summary.total == 3
        assert len(summary.succeeded) == 2
        assert len(summary.failed) == 1
        assert summary.failed[0].lead_name == "B Two"

    @patch("vanillasoft_client.requests.post")
    @patch("vanillasoft_client.time.sleep")
    def test_progress_callback(self, mock_sleep, mock_post):
        mock_post.return_value = MagicMock(
            status_code=200, text="<ReturnValue>Success</ReturnValue>"
        )
        rows = [
            {"First Name": "A", "Last Name": "One", "Company": "C1"},
            {"First Name": "B", "Last Name": "Two", "Company": "C2"},
        ]
        progress_calls = []
        summary = push_leads(
            rows, web_lead_id="test-id",
            progress_callback=lambda i, total, result: progress_calls.append((i, total, result.success)),
        )
        assert len(progress_calls) == 2
        assert progress_calls[0] == (1, 2, True)
        assert progress_calls[1] == (2, 2, True)
