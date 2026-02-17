# Rapidfuzz Fuzzy Dedup Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add rapidfuzz fuzzy company name matching to cross-workflow dedup so typos, abbreviations, and word reordering don't create duplicate leads.

**Architecture:** `fuzzy_company_match()` wraps `rapidfuzz.fuzz.token_sort_ratio` over pre-normalized company names. Cross-workflow functions (`find_duplicates`, `merge_lead_lists`, `flag_duplicates_in_list`) gain an O(n×m) fuzzy comparison fallback when exact key matching misses. Threshold configurable in `icp.yaml`.

**Tech Stack:** rapidfuzz>=3.0 (already in requirements.txt), Python, pytest

---

### Task 1: Add `fuzzy_company_match()` + config

**Files:**
- Modify: `dedup.py:1-10` (imports) and append new function after `normalize_company_name()`
- Modify: `config/icp.yaml:199` (append dedup config block)
- Test: `tests/test_dedup.py`

**Step 1: Add config to icp.yaml**

Append after line 199 of `config/icp.yaml`:

```yaml
# Cross-workflow dedup settings
dedup:
  fuzzy_threshold: 85
```

**Step 2: Write the failing tests**

Add to `tests/test_dedup.py`:

```python
from dedup import fuzzy_company_match

class TestFuzzyCompanyMatch:
    """Tests for fuzzy company name matching."""

    def test_exact_match(self):
        assert fuzzy_company_match("acme", "acme") is True

    def test_typo_match(self):
        """One-char typo should match at default threshold."""
        assert fuzzy_company_match("acme services", "acmee services") is True

    def test_word_reorder_match(self):
        """Word reorder should match (token_sort_ratio)."""
        assert fuzzy_company_match("saint joseph hospital", "hospital saint joseph") is True

    def test_abbreviation_match(self):
        """Common abbreviation should match."""
        assert fuzzy_company_match("st joseph hospital", "saint joseph hospital") is True

    def test_different_companies_no_match(self):
        """Genuinely different companies should not match."""
        assert fuzzy_company_match("acme services", "beta industries") is False

    def test_empty_strings_no_match(self):
        """Empty strings should not match."""
        assert fuzzy_company_match("", "") is False
        assert fuzzy_company_match("acme", "") is False

    def test_custom_threshold(self):
        """Custom threshold should be respected."""
        # "acme" vs "acmee" is ~89 ratio — passes at 85, fails at 95
        assert fuzzy_company_match("acme", "acmee", threshold=80) is True
        assert fuzzy_company_match("acme", "acmee", threshold=95) is False
```

**Step 3: Run tests to verify they fail**

Run: `python -m pytest tests/test_dedup.py::TestFuzzyCompanyMatch -v`
Expected: FAIL with `ImportError: cannot import name 'fuzzy_company_match'`

**Step 4: Implement `fuzzy_company_match()`**

Add to `dedup.py` after `normalize_company_name()` (after line 56):

```python
from rapidfuzz.fuzz import token_sort_ratio
from utils import load_config


def _get_fuzzy_threshold() -> float:
    """Load fuzzy match threshold from config."""
    config = load_config()
    return config.get("dedup", {}).get("fuzzy_threshold", 85)


def fuzzy_company_match(
    name1: str,
    name2: str,
    threshold: float | None = None,
) -> bool:
    """
    Check if two normalized company names are a fuzzy match.

    Uses token_sort_ratio which handles word reordering.
    Names should already be passed through normalize_company_name().

    Args:
        name1: First normalized company name
        name2: Second normalized company name
        threshold: Match threshold (0-100). None = use config value.

    Returns:
        True if names match above threshold
    """
    if not name1 or not name2:
        return False

    if threshold is None:
        threshold = _get_fuzzy_threshold()

    score = token_sort_ratio(name1, name2)
    return score >= threshold
```

**Step 5: Run tests to verify they pass**

Run: `python -m pytest tests/test_dedup.py::TestFuzzyCompanyMatch -v`
Expected: All PASS

**Step 6: Commit**

```bash
git add dedup.py config/icp.yaml tests/test_dedup.py
git commit -m "feat: add fuzzy_company_match() with configurable threshold"
```

---

### Task 2: Update `find_duplicates()` with fuzzy fallback

**Files:**
- Modify: `dedup.py:145-186` (`find_duplicates()`)
- Test: `tests/test_dedup.py`

**Step 1: Write the failing tests**

Add to `tests/test_dedup.py`:

```python
class TestFindDuplicatesFuzzy:
    """Tests for fuzzy matching in find_duplicates."""

    def test_fuzzy_company_same_phone(self):
        """Typo in company name with same phone → duplicate found."""
        list1 = [{"phone": "555-111-1111", "companyName": "Acme Services", "_score": 90}]
        list2 = [{"phone": "555-111-1111", "companyName": "Acmee Services Inc", "_score": 70}]
        duplicates = find_duplicates(list1, list2)
        assert len(duplicates) == 1

    def test_fuzzy_company_no_phone_overlap(self):
        """Different phones but fuzzy company match → still found."""
        list1 = [{"phone": "555-111-1111", "companyName": "Saint Joseph Medical Center", "_score": 90}]
        list2 = [{"phone": "555-222-2222", "companyName": "St Joseph Medical Center LLC", "_score": 70}]
        duplicates = find_duplicates(list1, list2)
        assert len(duplicates) == 1

    def test_no_fuzzy_match_different_companies(self):
        """Genuinely different companies with same phone → not duplicated by fuzzy."""
        list1 = [{"phone": "555-111-1111", "companyName": "Acme Services", "_score": 90}]
        list2 = [{"phone": "555-111-1111", "companyName": "Beta Industries", "_score": 70}]
        # Same phone but different company: exact key differs, fuzzy also differs
        # These should match on exact key (same phone+different company = different key)
        # Actually: key is "5551111111|acme services" vs "5551111111|beta industries" — no match
        duplicates = find_duplicates(list1, list2)
        assert len(duplicates) == 0

    def test_exact_match_still_works(self):
        """Exact match (current behavior) still works."""
        list1 = [{"phone": "555-111-1111", "companyName": "Acme Inc", "_score": 90}]
        list2 = [{"phone": "555-111-1111", "companyName": "Acme Corp", "_score": 70}]
        duplicates = find_duplicates(list1, list2)
        assert len(duplicates) == 1
```

**Step 2: Run tests to verify the NEW fuzzy tests fail**

Run: `python -m pytest tests/test_dedup.py::TestFindDuplicatesFuzzy -v`
Expected: `test_fuzzy_company_same_phone` and `test_fuzzy_company_no_phone_overlap` FAIL (0 duplicates found). Others may pass on exact match.

**Step 3: Rewrite `find_duplicates()`**

Replace `find_duplicates()` in `dedup.py` with:

```python
def find_duplicates(
    leads1: list[dict],
    leads2: list[dict],
) -> list[dict]:
    """
    Find leads that appear in both lists.

    Uses exact key matching first, then fuzzy company name fallback
    for cross-workflow dedup.

    Returns:
        List of dicts with duplicate info:
        {
            "key": dedup_key or fuzzy description,
            "lead1": lead from leads1,
            "lead2": lead from leads2,
            "score1": score from lead1,
            "score2": score from lead2,
        }
    """
    duplicates = []
    matched_leads2_indices = set()

    # Extract normalized names for leads2 (once)
    leads2_normalized = []
    for lead in leads2:
        key = get_dedup_key(lead)
        company = normalize_company_name(
            lead.get("companyName", "") or lead.get("Company", "") or ""
        )
        leads2_normalized.append((key, company, lead))

    for lead1 in leads1:
        key1 = get_dedup_key(lead1)
        if key1 == "|":
            continue

        company1 = normalize_company_name(
            lead1.get("companyName", "") or lead1.get("Company", "") or ""
        )

        best_match = None
        best_idx = None

        for idx, (key2, company2, lead2) in enumerate(leads2_normalized):
            if idx in matched_leads2_indices:
                continue
            if key2 == "|":
                continue

            # Tier 1: exact key match
            if key1 == key2:
                best_match = lead2
                best_idx = idx
                break

            # Tier 2/3: fuzzy company match
            if company1 and company2 and fuzzy_company_match(company1, company2):
                best_match = lead2
                best_idx = idx
                break

        if best_match is not None:
            matched_leads2_indices.add(best_idx)
            duplicates.append({
                "key": key1,
                "lead1": lead1,
                "lead2": best_match,
                "score1": lead1.get("_score", 0),
                "score2": best_match.get("_score", 0),
            })

    return duplicates
```

**Step 4: Run tests**

Run: `python -m pytest tests/test_dedup.py::TestFindDuplicatesFuzzy tests/test_dedup.py::TestFindDuplicates -v`
Expected: All PASS

**Step 5: Run full test suite**

Run: `python -m pytest tests/ -x -q --tb=short`
Expected: All pass (509+)

**Step 6: Commit**

```bash
git add dedup.py tests/test_dedup.py
git commit -m "feat: add fuzzy fallback to find_duplicates()"
```

---

### Task 3: Update `merge_lead_lists()` with fuzzy fallback

**Files:**
- Modify: `dedup.py:189-242` (`merge_lead_lists()`)
- Test: `tests/test_dedup.py`

**Step 1: Write the failing tests**

Add to `tests/test_dedup.py`:

```python
class TestMergeLeadListsFuzzy:
    """Tests for fuzzy matching in merge_lead_lists."""

    def test_fuzzy_merge_keeps_higher_score(self):
        """Fuzzy match across workflows keeps the higher-scored lead."""
        intent = [{"phone": "555-111-1111", "companyName": "Acme Services", "_score": 90}]
        geo = [{"phone": "555-222-2222", "companyName": "Acmee Services LLC", "_score": 70}]
        merged, dup_count = merge_lead_lists(intent, geo)
        assert len(merged) == 1
        assert dup_count == 1
        assert merged[0]["_score"] == 90

    def test_fuzzy_merge_geo_higher(self):
        """Fuzzy match where geo lead scores higher."""
        intent = [{"phone": "555-111-1111", "companyName": "St Joseph Hospital", "_score": 60}]
        geo = [{"phone": "555-222-2222", "companyName": "Saint Joseph Hospital", "_score": 85}]
        merged, dup_count = merge_lead_lists(intent, geo)
        assert len(merged) == 1
        assert dup_count == 1
        assert merged[0]["_score"] == 85

    def test_no_false_merge(self):
        """Different companies should not merge."""
        intent = [{"phone": "555-111-1111", "companyName": "Acme Services", "_score": 90}]
        geo = [{"phone": "555-222-2222", "companyName": "Beta Industries", "_score": 80}]
        merged, dup_count = merge_lead_lists(intent, geo)
        assert len(merged) == 2
        assert dup_count == 0
```

**Step 2: Run tests to verify the fuzzy tests fail**

Run: `python -m pytest tests/test_dedup.py::TestMergeLeadListsFuzzy -v`
Expected: `test_fuzzy_merge_keeps_higher_score` and `test_fuzzy_merge_geo_higher` FAIL

**Step 3: Rewrite `merge_lead_lists()`**

Replace `merge_lead_lists()` in `dedup.py`:

```python
def merge_lead_lists(
    intent_leads: list[dict],
    geo_leads: list[dict],
    tag_source: bool = True,
) -> tuple[list[dict], int]:
    """
    Merge intent and geography leads, keeping higher-scored duplicates.
    Uses exact key match first, then fuzzy company name fallback.
    """
    if tag_source:
        for lead in intent_leads:
            lead["_source"] = "intent"
        for lead in geo_leads:
            lead["_source"] = "geography"

    # Build index of intent leads by key and normalized company
    best_leads = {}
    intent_companies = {}  # key -> normalized company name

    for lead in intent_leads:
        key = get_dedup_key(lead)
        if key == "|":
            key = f"intent_{id(lead)}"

        company = normalize_company_name(
            lead.get("companyName", "") or lead.get("Company", "") or ""
        )
        intent_companies[key] = company

        if key not in best_leads or lead.get("_score", 0) > best_leads[key].get("_score", 0):
            best_leads[key] = lead

    # Process geo leads
    duplicate_count = 0
    for lead in geo_leads:
        key = get_dedup_key(lead)
        if key == "|":
            key = f"geo_{id(lead)}"

        # Try exact match first
        matched_key = None
        if key in best_leads:
            matched_key = key
        else:
            # Fuzzy fallback: compare company name against all intent companies
            geo_company = normalize_company_name(
                lead.get("companyName", "") or lead.get("Company", "") or ""
            )
            if geo_company:
                for ikey, icompany in intent_companies.items():
                    if icompany and fuzzy_company_match(geo_company, icompany):
                        matched_key = ikey
                        break

        if matched_key is not None:
            duplicate_count += 1
            if lead.get("_score", 0) > best_leads[matched_key].get("_score", 0):
                best_leads[matched_key] = lead
        else:
            best_leads[key] = lead

    merged = sorted(best_leads.values(), key=lambda x: x.get("_score", 0), reverse=True)
    return merged, duplicate_count
```

**Step 4: Run tests**

Run: `python -m pytest tests/test_dedup.py::TestMergeLeadListsFuzzy tests/test_dedup.py::TestMergeLeadLists -v`
Expected: All PASS

**Step 5: Run full test suite**

Run: `python -m pytest tests/ -x -q --tb=short`
Expected: All pass

**Step 6: Commit**

```bash
git add dedup.py tests/test_dedup.py
git commit -m "feat: add fuzzy fallback to merge_lead_lists()"
```

---

### Task 4: Update `flag_duplicates_in_list()` with fuzzy fallback

**Files:**
- Modify: `dedup.py:245-266` (`flag_duplicates_in_list()`)
- Test: `tests/test_dedup.py`

**Step 1: Write the failing test**

Add to `tests/test_dedup.py`:

```python
class TestFlagDuplicatesFuzzy:
    """Tests for fuzzy matching in flag_duplicates_in_list."""

    def test_fuzzy_flag(self):
        """Fuzzy company match flags as duplicate."""
        leads = [
            {"phone": "555-111-1111", "companyName": "Acme Services"},
            {"phone": "555-222-2222", "companyName": "Beta Corp"},
        ]
        other = [
            {"phone": "555-333-3333", "companyName": "Acmee Services LLC"},
        ]
        flagged = flag_duplicates_in_list(leads, other)
        assert flagged[0]["_is_duplicate"] is True
        assert flagged[1]["_is_duplicate"] is False
```

**Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_dedup.py::TestFlagDuplicatesFuzzy -v`
Expected: FAIL (Acme Services not flagged)

**Step 3: Rewrite `flag_duplicates_in_list()`**

Replace in `dedup.py`:

```python
def flag_duplicates_in_list(leads: list[dict], other_leads: list[dict]) -> list[dict]:
    """
    Add _is_duplicate flag to leads that also appear in other_leads.
    Uses exact key match first, then fuzzy company name fallback.
    """
    other_keys = set()
    other_companies = []
    for lead in other_leads:
        key = get_dedup_key(lead)
        if key and key != "|":
            other_keys.add(key)
        company = normalize_company_name(
            lead.get("companyName", "") or lead.get("Company", "") or ""
        )
        if company:
            other_companies.append(company)

    for lead in leads:
        key = get_dedup_key(lead)

        # Tier 1: exact key match
        if key in other_keys:
            lead["_is_duplicate"] = True
            continue

        # Tier 2/3: fuzzy company fallback
        company = normalize_company_name(
            lead.get("companyName", "") or lead.get("Company", "") or ""
        )
        if company and any(fuzzy_company_match(company, oc) for oc in other_companies):
            lead["_is_duplicate"] = True
        else:
            lead["_is_duplicate"] = False

    return leads
```

**Step 4: Run tests**

Run: `python -m pytest tests/test_dedup.py::TestFlagDuplicatesFuzzy tests/test_dedup.py::TestFlagDuplicates -v`
Expected: All PASS

**Step 5: Run full test suite**

Run: `python -m pytest tests/ -x -q --tb=short`
Expected: All pass

**Step 6: Commit**

```bash
git add dedup.py tests/test_dedup.py
git commit -m "feat: add fuzzy fallback to flag_duplicates_in_list()"
```

---

### Task 5: Final verification + design doc commit

**Step 1: Run full test suite**

Run: `python -m pytest tests/ -x -q --tb=short`
Expected: All pass (509 + ~12 new = ~521)

**Step 2: Verify rapidfuzz installed**

Run: `python -c "from rapidfuzz.fuzz import token_sort_ratio; print(token_sort_ratio('acme services', 'acmee services'))"`
Expected: A score ~93

**Step 3: Commit design doc + plan**

```bash
git add docs/plans/2026-02-17-rapidfuzz-dedup-design.md docs/plans/2026-02-17-rapidfuzz-dedup-plan.md
git commit -m "docs: rapidfuzz dedup design and implementation plan"
```
