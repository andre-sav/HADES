"""
VanillaSoft Incoming Web Leads client.

Pushes leads one-at-a-time via HTTP POST to VanillaSoft's post.aspx endpoint.
Uses XML format for per-lead success/failure feedback.
"""

import re
import time
from dataclasses import dataclass, field
from xml.etree.ElementTree import Element, SubElement, tostring, fromstring

import requests

# Control characters that are invalid in XML 1.0 — ElementTree serializes them
# raw, producing documents no conformant parser (including VanillaSoft's) accepts.
_XML_INVALID_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")

BASE_URL = "https://new.vanillasoft.net/post.aspx"
REQUEST_TIMEOUT = 10  # seconds
DELAY_BETWEEN_POSTS = 0.2  # seconds


@dataclass
class PushResult:
    """Result of pushing a single lead to VanillaSoft."""
    success: bool
    lead_name: str
    company: str
    error: str | None = None
    person_id: str | None = None


@dataclass
class PushSummary:
    """Aggregate result of pushing a batch of leads."""
    succeeded: list[PushResult] = field(default_factory=list)
    failed: list[PushResult] = field(default_factory=list)
    total: int = 0


# Maps VanillaSoft column names -> XML tag names for Incoming Web Leads.
# Must match the field mappings configured in VanillaSoft Admin > Incoming Web Lead Profile.
# Skipped: "Square Footage", "Best Appts Time", "Unavailable for appointments" (always empty).
VANILLASOFT_XML_FIELDS = {
    "List Source": "ListSource",
    "Last Name": "LastName",
    "First Name": "FirstName",
    "Title": "Title",
    "Home": "Home",
    "Email": "Email",
    "Mobile": "Mobile",
    "Company": "Company",
    "Web site": "WebSite",
    "Business": "Business",
    "Number of Employees": "Employees",
    "Primary SIC": "PrimarySIC",
    "Primary Line of Business": "LineOfBusiness",
    "Address": "Address",
    "City": "City",
    "State": "State",
    "ZIP code": "ZIPCode",
    "Contact Owner": "ContactOwner",
    "Lead Source": "LeadSource",
    "Vending Business Name": "VendingBusinessName",
    "Operator Name": "OperatorName",
    "Operator Phone #": "OperatorPhone",
    "Operator Email Address": "OperatorEmail",
    "Operator Zip Code": "OperatorZip",
    "Operator Website Address": "OperatorWebsite",
    "Team": "Team",
    "Call Priority": "CallPriority",
    "Import Notes": "ImportNotes",
}


def _build_xml(row: dict) -> bytes:
    """Serialize a VanillaSoft row dict to UTF-8 XML bytes for the Incoming Web Leads endpoint.

    Only includes fields that have non-empty values and a mapping in VANILLASOFT_XML_FIELDS.
    Special characters are escaped by ElementTree; XML-invalid control chars are stripped.

    Returns pre-encoded UTF-8 bytes with an XML declaration: a str body would be
    latin-1-encoded by http.client, raising UnicodeEncodeError on en-dashes/smart
    quotes mid-batch (HADES-kc0) and sending mojibake for latin-1-encodable text.
    """
    root = Element("Lead")
    for col_name, xml_tag in VANILLASOFT_XML_FIELDS.items():
        value = row.get(col_name)
        if value is not None and str(value).strip():
            child = SubElement(root, xml_tag)
            child.text = _XML_INVALID_CHARS.sub("", str(value))
    return tostring(root, encoding="utf-8", xml_declaration=True)


def _parse_response(text: str) -> tuple[bool, str | None]:
    """Parse VanillaSoft XML response. Returns (success, error_reason)."""
    try:
        # Response may not have a single root — wrap it
        wrapped = f"<Response>{text}</Response>"
        root = fromstring(wrapped)
        return_value = root.findtext("ReturnValue", "")
        if return_value.upper() == "SUCCESS":
            return True, None
        reason = root.findtext("ReturnReason", "Unknown error")
        return False, reason
    except Exception:
        # If response isn't parseable XML, check for exact success marker
        if "<ReturnValue>SUCCESS</ReturnValue>" in text or "<ReturnValue>Success</ReturnValue>" in text:
            return True, None
        return False, f"Unparseable response: {text[:200]}"


def push_lead(row: dict, web_lead_id: str) -> PushResult:
    """Push a single lead to VanillaSoft via Incoming Web Leads endpoint."""
    lead_name = f"{row.get('First Name', '')} {row.get('Last Name', '')}".strip()
    company = row.get("Company", "")
    person_id = row.get("_personId")

    try:
        xml_body = _build_xml(row)
    except Exception as e:
        return PushResult(success=False, lead_name=lead_name, company=company, error=f"XML build failed: {e}", person_id=person_id)

    url = f"{BASE_URL}?id={web_lead_id}&typ=XML"

    try:
        resp = requests.post(
            url, data=xml_body,
            headers={"Content-Type": "text/xml; charset=utf-8"},
            timeout=REQUEST_TIMEOUT,
        )
    except requests.exceptions.Timeout:
        return PushResult(success=False, lead_name=lead_name, company=company, error="Request timed out", person_id=person_id)
    except requests.exceptions.ConnectionError as e:
        return PushResult(success=False, lead_name=lead_name, company=company, error=f"Connection error: {e}", person_id=person_id)
    except requests.exceptions.RequestException as e:
        return PushResult(success=False, lead_name=lead_name, company=company, error=str(e), person_id=person_id)
    except Exception as e:
        # One bad lead must never kill the batch: an escaping exception here
        # aborts push_leads before outcome recording, so already-POSTed leads
        # are recorded nowhere and get re-pushed as CRM duplicates (HADES-kc0).
        return PushResult(success=False, lead_name=lead_name, company=company, error=f"Unexpected error: {e}", person_id=person_id)

    if resp.status_code != 200:
        return PushResult(
            success=False, lead_name=lead_name, company=company,
            error=f"HTTP {resp.status_code}: {resp.text[:200]}", person_id=person_id,
        )

    success, reason = _parse_response(resp.text)
    return PushResult(success=success, lead_name=lead_name, company=company, error=reason, person_id=person_id)


def push_leads(rows: list[dict], web_lead_id: str, progress_callback=None) -> PushSummary:
    """Push a batch of leads to VanillaSoft sequentially."""
    summary = PushSummary(total=len(rows))

    for i, row in enumerate(rows):
        result = push_lead(row, web_lead_id)

        if result.success:
            summary.succeeded.append(result)
        else:
            summary.failed.append(result)

        if progress_callback:
            progress_callback(i + 1, len(rows), result)

        # Delay between requests (skip after last)
        if i < len(rows) - 1:
            time.sleep(DELAY_BETWEEN_POSTS)

    return summary
