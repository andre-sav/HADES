# VanillaSoft Direct Push — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Push leads directly to VanillaSoft from the Export page via their Incoming Web Leads HTTP endpoint, with per-lead progress tracking and retry support.

**Architecture:** Reuse `build_vanillasoft_row()` to produce the same 31-column dict, serialize to XML, POST one lead at a time to `post.aspx?id={WebLeadID}&typ=XML`. Sequential with progress bar. CSV download stays as fallback.

**Tech Stack:** Python `requests` for HTTP, `xml.etree.ElementTree` for XML serialization/parsing, Streamlit progress bar + status log for UI.

**Design doc:** `docs/plans/2026-02-17-vanillasoft-push-design.md`

---

### Task 1: VanillaSoft Client — Data Classes & XML Serialization

**Files:**
- Create: `vanillasoft_client.py`
- Create: `tests/test_vanillasoft_client.py`

**Step 1: Write failing tests for PushResult, PushSummary, and XML serialization**

```python
# tests/test_vanillasoft_client.py
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
```

**Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_vanillasoft_client.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'vanillasoft_client'`

**Step 3: Implement data classes, XML field mapping, and `_build_xml()`**

```python
# vanillasoft_client.py
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


# Maps VanillaSoft column names → XML tag names for Incoming Web Leads.
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
```

**Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_vanillasoft_client.py -v`
Expected: All 8 tests PASS

**Step 5: Commit**

```bash
git add vanillasoft_client.py tests/test_vanillasoft_client.py
git commit -m "feat: VanillaSoft client — data classes and XML serialization"
```

---

### Task 2: VanillaSoft Client — push_lead() and push_leads()

**Files:**
- Modify: `vanillasoft_client.py`
- Modify: `tests/test_vanillasoft_client.py`

**Step 1: Write failing tests for push_lead() and push_leads()**

Add to `tests/test_vanillasoft_client.py`:

```python
from unittest.mock import patch, MagicMock
from vanillasoft_client import push_lead, push_leads


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
    """Tests for push_lead() — single lead POST."""

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

        # Verify POST was called with correct URL and XML body
        mock_post.assert_called_once()
        call_args = mock_post.call_args
        assert "post.aspx" in call_args[0][0]
        assert "id=test-id-123" in call_args[0][0]
        assert "typ=XML" in call_args[0][0]

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
        assert result.error  # Has some error message


class TestPushLeads:
    """Tests for push_leads() — batch push with progress."""

    @patch("vanillasoft_client.requests.post")
    @patch("vanillasoft_client.time.sleep")  # Skip delays in tests
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
```

**Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_vanillasoft_client.py -v -k "TestPushLead or TestPushLeads"`
Expected: FAIL — `ImportError: cannot import name 'push_lead' from 'vanillasoft_client'`

**Step 3: Implement push_lead() and push_leads()**

Add to `vanillasoft_client.py`:

```python
BASE_URL = "https://new.vanillasoft.net/post.aspx"
REQUEST_TIMEOUT = 10  # seconds
DELAY_BETWEEN_POSTS = 0.2  # seconds


def _parse_response(text: str) -> tuple[bool, str | None]:
    """Parse VanillaSoft XML response. Returns (success, error_reason)."""
    try:
        # Response may not have a single root — wrap it
        wrapped = f"<Response>{text}</Response>"
        root = fromstring(wrapped)
        return_value = root.findtext("ReturnValue", "")
        if return_value == "Success":
            return True, None
        reason = root.findtext("ReturnReason", "Unknown error")
        return False, reason
    except Exception:
        # If response isn't parseable XML, treat as failure
        if "Success" in text:
            return True, None
        return False, f"Unparseable response: {text[:200]}"


def push_lead(row: dict, web_lead_id: str) -> PushResult:
    """Push a single lead to VanillaSoft via Incoming Web Leads endpoint.

    Args:
        row: VanillaSoft row dict (output of build_vanillasoft_row()).
        web_lead_id: The WebLeadID from VanillaSoft Admin > Incoming Web Leads.

    Returns:
        PushResult with success/failure status and any error message.
    """
    lead_name = f"{row.get('First Name', '')} {row.get('Last Name', '')}".strip()
    company = row.get("Company", "")

    xml_body = _build_xml(row)
    url = f"{BASE_URL}?id={web_lead_id}&typ=XML"

    try:
        resp = requests.post(
            url,
            data=xml_body,
            headers={"Content-Type": "text/xml"},
            timeout=REQUEST_TIMEOUT,
        )
    except requests.exceptions.Timeout:
        return PushResult(success=False, lead_name=lead_name, company=company, error="Request timed out")
    except requests.exceptions.ConnectionError as e:
        return PushResult(success=False, lead_name=lead_name, company=company, error=f"Connection error: {e}")
    except requests.exceptions.RequestException as e:
        return PushResult(success=False, lead_name=lead_name, company=company, error=str(e))

    if resp.status_code != 200:
        return PushResult(
            success=False, lead_name=lead_name, company=company,
            error=f"HTTP {resp.status_code}: {resp.text[:200]}",
        )

    success, reason = _parse_response(resp.text)
    return PushResult(success=success, lead_name=lead_name, company=company, error=reason)


def push_leads(
    rows: list[dict],
    web_lead_id: str,
    progress_callback=None,
) -> PushSummary:
    """Push a batch of leads to VanillaSoft sequentially.

    Args:
        rows: List of VanillaSoft row dicts.
        web_lead_id: The WebLeadID from VanillaSoft Admin.
        progress_callback: Optional callable(current: int, total: int, result: PushResult).

    Returns:
        PushSummary with succeeded/failed lists.
    """
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
```

**Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_vanillasoft_client.py -v`
Expected: All 16 tests PASS

**Step 5: Commit**

```bash
git add vanillasoft_client.py tests/test_vanillasoft_client.py
git commit -m "feat: VanillaSoft push_lead() and push_leads() with progress callback"
```

---

### Task 3: DB Schema — Push Tracking Columns on staged_exports

**Files:**
- Modify: `turso_db.py:221-231` (staged_exports CREATE TABLE)
- Modify: `turso_db.py:841-846` (mark_staged_exported)
- Add new method: `turso_db.py` — `mark_staged_pushed()`
- Modify: `tests/test_turso_db.py`

**Step 1: Write failing tests for push tracking**

Add to `tests/test_turso_db.py`:

```python
def test_mark_staged_pushed_complete(db):
    """mark_staged_pushed updates push_status, pushed_at, push_results_json."""
    export_id = db.save_staged_export("geography", [{"name": "test"}])
    results_json = '{"succeeded": 5, "failed": 0}'
    db.mark_staged_pushed(export_id, "complete", results_json)

    row = db.get_staged_export(export_id)
    assert row["push_status"] == "complete"
    assert row["pushed_at"] is not None
    assert row["push_results_json"] == results_json


def test_mark_staged_pushed_partial(db):
    """Partial push stores failed lead details for retry."""
    export_id = db.save_staged_export("intent", [{"name": "test"}])
    results_json = '{"succeeded": 3, "failed": 2, "failed_indices": [1, 4]}'
    db.mark_staged_pushed(export_id, "partial", results_json)

    row = db.get_staged_export(export_id)
    assert row["push_status"] == "partial"
    assert row["push_results_json"] == results_json


def test_get_staged_export_includes_push_fields(db):
    """get_staged_export returns push_status, pushed_at, push_results_json."""
    export_id = db.save_staged_export("geography", [{"name": "test"}])
    row = db.get_staged_export(export_id)
    assert row["push_status"] is None
    assert row["pushed_at"] is None
    assert row["push_results_json"] is None
```

**Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_turso_db.py -v -k "push"`
Expected: FAIL — `mark_staged_pushed` not found / push columns not in result

**Step 3: Add push columns to schema and implement mark_staged_pushed()**

In `turso_db.py`, update the `staged_exports` CREATE TABLE (line 221):

```python
            CREATE TABLE IF NOT EXISTS staged_exports (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                workflow_type TEXT NOT NULL,
                leads_json TEXT NOT NULL,
                lead_count INTEGER NOT NULL,
                query_params TEXT,
                operator_id INTEGER,
                batch_id TEXT,
                exported_at TEXT,
                push_status TEXT,
                pushed_at TEXT,
                push_results_json TEXT,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
```

Since schema is self-creating with `CREATE TABLE IF NOT EXISTS`, the new columns won't appear on existing tables. Add ALTER TABLE migration calls in `init_schema()` after the CREATE TABLE (safe to run repeatedly):

```python
            # Migrate: add push columns to staged_exports (idempotent)
            "ALTER TABLE staged_exports ADD COLUMN push_status TEXT",
            "ALTER TABLE staged_exports ADD COLUMN pushed_at TEXT",
            "ALTER TABLE staged_exports ADD COLUMN push_results_json TEXT",
```

Wrap each ALTER in try/except to ignore "duplicate column" errors (SQLite throws on re-add). Or use the existing pattern if one exists in the codebase.

Update `get_staged_export()` (line 818) to SELECT and return the 3 new columns.

Add `mark_staged_pushed()` method:

```python
    def mark_staged_pushed(self, export_id: int, push_status: str, push_results_json: str) -> None:
        """Record push results on a staged export."""
        self.execute_write(
            "UPDATE staged_exports SET push_status = ?, pushed_at = CURRENT_TIMESTAMP, push_results_json = ? WHERE id = ?",
            (push_status, push_results_json, export_id),
        )
```

**Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_turso_db.py -v -k "push"`
Expected: 3 tests PASS

Also run full suite: `python -m pytest tests/ -x -q --tb=short`
Expected: All tests pass (existing staged_exports tests still work)

**Step 5: Commit**

```bash
git add turso_db.py tests/test_turso_db.py
git commit -m "feat: staged_exports push tracking columns and mark_staged_pushed()"
```

---

### Task 4: Secrets Configuration

**Files:**
- Modify: `.streamlit/secrets.toml.template`

**Step 1: Add VanillaSoft secret placeholder to template**

Add to `.streamlit/secrets.toml.template`:

```toml
# VanillaSoft Incoming Web Leads
# Get WebLeadID from: VanillaSoft Admin > Integration > Incoming Web Leads > Add
VANILLASOFT_WEB_LEAD_ID = "your-web-lead-id"
```

**Step 2: Commit**

```bash
git add .streamlit/secrets.toml.template
git commit -m "docs: add VANILLASOFT_WEB_LEAD_ID to secrets template"
```

---

### Task 5: Export Page — Push to VanillaSoft Button & Flow

**Files:**
- Modify: `pages/4_CSV_Export.py:305-415` (Export section)

**Step 1: Add VanillaSoft push import and secret check**

At top of `pages/4_CSV_Export.py`, add import:

```python
from vanillasoft_client import push_leads, PushSummary
```

After the existing secret/DB setup (around line 38), add:

```python
# Check for VanillaSoft push capability
import streamlit as st
_vs_web_lead_id = st.secrets.get("VANILLASOFT_WEB_LEAD_ID")
_vs_push_available = bool(_vs_web_lead_id and _vs_web_lead_id != "your-web-lead-id")
```

**Step 2: Replace the Export section (lines 305-415)**

Replace the current `EXPORT + MARK EXPORTED` section with the new layout:

```python
# =============================================================================
# EXPORT — Push to VanillaSoft + CSV Download
# =============================================================================
st.markdown("---")

agents = get_call_center_agents()

# Build rows (cached to avoid batch_id DB writes on rerun)
_export_cache_key = (
    tuple(l.get("personId", l.get("companyId", i)) for i, l in enumerate(leads_to_export)),
    selected_operator.get("id") if selected_operator else None,
    workflow_type,
)
if st.session_state.get("_export_cache_key") != _export_cache_key:
    csv_content, filename, batch_id = export_leads_to_csv(
        leads_to_export,
        operator=selected_operator,
        workflow_type=workflow_type,
        db=db,
        agents=agents,
    )
    st.session_state["_export_cache_key"] = _export_cache_key
    st.session_state["_export_cached"] = (csv_content, filename, batch_id)
else:
    csv_content, filename, batch_id = st.session_state["_export_cached"]

# Build VanillaSoft rows for push (same data as CSV, just dict form)
from export import build_vanillasoft_row
vs_rows = []
for i, lead in enumerate(leads_to_export):
    contact_owner = agents[i % len(agents)] if agents else ""
    vs_rows.append(build_vanillasoft_row(
        lead, selected_operator, batch_id=batch_id, contact_owner=contact_owner,
    ))

# Post-push/export display
if st.session_state.get("last_export_metadata"):
    meta = st.session_state.last_export_metadata
    op_name = meta.get("operator") or ""
    op_display = f" for {op_name}" if op_name else ""
    ts = meta.get("timestamp", "")[:16] if meta.get("timestamp") else ""
    batch_display = f" · {meta.get('batch_id')}" if meta.get("batch_id") else ""
    method = meta.get("method", "Exported")
    st.success(f"{method}: {meta.get('filename', '')} · {meta.get('count', 0)} leads{op_display}{batch_display} · {ts}")

# Buttons
col1, col2, col3 = st.columns([2, 1, 1])

with col1:
    st.caption(f"Ready: {len(leads_to_export)} leads" + (f" for {selected_operator['operator_name']}" if selected_operator else ""))

with col2:
    push_clicked = st.button(
        "📤 Push to VanillaSoft",
        type="primary",
        use_container_width=True,
        disabled=not _vs_push_available,
        help=None if _vs_push_available else "Configure VANILLASOFT_WEB_LEAD_ID in secrets",
    )

with col3:
    st.download_button(
        "💾 Download CSV",
        data=csv_content,
        file_name=filename,
        mime="text/csv",
        use_container_width=True,
    )

# Push flow
if push_clicked and _vs_push_available:
    progress_bar = st.progress(0, text="Pushing to VanillaSoft...")
    log_container = st.container()

    def _on_progress(current, total, result):
        progress_bar.progress(current / total, text=f"Pushing to VanillaSoft... {current}/{total}")
        icon = "✔" if result.success else "✖"
        err = f" ({result.error})" if result.error else ""
        log_container.caption(f"{icon} {result.lead_name} — {result.company}{err}")

    summary = push_leads(vs_rows, web_lead_id=_vs_web_lead_id, progress_callback=_on_progress)

    progress_bar.empty()

    # Summary banner
    if summary.failed:
        st.warning(f"Push complete: {len(summary.succeeded)}/{summary.total} succeeded, {len(summary.failed)} failed")
    else:
        st.success(f"All {summary.total} leads pushed to VanillaSoft")

    # Record outcomes for successful leads
    if batch_id:
        now_iso = datetime.now().isoformat()
        # Build index mapping: vs_rows index → leads_to_export index
        succeeded_names = {(r.lead_name, r.company) for r in summary.succeeded}
        outcome_rows = []
        for i, lead in enumerate(leads_to_export):
            name = f"{lead.get('firstName', '')} {lead.get('lastName', '')}".strip()
            company = lead.get("companyName", "")
            if (name, company) in succeeded_names:
                features = {k: v for k, v in lead.items() if k.startswith("_") and v is not None}
                outcome_rows.append((
                    batch_id,
                    company,
                    str(lead.get("companyId", "")) if lead.get("companyId") else None,
                    str(lead.get("personId", "")) if lead.get("personId") else None,
                    lead.get("sicCode") or lead.get("_sic_code"),
                    lead.get("employees") or lead.get("numberOfEmployees"),
                    lead.get("_distance_miles"),
                    lead.get("zip") or lead.get("zipCode"),
                    lead.get("state"),
                    lead.get("_score"),
                    workflow_type,
                    now_iso,
                    json.dumps(features) if features else None,
                ))
        if outcome_rows:
            db.record_lead_outcomes_batch(outcome_rows)

    # Update query log
    last_query = db.get_last_query(workflow_type)
    if last_query:
        db.update_query_exported(last_query["id"], len(summary.succeeded))

    # Mark staged export
    staged_id = st.session_state.get("_loaded_staged_id")
    push_status = "complete" if not summary.failed else "partial"
    push_results = json.dumps({
        "succeeded": [{"name": r.lead_name, "company": r.company} for r in summary.succeeded],
        "failed": [{"name": r.lead_name, "company": r.company, "error": r.error} for r in summary.failed],
    })
    if staged_id and batch_id:
        db.mark_staged_exported(staged_id, batch_id)
        db.mark_staged_pushed(staged_id, push_status, push_results)

    # Store metadata
    st.session_state.last_export_metadata = {
        "filename": f"Push {batch_id}" if batch_id else "Push",
        "count": len(summary.succeeded),
        "timestamp": datetime.now().isoformat(),
        "operator": selected_operator.get("operator_name") if selected_operator else None,
        "batch_id": batch_id,
        "method": "Pushed to VanillaSoft",
    }
    if workflow_type == "intent":
        st.session_state["intent_exported"] = True
    else:
        st.session_state["geo_exported"] = True

    # Failed leads — retry + CSV fallback
    if summary.failed:
        st.markdown("---")
        st.markdown(f"**Failed ({len(summary.failed)}):**")
        for r in summary.failed:
            st.caption(f"✖ {r.lead_name} — {r.company} ({r.error})")

        fcol1, fcol2 = st.columns(2)
        with fcol1:
            if st.button("🔄 Retry Failed", use_container_width=True):
                failed_indices = []
                for i, row in enumerate(vs_rows):
                    name = f"{row.get('First Name', '')} {row.get('Last Name', '')}".strip()
                    company = row.get("Company", "")
                    if any(r.lead_name == name and r.company == company for r in summary.failed):
                        failed_indices.append(i)
                st.session_state["_retry_rows"] = [vs_rows[i] for i in failed_indices]
                st.rerun()
        with fcol2:
            # Build CSV of just the failed leads
            failed_names = {(r.lead_name, r.company) for r in summary.failed}
            failed_csv_rows = [
                r for r in vs_rows
                if (f"{r.get('First Name', '')} {r.get('Last Name', '')}".strip(), r.get("Company", "")) in failed_names
            ]
            if failed_csv_rows:
                import csv as csv_mod, io
                out = io.StringIO()
                from utils import VANILLASOFT_COLUMNS
                writer = csv_mod.DictWriter(out, fieldnames=VANILLASOFT_COLUMNS)
                writer.writeheader()
                for r in failed_csv_rows:
                    writer.writerow(r)
                st.download_button(
                    "💾 Download Failed as CSV",
                    data=out.getvalue(),
                    file_name=f"HADES-failed-{datetime.now().strftime('%Y%m%d-%H%M%S')}.csv",
                    mime="text/csv",
                    use_container_width=True,
                )
```

**Step 3: Run full test suite**

Run: `python -m pytest tests/ -x -q --tb=short`
Expected: All tests pass (this is a UI change — no new unit tests needed beyond the client tests already written)

**Step 4: Commit**

```bash
git add pages/4_CSV_Export.py
git commit -m "feat: Push to VanillaSoft button on Export page with progress + retry"
```

---

### Task 6: Update Header, Secrets Template, and CLAUDE.md

**Files:**
- Modify: `pages/4_CSV_Export.py:48` (page header)
- Modify: `CLAUDE.md`

**Step 1: Update page header**

Change line 48:

```python
page_header("Export", "Push leads to VanillaSoft or download CSV")
```

**Step 2: Update CLAUDE.md**

Add to the "Secrets required" section:

```toml
VANILLASOFT_WEB_LEAD_ID = "..."     # VanillaSoft Incoming Web Leads profile ID
```

Add to the file structure:

```
├── vanillasoft_client.py  # VanillaSoft Incoming Web Leads push client
```

Update test count after confirming final number.

**Step 3: Run full test suite**

Run: `python -m pytest tests/ -x -q --tb=short`
Expected: All tests pass

**Step 4: Commit**

```bash
git add pages/4_CSV_Export.py CLAUDE.md
git commit -m "docs: update header and CLAUDE.md for VanillaSoft push"
```

---

### Task 7: Final Verification

**Step 1: Run full test suite**

Run: `python -m pytest tests/ -v`
Expected: All tests pass, count increased by ~19 (8 XML + 8 push + 3 DB)

**Step 2: Verify app starts**

Run: `streamlit run app.py` (manual check — Export page loads, push button shows disabled if no secret configured)

**Step 3: Final commit with test count update**

```bash
git add -A
git commit -m "feat: VanillaSoft direct push — complete implementation"
```
