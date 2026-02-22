# Batch Enrich + exclude_org_exported Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Replace the N+1 enrich loop in Step 3 with a single batch call (~24 credits/run saved), and send `excludeOrgExportedContacts` to the ZoomInfo API so the feature actually works.

**Architecture:** Two isolated fixes in separate files. The batch fix restructures the Step 3 loop in `run_intent_pipeline.py` to collect all PIDs and call `enrich_contacts_batch` once. The exclude fix adds one field to the request body in `zoominfo_client.py`.

**Tech Stack:** Python, ZoomInfo Contact Search + Enrich APIs, pytest

---

### Task 1: Send exclude_org_exported to ZoomInfo API

**Files:**
- Modify: `zoominfo_client.py:815-818` (add field to request body)
- Test: `tests/test_zoominfo_client.py:737-771`

**Step 1: Update the failing test**

In `tests/test_zoominfo_client.py`, the test at line 737 (`test_search_contacts_exclude_org_exported`) currently asserts the field is NOT sent. Change it to assert it IS sent:

```python
def test_search_contacts_exclude_org_exported(self, client):
    """Test exclude_org_exported is sent to ZoomInfo API when True (default)."""
    mock_response = {"data": [], "totalResults": 0}

    with patch.object(client, "_request", return_value=mock_response) as mock_req:
        params = ContactQueryParams(
            zip_codes=["75201"],
            radius_miles=25,
            states=["TX"],
        )
        client.search_contacts(params)

    call_args = mock_req.call_args
    body = call_args[1]["json"]
    assert body["excludeOrgExportedContacts"] is True
```

Also update the test at line 756 (`test_search_contacts_include_org_exported`) to verify the field is absent when set to False:

```python
def test_search_contacts_include_org_exported(self, client):
    """Test exclude_org_exported=False omits the field from request."""
    mock_response = {"data": [], "totalResults": 0}

    with patch.object(client, "_request", return_value=mock_response) as mock_req:
        params = ContactQueryParams(
            zip_codes=["75201"],
            radius_miles=25,
            states=["TX"],
            exclude_org_exported=False,
        )
        client.search_contacts(params)

    call_args = mock_req.call_args
    body = call_args[1]["json"]
    assert "excludeOrgExportedContacts" not in body
```

**Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_zoominfo_client.py -k "exclude_org_exported" -v`
Expected: `test_search_contacts_exclude_org_exported` FAILS (field not in body yet)

**Step 3: Add the field to the request body**

In `zoominfo_client.py`, after the management level filter block (around line 824, after `request_body["managementLevel"] = ...`), add:

```python
# Exclude contacts already exported by this org
if params.exclude_org_exported:
    request_body["excludeOrgExportedContacts"] = True
```

**Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_zoominfo_client.py -k "exclude_org_exported" -v`
Expected: Both PASS

**Step 5: Run full test suite**

Run: `python -m pytest tests/ -x -q --tb=short`
Expected: 581+ passed

**Step 6: Commit**

```bash
git add zoominfo_client.py tests/test_zoominfo_client.py
git commit -m "fix: send excludeOrgExportedContacts to ZoomInfo API

Previously the field existed in ContactQueryParams and cache hash
but was never included in the request body — a silent no-op.

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>"
```

---

### Task 2: Replace N+1 enrich loop with single batch call

**Files:**
- Modify: `scripts/run_intent_pipeline.py:186-215` (replace loop with batch)
- Test: `tests/test_run_intent_pipeline.py`

**Step 1: Update existing test expectations**

The `test_happy_path` test at line 203-211 mocks `enrich_contacts_batch.side_effect` as 3 calls:
- Call 1: resolve company ID for c1 (N+1)
- Call 2: resolve company ID for c2 (N+1)
- Call 3: full enrichment

After batching, it should be 2 calls:
- Call 1: batch resolve ALL company IDs at once
- Call 2: full enrichment

Update `test_happy_path` (line 203-211) to:

```python
client.enrich_contacts_batch.side_effect = [
    # First call: batch resolve ALL company IDs (was N+1, now single batch)
    [
        {"id": "p_c1", "company": {"id": 100, "name": "Acme Corp"}, "companyId": 100},
        {"id": "p_c2", "company": {"id": 200, "name": "Beta Inc"}, "companyId": 200},
    ],
    # Second call: full enrichment
    [_make_contact("p1", "100", "Acme Corp"),
     _make_contact("p2", "200", "Beta Inc")],
]
```

Also add a new test that verifies the batch call uses the correct PIDs and output_fields:

```python
@patch("scripts.run_intent_pipeline.CostTracker")
@patch("scripts.run_intent_pipeline.TursoDatabase")
@patch("scripts.run_intent_pipeline.ZoomInfoClient")
def test_step3_batch_resolves_company_ids(self, MockClient, MockDB, MockCostTracker):
    """Step 3 resolves all uncached company IDs in one batch enrich call."""
    config = _make_config(target_companies=3)
    creds = _make_creds()

    budget = MagicMock()
    budget.alert_level = None
    MockCostTracker.return_value.check_budget.return_value = budget

    client = MockClient.return_value
    client.search_intent_all_pages.return_value = [
        _make_intent_lead("c1", "Acme Corp"),
        _make_intent_lead("c2", "Beta Inc"),
        _make_intent_lead("c3", "Gamma LLC"),
    ]
    client.search_contacts_all_pages.return_value = []
    client.enrich_contacts_batch.return_value = [
        {"id": "p_c1", "company": {"id": 100, "name": "Acme Corp"}, "companyId": 100},
        {"id": "p_c2", "company": {"id": 200, "name": "Beta Inc"}, "companyId": 200},
        {"id": "p_c3", "company": {"id": 300, "name": "Gamma LLC"}, "companyId": 300},
    ]

    db = MockDB.return_value
    db.has_running_pipeline.return_value = False
    db.get_company_ids_bulk.return_value = {}  # Nothing cached
    db.get_exported_company_ids.return_value = {}

    run_pipeline(config, creds)

    # Step 3 should make exactly ONE enrich call for ID resolution (not 3)
    first_enrich_call = client.enrich_contacts_batch.call_args_list[0]
    assert first_enrich_call[1]["person_ids"] == ["p_c1", "p_c2", "p_c3"]
    assert first_enrich_call[1]["output_fields"] == ["id", "companyId", "companyName"]
```

**Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_run_intent_pipeline.py -k "test_happy_path or test_step3_batch" -v`
Expected: FAIL (still N+1 loop)

**Step 3: Replace the N+1 loop with batch call**

In `scripts/run_intent_pipeline.py`, replace lines 190-215 (the `uncached` block) with:

```python
        uncached = [hid for hid in company_ids if hid not in numeric_map]
        if uncached:
            logger.info("Enriching %d contacts to resolve company IDs (%d cached)",
                         len(uncached), len(cached))

            # Collect all PIDs for batch resolution
            pid_to_hid = {}  # person_id → hashed_company_id
            for hid in uncached:
                company_lead = selected_companies[hid]
                recommended = company_lead.get("recommendedContacts") or []
                if not recommended or not isinstance(recommended[0], dict):
                    continue
                pid = recommended[0].get("id")
                if pid:
                    pid_to_hid[str(pid)] = hid

            if pid_to_hid:
                try:
                    enriched = client.enrich_contacts_batch(
                        person_ids=list(pid_to_hid.keys()),
                        output_fields=["id", "companyId", "companyName"],
                    )
                    for contact in enriched:
                        contact_id = str(contact.get("id", ""))
                        hid = pid_to_hid.get(contact_id)
                        if not hid:
                            continue
                        company = contact.get("company", {})
                        numeric_id = company.get("id") or contact.get("companyId")
                        company_name = company.get("name") or contact.get("companyName", "")
                        if numeric_id:
                            numeric_map[hid] = int(numeric_id)
                            db.save_company_id(hid, int(numeric_id), company_name)
                except Exception as e:
                    logger.warning("Batch company ID resolution failed: %s", e)
```

Key changes:
- Collect ALL uncached PIDs into `pid_to_hid` mapping first
- One `enrich_contacts_batch()` call with all PIDs (method handles 25-per-batch internally)
- Map results back to hashed IDs using the `pid_to_hid` lookup
- Single try/except around the batch instead of per-company

**Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_run_intent_pipeline.py -k "test_happy_path or test_step3_batch" -v`
Expected: Both PASS

**Step 5: Run full test suite**

Run: `python -m pytest tests/ -x -q --tb=short`
Expected: 581+ passed

**Step 6: Commit**

```bash
git add scripts/run_intent_pipeline.py tests/test_run_intent_pipeline.py
git commit -m "fix: batch Step 3 company ID resolution (N+1 → single call)

Saves ~24 credits per automated run by collecting all uncached person
IDs and resolving them in one enrich_contacts_batch call instead of
individual calls per company.

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>"
```

---

### Task 3: Final Verification + Close Bead

**Step 1: Run full test suite**

Run: `python -m pytest tests/ -x -q --tb=short`
Expected: All tests pass

**Step 2: Close bead and sync**

```bash
bd close HADES-ect --reason="Batch Step 3 ID resolution (N+1 → 1 call, ~24 credits/run saved) + excludeOrgExportedContacts now sent to API"
bd sync
```
