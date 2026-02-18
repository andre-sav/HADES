"""
VanillaSoft Incoming Web Leads client.

Pushes leads one-at-a-time via HTTP POST to VanillaSoft's post.aspx endpoint.
Uses XML format for per-lead success/failure feedback.
"""

import time
from dataclasses import dataclass, field
from xml.etree.ElementTree import Element, SubElement, tostring, fromstring

import requests


@dataclass
class PushResult:
    """Result of pushing a single lead to VanillaSoft."""
    success: bool
    lead_name: str
    company: str
    error: str | None = None


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


def _build_xml(row: dict) -> str:
    """Serialize a VanillaSoft row dict to XML for the Incoming Web Leads endpoint.

    Only includes fields that have non-empty values and a mapping in VANILLASOFT_XML_FIELDS.
    Special characters are escaped by ElementTree.
    """
    root = Element("Lead")
    for col_name, xml_tag in VANILLASOFT_XML_FIELDS.items():
        value = row.get(col_name)
        if value is not None and str(value).strip():
            child = SubElement(root, xml_tag)
            child.text = str(value)
    return tostring(root, encoding="unicode")
