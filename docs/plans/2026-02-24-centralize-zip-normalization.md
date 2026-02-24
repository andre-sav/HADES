# Centralize ZIP Code Normalization

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Replace 3 duplicate ZIP normalization functions with a single `normalize_zip()` in `utils.py`.

**Architecture:** Add `normalize_zip()` to `utils.py` using the regex approach from `enrich_locatings.clean_zip()` (most robust). Update `get_state_from_zip()` to call it. Make `enrich_locatings.clean_zip()` a thin wrapper. Delete `scripts/import_historical.normalize_zip()` and update its callers to import from `utils`. Leave `zoho_sync.parse_zip()` as-is (extraction, not normalization).

**Tech Stack:** Python stdlib (`re`), pytest

---

### Task 1: Add `normalize_zip()` to `utils.py` with tests

**Files:**
- Modify: `utils.py:418` (insert before `get_state_from_zip`)
- Modify: `tests/test_utils.py:312` (insert before `TestGetStateFromZip`)

**Step 1: Write the tests**

Add to `tests/test_utils.py` before line 312 (`TestGetStateFromZip`):

```python
class TestNormalizeZip:
    """Tests for centralized ZIP code normalization."""

    def test_standard_5_digit(self):
        assert normalize_zip("75201") == "75201"

    def test_zip_plus4_hyphen(self):
        assert normalize_zip("75201-1234") == "75201"

    def test_zip_plus4_space(self):
        assert normalize_zip("75201 1234") == "75201"

    def test_9_digit_no_separator(self):
        assert normalize_zip("752011234") == "75201"

    def test_4_digit_padded(self):
        assert normalize_zip("6101") == "06101"

    def test_3_digit_padded(self):
        assert normalize_zip("501") == "00501"

    def test_backtick_excel_format(self):
        assert normalize_zip("`06101") == "06101"

    def test_excel_equals_format(self):
        assert normalize_zip("='06101'") == "06101"

    def test_whitespace(self):
        assert normalize_zip("  75201  ") == "75201"

    def test_integer_input(self):
        assert normalize_zip(6101) == "06101"

    def test_none_returns_none(self):
        assert normalize_zip(None) is None

    def test_empty_returns_none(self):
        assert normalize_zip("") is None

    def test_non_numeric_returns_none(self):
        assert normalize_zip("ABCDE") is None

    def test_too_short_returns_none(self):
        """Single digit or two digits aren't valid ZIPs."""
        assert normalize_zip("1") is None
        assert normalize_zip("12") is None
```

Add `normalize_zip` to the import block at the top of `tests/test_utils.py`.

**Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_utils.py::TestNormalizeZip -v`
Expected: ImportError — `normalize_zip` not defined in utils

**Step 3: Write `normalize_zip()` in `utils.py`**

Insert before `get_state_from_zip` (line 418):

```python
def normalize_zip(raw) -> str | None:
    """Normalize a ZIP code to 5-digit string.

    Handles ZIP+4 (hyphen, space, no separator), leading-zero padding,
    Excel backtick/equals formatting, integer input, and whitespace.

    Returns:
        5-digit ZIP string, or None if input is empty/invalid.
    """
    import re

    if raw is None:
        return None
    digits = re.sub(r"[^0-9]", "", str(raw))
    if len(digits) < 3:
        return None
    # Take first 5 digits (handles ZIP+4 variants)
    digits = digits[:5]
    # Pad with leading zeros (handles 4-digit CT/NJ/MA ZIPs)
    return digits.zfill(5)
```

**Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_utils.py::TestNormalizeZip -v`
Expected: All 14 tests PASS

**Step 5: Commit**

```bash
git add utils.py tests/test_utils.py
git commit -m "feat: add normalize_zip() to utils.py with tests (HADES-nw6)"
```

---

### Task 2: Refactor `get_state_from_zip()` to use `normalize_zip()`

**Files:**
- Modify: `utils.py:419-443` (`get_state_from_zip`)

**Step 1: Replace inline cleaning with `normalize_zip()` call**

Replace the body of `get_state_from_zip` (lines ~428-443) with:

```python
def get_state_from_zip(zip_code: str) -> str | None:
    """Get state code from ZIP code."""
    cleaned = normalize_zip(zip_code)
    if not cleaned:
        return None
    prefix = cleaned[:3]
    return ZIP_PREFIX_TO_STATE.get(prefix)
```

**Step 2: Run existing tests to verify no regressions**

Run: `python -m pytest tests/test_utils.py::TestGetStateFromZip -v`
Expected: All 9 tests PASS (behavior unchanged)

**Step 3: Commit**

```bash
git add utils.py
git commit -m "refactor: get_state_from_zip uses normalize_zip (HADES-nw6)"
```

---

### Task 3: Refactor `enrich_locatings.clean_zip()` to delegate

**Files:**
- Modify: `enrich_locatings.py:38-53` (`clean_zip`)

**Step 1: Replace body with `normalize_zip()` call**

```python
def clean_zip(raw: str) -> str:
    """Clean a ZIP code: strip non-numeric, pad to 5 digits.

    Thin wrapper around utils.normalize_zip() — returns "" instead of
    None for backward compatibility with the enrichment pipeline.
    """
    from utils import normalize_zip
    return normalize_zip(raw) or ""
```

**Step 2: Run full test suite to verify no regressions**

Run: `python -m pytest tests/ -x -q --tb=short`
Expected: All tests PASS

**Step 3: Commit**

```bash
git add enrich_locatings.py
git commit -m "refactor: clean_zip delegates to normalize_zip (HADES-nw6)"
```

---

### Task 4: Delete `scripts/import_historical.normalize_zip()` and update callers

**Files:**
- Modify: `scripts/import_historical.py:62-75` (delete function)
- Modify: `scripts/import_historical.py:109,142` (call sites)
- Modify: `tests/test_import_historical.py:10,47-69` (update import, keep tests)

**Step 1: In `scripts/import_historical.py`**

- Delete the `normalize_zip` function (lines 62-75)
- Add `from utils import normalize_zip` near the top imports (after the sys.path setup)
- Call sites at lines ~109 and ~142 already call `normalize_zip(...)` so they need no change

**Step 2: In `tests/test_import_historical.py`**

- Change the import from `from scripts.import_historical import normalize_state, normalize_zip` to `from scripts.import_historical import normalize_state` and add `from utils import normalize_zip`
- The `TestNormalizeZip` class in this file can be deleted since `tests/test_utils.py::TestNormalizeZip` now has superset coverage. Or keep it as integration coverage — it will pass either way since it imports from the same function now.

**Step 3: Run tests**

Run: `python -m pytest tests/test_import_historical.py -v && python -m pytest tests/ -x -q --tb=short`
Expected: All tests PASS

**Step 4: Commit**

```bash
git add scripts/import_historical.py tests/test_import_historical.py
git commit -m "refactor: import_historical uses utils.normalize_zip (HADES-nw6)"
```

---

### Task 5: Final verification

**Step 1: Run full test suite**

Run: `python -m pytest tests/ -x -q --tb=short`
Expected: All tests PASS

**Step 2: Grep for orphaned references**

Run: `grep -rn "clean_zip\|normalize_zip" --include="*.py" .` and verify:
- `utils.py` — `normalize_zip` definition
- `enrich_locatings.py` — `clean_zip` wrapper calling `normalize_zip`
- `scripts/import_historical.py` — `from utils import normalize_zip`
- Test files — imports from correct locations
- No other files define their own ZIP normalization

**Step 3: Commit (if any cleanup needed)**
