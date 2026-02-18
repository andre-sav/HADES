import pytest
from vanillasoft_client import (
    PushResult,
    PushSummary,
    VANILLASOFT_XML_FIELDS,
    _build_xml,
)


def test_push_result_success():
    r = PushResult(success=True, lead_name="John Smith", company="Acme", error=None)
    assert r.success is True
    assert r.error is None


def test_push_result_failure():
    r = PushResult(success=False, lead_name="Jane Doe", company="Widgetco", error="missing phone")
    assert r.success is False
    assert r.error == "missing phone"


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
