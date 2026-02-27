# Company Enrich Integration — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add Company Enrich API support so SIC code, industry, and employee count appear in VanillaSoft exports.

**Architecture:** New `enrich_companies()` / `enrich_companies_batch()` methods in `zoominfo_client.py` call `POST /enrich/company`. A helper `merge_company_data()` in `export.py` maps the API response fields (`sicCodes`, `primaryIndustry`, `employeeCount`) onto lead dicts using VanillaSoft-compatible keys (`sicCode`, `industry`, `employeeCount`). All 3 pipeline paths and the backfill script call this after Contact Enrich.

**Tech Stack:** Python, ZoomInfo REST API, pytest

**Design doc:** `docs/plans/2026-02-26-company-enrich-design.md`

---

### Task 1: Company Enrich API methods in zoominfo_client.py

**Files:**
- Modify: `zoominfo_client.py:100-142` (add dataclass + constant after existing Contact Enrich params)
- Modify: `zoominfo_client.py:1189` (add methods after `enrich_contacts` method)
- Test: `tests/test_zoominfo_client.py`

**Step 1: Write failing tests**

Add after the `TestContactEnrich` class (around line 1160):

```python
class TestCompanyEnrich:
    """Tests for Company Enrich API response parsing."""

    @pytest.fixture
    def client(self):
        client = ZoomInfoClient("id", "secret")
        client._get_token = MagicMock(return_value="token")
        return client

    def test_enrich_companies_parses_response(self, client):
        """Company Enrich returns {data: {result: [{input, data: [company], matchStatus}]}}."""
        mock_response = {
            "success": True,
            "data": {
                "outputFields": [["id", "name", "employeeCount", "sicCodes", "primaryIndustry"]],
                "result": [
                    {
                        "input": {"companyid": "369577586"},
                        "data": [
                            {
                                "id": 369577586,
                                "name": "BaneCare",
                                "employeeCount": 144,
                                "sicCodes": [
                                    {"id": "80", "name": "Health Services"},
                                    {"id": "805", "name": "Nursing And Personal Care Facilities"},
                                    {"id": "8051", "name": "Skilled Nursing Care Facilities"},
                                ],
                                "primaryIndustry": ["Hospitals & Physicians Clinics"],
                            }
                        ],
                        "matchStatus": "FULL_MATCH",
                    }
                ],
            },
        }

        with patch.object(client, "_request", return_value=mock_response):
            params = CompanyEnrichParams(company_ids=["369577586"])
            result = client.enrich_companies(params)

        assert len(result["data"]) == 1
        company = result["data"][0]
        assert company["id"] == 369577586
        assert company["name"] == "BaneCare"
        assert company["employeeCount"] == 144
        assert company["sicCodes"][-1]["id"] == "8051"
        assert company["primaryIndustry"][0] == "Hospitals & Physicians Clinics"

    def test_enrich_companies_no_match(self, client):
        """Companies that don't match should not appear in results."""
        mock_response = {
            "success": True,
            "data": {
                "outputFields": [["id", "name"]],
                "result": [
                    {
                        "input": {"companyid": "999999"},
                        "data": [],
                        "matchStatus": "NO_MATCH",
                    }
                ],
            },
        }

        with patch.object(client, "_request", return_value=mock_response):
            params = CompanyEnrichParams(company_ids=["999999"])
            result = client.enrich_companies(params)

        assert len(result["data"]) == 0

    def test_enrich_companies_batch(self, client):
        """Batch splits into groups of 25 and aggregates results."""
        def mock_request(method, endpoint, json=None, **kwargs):
            ids = [item["companyId"] for item in json["matchCompanyInput"]]
            return {
                "success": True,
                "data": {
                    "result": [
                        {
                            "input": {"companyid": cid},
                            "data": [{"id": int(cid), "name": f"Company {cid}", "employeeCount": 100}],
                            "matchStatus": "FULL_MATCH",
                        }
                        for cid in ids
                    ],
                },
            }

        with patch.object(client, "_request", side_effect=mock_request):
            # 30 companies → 2 batches (25 + 5)
            company_ids = [str(i) for i in range(30)]
            result = client.enrich_companies_batch(company_ids, batch_size=25)

        assert len(result) == 30

    def test_enrich_companies_request_body(self, client):
        """Verify request body format matches ZoomInfo API spec."""
        mock_response = {"success": True, "data": {"result": []}}

        with patch.object(client, "_request", return_value=mock_response) as mock_req:
            params = CompanyEnrichParams(company_ids=["111", "222"])
            client.enrich_companies(params)

        call_args = mock_req.call_args
        body = call_args[1]["json"] if "json" in call_args[1] else call_args[0][2]
        assert body["matchCompanyInput"] == [{"companyId": "111"}, {"companyId": "222"}]
        assert "outputFields" in body
```

Add import at top of test file: `from zoominfo_client import CompanyEnrichParams` (alongside existing `ContactEnrichParams` import).

**Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_zoominfo_client.py::TestCompanyEnrich -v`
Expected: FAIL — `ImportError: cannot import name 'CompanyEnrichParams'`

**Step 3: Write implementation**

In `zoominfo_client.py`, after `ContactEnrichParams` (line 105) and `DEFAULT_ENRICH_OUTPUT_FIELDS` (line 142), add:

```python
@dataclass
class CompanyEnrichParams:
    """Parameters for Company Enrich API query."""

    company_ids: list[str]  # List of companyId values
    output_fields: list[str] | None = None  # Fields to return (None = default)


DEFAULT_COMPANY_ENRICH_OUTPUT_FIELDS = [
    "id",
    "name",
    "employeeCount",
    "sicCodes",       # Array of {id, name} — use most specific (last entry)
    "primaryIndustry",  # Array of industry names
]
```

In `ZoomInfoClient`, after `enrich_contacts` (line ~1189), add:

```python
    def enrich_companies(self, params: CompanyEnrichParams) -> dict:
        """
        Enrich companies by companyId to get SIC, industry, employee count.

        Free when company's contact was already enriched (under management).

        Args:
            params: Enrich parameters with company_ids and optional output_fields

        Returns:
            Dict with 'data' (list of enriched companies)
        """
        logger.info(f"Company Enrich: {len(params.company_ids)} companies")
        output_fields = params.output_fields or DEFAULT_COMPANY_ENRICH_OUTPUT_FIELDS

        request_body = {
            "matchCompanyInput": [
                {"companyId": str(cid)} for cid in params.company_ids
            ],
            "outputFields": output_fields,
        }

        response = self._request("POST", "/enrich/company", json=request_body)

        # Parse response: data.result[i].data[0] → company dict
        companies = []
        raw_data = response.get("data", {})
        if isinstance(raw_data, dict):
            for item in raw_data.get("result", []):
                if isinstance(item, dict) and item.get("data"):
                    companies.append(item["data"][0])

        logger.info(f"Company Enrich complete: {len(companies)} companies returned")
        return {"data": companies, "success": response.get("success")}

    def enrich_companies_batch(
        self,
        company_ids: list[str],
        output_fields: list[str] | None = None,
        batch_size: int = 25,
    ) -> list[dict]:
        """
        Enrich companies in batches (max 25 per request).

        Returns:
            List of enriched company dicts
        """
        total = len(company_ids)
        num_batches = (total + batch_size - 1) // batch_size
        logger.info(f"Company Enrich Batch: {total} companies in {num_batches} batches")

        all_enriched = []
        for i in range(0, total, batch_size):
            batch_num = (i // batch_size) + 1
            batch_ids = company_ids[i:i + batch_size]
            logger.info(f"  Company batch {batch_num}/{num_batches} ({len(batch_ids)} companies)")

            params = CompanyEnrichParams(
                company_ids=batch_ids,
                output_fields=output_fields,
            )
            result = self.enrich_companies(params)
            all_enriched.extend(result.get("data", []))

        logger.info(f"Company Enrich Batch complete: {len(all_enriched)} companies from {total} requested")
        return all_enriched
```

**Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_zoominfo_client.py::TestCompanyEnrich -v`
Expected: 4 PASS

**Step 5: Commit**

```bash
git add zoominfo_client.py tests/test_zoominfo_client.py
git commit -m "feat: add Company Enrich API methods"
```

---

### Task 2: merge_company_data helper in export.py

**Files:**
- Modify: `export.py` (add helper after `merge_contact`)
- Test: `tests/test_export.py`

**Step 1: Write failing tests**

Add a new test class in `tests/test_export.py`:

```python
class TestMergeCompanyData:
    """Tests for merge_company_data — maps Company Enrich response onto leads."""

    def test_extracts_most_specific_sic_code(self):
        """sicCodes array: last entry is most specific (4-digit code)."""
        leads = [{"companyId": "123", "firstName": "Alice"}]
        companies = [{
            "id": 123,
            "sicCodes": [
                {"id": "80", "name": "Health Services"},
                {"id": "805", "name": "Nursing"},
                {"id": "8051", "name": "Skilled Nursing Care Facilities"},
            ],
            "primaryIndustry": ["Hospitals & Physicians Clinics"],
            "employeeCount": 144,
        }]
        result = merge_company_data(leads, companies)
        assert result[0]["sicCode"] == "8051"

    def test_extracts_industry_and_employee_count(self):
        leads = [{"companyId": "123"}]
        companies = [{
            "id": 123,
            "primaryIndustry": ["Hospitals & Physicians Clinics"],
            "employeeCount": 250,
        }]
        result = merge_company_data(leads, companies)
        assert result[0]["industry"] == "Hospitals & Physicians Clinics"
        assert result[0]["employeeCount"] == 250

    def test_no_company_match_preserves_lead(self):
        """Leads without a matching company in enrich results keep original data."""
        leads = [{"companyId": "999", "firstName": "Bob"}]
        companies = []
        result = merge_company_data(leads, companies)
        assert result[0]["firstName"] == "Bob"
        assert result[0].get("sicCode") is None

    def test_handles_missing_sic_codes(self):
        """Company with no sicCodes field doesn't crash."""
        leads = [{"companyId": "123"}]
        companies = [{"id": 123, "employeeCount": 50}]
        result = merge_company_data(leads, companies)
        assert result[0]["employeeCount"] == 50
        assert result[0].get("sicCode") is None

    def test_handles_empty_sic_codes_array(self):
        """Company with empty sicCodes array doesn't crash."""
        leads = [{"companyId": "123"}]
        companies = [{"id": 123, "sicCodes": [], "primaryIndustry": []}]
        result = merge_company_data(leads, companies)
        assert result[0].get("sicCode") is None
        assert result[0].get("industry") is None

    def test_multiple_leads_same_company(self):
        """Multiple leads sharing the same companyId all get enriched."""
        leads = [
            {"companyId": "123", "firstName": "Alice"},
            {"companyId": "123", "firstName": "Bob"},
        ]
        companies = [{"id": 123, "employeeCount": 200, "sicCodes": [{"id": "7011", "name": "Hotels"}]}]
        result = merge_company_data(leads, companies)
        assert result[0]["employeeCount"] == 200
        assert result[1]["employeeCount"] == 200

    def test_does_not_overwrite_existing_values(self):
        """If lead already has sicCode/industry/employeeCount, don't overwrite."""
        leads = [{"companyId": "123", "sicCode": "9999", "industry": "Custom", "employeeCount": 500}]
        companies = [{"id": 123, "employeeCount": 200, "sicCodes": [{"id": "7011", "name": "Hotels"}], "primaryIndustry": ["Hotels"]}]
        result = merge_company_data(leads, companies)
        assert result[0]["sicCode"] == "9999"
        assert result[0]["industry"] == "Custom"
        assert result[0]["employeeCount"] == 500
```

Add import: `from export import merge_company_data` at top of test file.

**Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_export.py::TestMergeCompanyData -v`
Expected: FAIL — `ImportError: cannot import name 'merge_company_data'`

**Step 3: Write implementation**

In `export.py`, after `merge_contact()` (around line 68), add:

```python
def merge_company_data(leads: list[dict], companies: list[dict]) -> list[dict]:
    """Merge Company Enrich data onto leads.

    Maps ZoomInfo Company Enrich field names to VanillaSoft-compatible keys:
    - sicCodes[-1]["id"] → sicCode (most specific SIC code)
    - primaryIndustry[0] → industry
    - employeeCount → employeeCount

    Only fills gaps — does not overwrite existing values.
    """
    # Index companies by id (coerce to str for matching)
    company_by_id = {}
    for co in companies:
        cid = str(co.get("id", ""))
        if cid:
            company_by_id[cid] = co

    for lead in leads:
        cid = str(lead.get("companyId") or "")
        co = company_by_id.get(cid)
        if not co:
            continue

        # SIC code: last entry in sicCodes array is the most specific
        if not lead.get("sicCode"):
            sic_list = co.get("sicCodes") or []
            if sic_list:
                lead["sicCode"] = sic_list[-1].get("id", "")

        # Industry: first entry in primaryIndustry array
        if not lead.get("industry"):
            ind_list = co.get("primaryIndustry") or []
            if ind_list:
                lead["industry"] = ind_list[0]

        # Employee count
        if not lead.get("employeeCount"):
            emp = co.get("employeeCount")
            if emp is not None:
                lead["employeeCount"] = emp

    return leads
```

**Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_export.py::TestMergeCompanyData -v`
Expected: 7 PASS

**Step 5: Commit**

```bash
git add export.py tests/test_export.py
git commit -m "feat: add merge_company_data helper for Company Enrich fields"
```

---

### Task 3: Pipeline integration — Intent Workflow

**Files:**
- Modify: `pages/1_Intent_Workflow.py:55` (add import)
- Modify: `pages/1_Intent_Workflow.py:1462` (add Company Enrich after merge_contact loop)

**Step 1: Add import**

At line 55, change:
```python
from export import merge_contact
```
to:
```python
from export import merge_contact, merge_company_data
```

**Step 2: Add Company Enrich step after Contact Enrich merge**

After the merge_contact loop (line ~1462), before scoring (line ~1469), add:

```python
    # Company Enrich — fills sicCode, industry, employeeCount (free if contact already enriched)
    company_ids = list({str(c.get("companyId") or "") for c in enriched_contacts} - {""})
    if company_ids:
        try:
            company_data = client.enrich_companies_batch(company_ids)
            merge_company_data(enriched_contacts, company_data)
            logger.info("Company Enrich: merged %d companies onto %d contacts", len(company_data), len(enriched_contacts))
        except Exception as e:
            logger.warning("Company Enrich failed (non-fatal): %s", e)
```

Note: `client` is already available in scope — it's created earlier in the enrichment step.

**Step 3: Run full test suite**

Run: `python -m pytest tests/ -x -q --tb=short`
Expected: all pass

**Step 4: Commit**

```bash
git add pages/1_Intent_Workflow.py
git commit -m "feat: add Company Enrich to Intent Workflow"
```

---

### Task 4: Pipeline integration — Geography Workflow

**Files:**
- Modify: `pages/2_Geography_Workflow.py:36` (add import)
- Modify: `pages/2_Geography_Workflow.py:1646` (add Company Enrich after merge_contact loop)

**Step 1: Add import**

At line 36, change:
```python
from export import merge_contact
```
to:
```python
from export import merge_contact, merge_company_data
```

**Step 2: Add Company Enrich step after merge_contact loop**

After the merge_contact loop (line ~1646) and distance computation (line ~1657), before scoring (line ~1659), add:

```python
    # Company Enrich — fills sicCode, industry, employeeCount (free if contact already enriched)
    company_ids = list({str(c.get("companyId") or "") for c in enriched_contacts} - {""})
    if company_ids:
        try:
            company_data = client.enrich_companies_batch(company_ids)
            merge_company_data(enriched_contacts, company_data)
            logger.info("Company Enrich: merged %d companies onto %d contacts", len(company_data), len(enriched_contacts))
        except Exception as e:
            logger.warning("Company Enrich failed (non-fatal): %s", e)
```

**Step 3: Run full test suite**

Run: `python -m pytest tests/ -x -q --tb=short`
Expected: all pass

**Step 4: Commit**

```bash
git add pages/2_Geography_Workflow.py
git commit -m "feat: add Company Enrich to Geography Workflow"
```

---

### Task 5: Pipeline integration — Headless intent pipeline

**Files:**
- Modify: `scripts/run_intent_pipeline.py:49` (add import)
- Modify: `scripts/run_intent_pipeline.py:352` (add Company Enrich after merge_contact loop)

**Step 1: Add import**

At line 49, change:
```python
from export import export_leads_to_csv, merge_contact
```
to:
```python
from export import export_leads_to_csv, merge_contact, merge_company_data
```

**Step 2: Add Company Enrich step after merge_contact loop**

After line 352 (merge_contact loop), before credit logging (line ~354), add:

```python
        # Company Enrich — fills sicCode, industry, employeeCount
        company_ids = list({str(c.get("companyId") or "") for c in enriched} - {""})
        if company_ids:
            try:
                company_data = client.enrich_companies_batch(company_ids)
                merge_company_data(enriched, company_data)
                logger.info("Company Enrich: merged %d companies", len(company_data))
            except Exception as e:
                logger.warning("Company Enrich failed (non-fatal): %s", e)
```

**Step 3: Run full test suite**

Run: `python -m pytest tests/ -x -q --tb=short`
Expected: all pass

**Step 4: Commit**

```bash
git add scripts/run_intent_pipeline.py
git commit -m "feat: add Company Enrich to headless intent pipeline"
```

---

### Task 6: Update backfill script

**Files:**
- Modify: `scripts/backfill_exports.py`

**Step 1: Add Company Enrich step after Contact Enrich**

After line 117 (`logger.info("Re-enriched %d contacts", len(enriched))`), before the merge loop, add:

```python
        # Company Enrich — fills sicCode, industry, employeeCount
        company_ids = list({str(l.get("companyId") or "") for l in leads} - {""})
        company_data_map = {}
        if company_ids:
            try:
                company_data = client.enrich_companies_batch(company_ids)
                logger.info("Company Enrich: %d companies returned", len(company_data))
                for co in company_data:
                    cid = str(co.get("id", ""))
                    if cid:
                        company_data_map[cid] = co
            except Exception as e:
                logger.warning("Company Enrich failed (non-fatal): %s", e)
```

Then update the merge loop to also apply company data. After line 127 (`merged = merge_contact(original, enriched_contact)`), add:

```python
            # Apply company data
            cid = str(merged.get("companyId") or "")
            co = company_data_map.get(cid)
            if co:
                sic_list = co.get("sicCodes") or []
                if sic_list and not merged.get("sicCode"):
                    merged["sicCode"] = sic_list[-1].get("id", "")
                ind_list = co.get("primaryIndustry") or []
                if ind_list and not merged.get("industry"):
                    merged["industry"] = ind_list[0]
                if co.get("employeeCount") and not merged.get("employeeCount"):
                    merged["employeeCount"] = co["employeeCount"]
```

Also update the docstring (line 1-6) to mention Company Enrich.

Also update the dry-run company count info (line ~107) to show unique company count:

After line 106, add:
```python
            company_ids = list({str(l.get("companyId") or "") for l in leads} - {""})
            logger.info("DRY RUN: Would also company-enrich %d unique companies", len(company_ids))
```

**Step 2: Run full test suite**

Run: `python -m pytest tests/ -x -q --tb=short`
Expected: all pass

**Step 3: Commit**

```bash
git add scripts/backfill_exports.py
git commit -m "feat: add Company Enrich to backfill script"
```

---

### Task 7: Run backfill and verify

**Step 1: Run backfill with --dry-run to verify**

Run: `python scripts/backfill_exports.py --id 5 --id 6 --dry-run`
Expected: Shows person count and company count for both exports

**Step 2: Run actual backfill**

Run: `python scripts/backfill_exports.py --id 5 --id 6`
Expected: Contact + Company Enrich succeeds, all 96 leads updated with SIC, industry, employee count

**Step 3: Verify results**

Run: `python scripts/backfill_exports.py`
Expected: Exports 5 and 6 show "none" in the Missing Fields column

**Step 4: Run full test suite**

Run: `python -m pytest tests/ -x -q --tb=short`
Expected: all pass

**Step 5: Commit updated session handoff + push**

```bash
git add docs/SESSION_HANDOFF.md
git commit -m "feat: company enrich integration complete, 96 leads backfilled"
git push
```
