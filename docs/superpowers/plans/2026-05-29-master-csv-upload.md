# Operator Master CSV Upload — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let users bulk-import operators into HADES by uploading a column-per-operator Master CSV, matching each against the Turso `operators` table and importing only the unmatched ones, with no silent data loss.

**Architecture:** A pure-logic module `operator_import.py` (parse + reconcile, fully unit-tested without Streamlit) plus a thin "Upload Master CSV" section in `pages/3_Operators.py`. A small `get_all_operators()` DB helper feeds reconciliation. Import runs inside the existing `db.transaction()` context manager.

**Tech Stack:** Python, pandas 2.2.3 (positional CSV read), Streamlit, Turso/libsql, pytest.

**Spec:** `docs/superpowers/specs/2026-05-29-hades-master-csv-upload-design.md`
**Bead:** HADES-ei7

---

## File Structure

- **Create** `operator_import.py` — `MasterCsvParse` dataclass, `MASTER_ROW_*` constants, `normalize_operator_name`, `parse_master_csv`, `reconcile_operators`. Pure logic, no Streamlit import.
- **Create** `tests/test_operator_import.py` — unit tests for parse + reconcile.
- **Modify** `db/_operators.py` — add `get_all_operators()`.
- **Modify** `tests/test_turso_db.py` — test for `get_all_operators()`.
- **Modify** `pages/3_Operators.py` — add the upload/reconcile/import UI section.

Row-position constants (0-indexed, `header=None`) live in **one place** in `operator_import.py` so the offset can be corrected against a real file with a single edit.

---

### Task 1: Parser core — `normalize_operator_name`, `MasterCsvParse`, `parse_master_csv`

**Files:**
- Create: `operator_import.py`
- Test: `tests/test_operator_import.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_operator_import.py
import io
import pytest

from operator_import import (
    MasterCsvParse,
    normalize_operator_name,
    parse_master_csv,
)

# Column-per-operator fixture. Rows are POSITIONAL (header=None):
#   row2=business, row3=name, row4=phone, row5=email, row6=zip,
#   row7=website, row10=team. Rows 0,1,8,9 are non-field rows.
# Columns: A=valid, B=valid w/ messy data + leading-zero zip,
#          C=wholly empty spacer, D=data but BLANK name (skip-no-name).
FIXTURE = (
    "title,,,\n"                                            # row0
    "subtitle,,,\n"                                         # row1
    "Acme Vending,Bob's Snacks,,Ghost Co\n"                 # row2 business
    "John Smith, Bob   Jones ,,\n"                          # row3 name (D blank)
    "5551234567,N/A,,5559999999\n"                          # row4 phone
    "john@a.com,bob@b.com,,ghost@x.com\n"                   # row5 email
    "75201,07030,,30301\n"                                  # row6 zip
    "acme.com,bobs.com,,ghost.com\n"                        # row7 website
    ",,,\n"                                                 # row8 gap
    ",,,\n"                                                 # row9 gap
    "North Texas,New Jersey\xa0,,Georgia\n"                 # row10 team
)


def _parse(text):
    return parse_master_csv(io.StringIO(text))


def test_normalize_collapses_case_and_whitespace():
    assert normalize_operator_name("  John   Smith ") == "john smith"
    assert normalize_operator_name("John Smith") == "john smith"


def test_parse_returns_master_csv_parse():
    result = _parse(FIXTURE)
    assert isinstance(result, MasterCsvParse)


def test_parse_scans_all_columns_not_just_last_five():
    # 4 columns total; A and B are operators, C empty, D has no name.
    result = _parse(FIXTURE)
    assert result.total_columns == 4
    names = [op["operator_name"] for op in result.operators]
    assert names == ["John Smith", "Bob Jones"]  # A and B, in column order


def test_parse_skips_empty_spacer_and_records_blank_name_column():
    result = _parse(FIXTURE)
    assert result.empty_columns == 1            # column C
    assert result.skipped_no_name == [3]        # column D index (data, no name)


def test_parse_cleans_messy_cells():
    result = _parse(FIXTURE)
    bob = result.operators[1]
    assert bob["operator_name"] == "Bob Jones"  # collapsed inner spaces, trimmed
    assert bob["operator_phone"] is None        # "N/A" -> empty -> None
    assert bob["team"] == "New Jersey"          # \xa0 stripped


def test_parse_keeps_zip_as_string_no_float_coercion():
    result = _parse(FIXTURE)
    assert result.operators[0]["operator_zip"] == "75201"   # not "75201.0"
    assert result.operators[1]["operator_zip"] == "07030"   # leading zero kept


def test_parse_formats_phone():
    result = _parse(FIXTURE)
    assert result.operators[0]["operator_phone"] == "(555) 123-4567"


def test_parse_empty_file_returns_empty_parse():
    result = _parse("\n\n")
    assert result.operators == []
    assert isinstance(result, MasterCsvParse)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_operator_import.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'operator_import'`.

- [ ] **Step 3: Write minimal implementation**

```python
# operator_import.py
"""Parse a column-per-operator Master CSV and reconcile it against the
operators table. Pure logic — no Streamlit. See
docs/superpowers/specs/2026-05-29-hades-master-csv-upload-design.md.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field

import pandas as pd

from utils import format_phone, normalize_zip

logger = logging.getLogger(__name__)

# Fixed row positions (0-indexed; file read with header=None).
# SINGLE SOURCE OF TRUTH — correct here if a real Master file is offset.
MASTER_ROW_BUSINESS_NAME = 2
MASTER_ROW_OPERATOR_NAME = 3
MASTER_ROW_PHONE = 4
MASTER_ROW_EMAIL = 5
MASTER_ROW_ZIP = 6
MASTER_ROW_WEBSITE = 7
MASTER_ROW_TEAM = 10


@dataclass
class MasterCsvParse:
    operators: list[dict] = field(default_factory=list)
    total_columns: int = 0
    skipped_no_name: list[int] = field(default_factory=list)
    empty_columns: int = 0


def normalize_operator_name(raw) -> str:
    """Lowercase, trim, collapse internal whitespace. Match key."""
    if raw is None:
        return ""
    return re.sub(r"\s+", " ", str(raw)).strip().lower()


def _clean_cell(df: pd.DataFrame, row: int, col: int) -> str:
    """Null-safe positional read: NaN/missing -> '', strip \\xa0 + ws,
    treat 'N/A' (any case) as empty."""
    try:
        if row >= len(df):
            return ""
        val = df.iat[row, col]
    except (IndexError, KeyError):
        return ""
    if pd.isna(val):
        return ""
    cleaned = re.sub(r"\s+", " ", str(val).replace("\xa0", " ")).strip()
    if cleaned == "" or cleaned.upper() == "N/A":
        return ""
    return cleaned


def parse_master_csv(file) -> MasterCsvParse:
    """Parse a column-per-operator Master CSV into operator dicts.

    `file` may be a path or a file-like object. dtype=str prevents
    ZIP/phone float coercion; utf-8-sig strips a BOM if present.
    """
    try:
        df = pd.read_csv(file, header=None, dtype=str, encoding="utf-8-sig")
    except (pd.errors.EmptyDataError, pd.errors.ParserError) as e:
        logger.warning("Master CSV unparseable: %s", e)
        return MasterCsvParse()

    result = MasterCsvParse(total_columns=int(df.shape[1]))

    for col in range(df.shape[1]):
        name = _clean_cell(df, MASTER_ROW_OPERATOR_NAME, col)
        business = _clean_cell(df, MASTER_ROW_BUSINESS_NAME, col)
        phone = _clean_cell(df, MASTER_ROW_PHONE, col)
        email = _clean_cell(df, MASTER_ROW_EMAIL, col)
        zip_ = _clean_cell(df, MASTER_ROW_ZIP, col)
        website = _clean_cell(df, MASTER_ROW_WEBSITE, col)
        team = _clean_cell(df, MASTER_ROW_TEAM, col)

        if not name:
            # Distinguish a spacer column from a real-but-mis-keyed one.
            if any([business, phone, email, zip_, website, team]):
                result.skipped_no_name.append(col)
            else:
                result.empty_columns += 1
            continue

        result.operators.append({
            "operator_name": name,
            "vending_business_name": business or None,
            "operator_phone": format_phone(phone) or None,
            "operator_email": email or None,
            "operator_zip": normalize_zip(zip_),
            "operator_website": website or None,
            "team": team or None,
        })

    return result
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_operator_import.py -q`
Expected: PASS (8 tests).

- [ ] **Step 5: Commit**

```bash
git add operator_import.py tests/test_operator_import.py
git commit -m "feat: parse column-per-operator Master CSV (HADES-ei7)"
```

---

### Task 2: Reconciliation — `reconcile_operators`

**Files:**
- Modify: `operator_import.py`
- Test: `tests/test_operator_import.py`

- [ ] **Step 1: Write the failing tests**

```python
# Append to tests/test_operator_import.py
from operator_import import reconcile_operators


def _db_row(name, phone="(555) 123-4567", **kw):
    row = {
        "id": kw.get("id", 1),
        "operator_name": name,
        "vending_business_name": kw.get("business", "Acme Vending"),
        "operator_phone": phone,
        "operator_email": kw.get("email", "john@a.com"),
        "operator_zip": kw.get("zip", "75201"),
        "operator_website": kw.get("website", "acme.com"),
        "team": kw.get("team", "North Texas"),
    }
    return row


def test_reconcile_splits_matched_and_new():
    parsed = [
        {"operator_name": "John Smith", "operator_phone": "(555) 123-4567",
         "vending_business_name": "Acme Vending", "operator_email": "john@a.com",
         "operator_zip": "75201", "operator_website": "acme.com", "team": "North Texas"},
        {"operator_name": "Carol New", "operator_phone": "(555) 000-0000",
         "vending_business_name": "New Co", "operator_email": None,
         "operator_zip": "10001", "operator_website": None, "team": None},
    ]
    existing = [_db_row("John Smith")]
    out = reconcile_operators(parsed, existing)
    assert [m["uploaded"]["operator_name"] for m in out["matched"]] == ["John Smith"]
    assert [n["operator_name"] for n in out["new"]] == ["Carol New"]


def test_reconcile_matches_normalized_name():
    parsed = [{"operator_name": " John   Smith ", "operator_phone": "(555) 123-4567",
               "vending_business_name": "Acme Vending", "operator_email": "john@a.com",
               "operator_zip": "75201", "operator_website": "acme.com", "team": "North Texas"}]
    existing = [_db_row("John Smith")]
    out = reconcile_operators(parsed, existing)
    assert len(out["matched"]) == 1
    assert out["new"] == []


def test_reconcile_detects_field_drift():
    parsed = [{"operator_name": "John Smith", "operator_phone": "(555) 999-9999",
               "vending_business_name": "Acme Vending", "operator_email": "john@a.com",
               "operator_zip": "75201", "operator_website": "acme.com", "team": "North Texas"}]
    existing = [_db_row("John Smith", phone="(555) 123-4567")]
    out = reconcile_operators(parsed, existing)
    drift = out["matched"][0]["drift"]
    assert "operator_phone" in drift
    assert drift["operator_phone"] == ("(555) 999-9999", "(555) 123-4567")
    assert "operator_email" not in drift  # unchanged field not flagged


def test_reconcile_flags_duplicate_names_in_upload():
    parsed = [
        {"operator_name": "Dup Co", "operator_phone": None, "vending_business_name": None,
         "operator_email": None, "operator_zip": None, "operator_website": None, "team": None},
        {"operator_name": "dup co", "operator_phone": None, "vending_business_name": None,
         "operator_email": None, "operator_zip": None, "operator_website": None, "team": None},
    ]
    out = reconcile_operators(parsed, [])
    assert out["dupes_in_upload"] == ["dup co"]
    assert [n["operator_name"] for n in out["new"]] == ["Dup Co"]  # only first
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_operator_import.py -k reconcile -q`
Expected: FAIL — `ImportError: cannot import name 'reconcile_operators'`.

- [ ] **Step 3: Write minimal implementation**

```python
# Append to operator_import.py

# Fields compared for drift on matched operators (display only).
_DRIFT_FIELDS = (
    "vending_business_name", "operator_phone", "operator_email",
    "operator_zip", "operator_website", "team",
)


def reconcile_operators(parsed: list[dict], existing: list[dict]) -> dict:
    """Split parsed operators into matched (already in DB) vs new.

    Matched entries carry the DB row and a `drift` map of fields whose
    uploaded value differs from the stored value (display only, never
    written). Names appearing 2+ times in the upload are reported in
    `dupes_in_upload`; only the first occurrence is offered as new/matched.
    """
    by_name: dict[str, dict] = {}
    for row in existing:
        key = normalize_operator_name(row.get("operator_name"))
        if key and key not in by_name:
            by_name[key] = row
        elif key:
            logger.warning("Duplicate normalized operator name in DB: %r", key)

    matched: list[dict] = []
    new: list[dict] = []
    seen: set[str] = set()
    dupes: list[str] = []

    for op in parsed:
        key = normalize_operator_name(op.get("operator_name"))
        if key in seen:
            if key not in dupes:
                dupes.append(key)
            continue
        seen.add(key)

        db_row = by_name.get(key)
        if db_row is not None:
            drift = {}
            for f in _DRIFT_FIELDS:
                up = op.get(f) or ""
                cur = db_row.get(f) or ""
                if str(up) != str(cur):
                    drift[f] = (op.get(f), db_row.get(f))
            matched.append({"uploaded": op, "db": db_row, "drift": drift})
        else:
            new.append(op)

    return {"matched": matched, "new": new, "dupes_in_upload": dupes}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_operator_import.py -q`
Expected: PASS (all tests, ~12).

- [ ] **Step 5: Commit**

```bash
git add operator_import.py tests/test_operator_import.py
git commit -m "feat: reconcile parsed operators against DB with drift detection (HADES-ei7)"
```

---

### Task 3: DB helper — `get_all_operators()`

**Files:**
- Modify: `db/_operators.py` (add method after `search_operators`, before `create_operator` at line ~92)
- Test: `tests/test_turso_db.py`

- [ ] **Step 1: Write the failing test**

```python
# Add to tests/test_turso_db.py (in the operators test area)
def test_get_all_operators_returns_every_row(tmp_path):
    from turso_db import TursoDatabase
    db = TursoDatabase(db_path=str(tmp_path / "t.db"))  # match existing test setup
    db.create_operator(operator_name="Alpha", operator_zip="75201")
    db.create_operator(operator_name="Beta", operator_zip="10001")
    rows = db.get_all_operators()
    names = sorted(r["operator_name"] for r in rows)
    assert names == ["Alpha", "Beta"]
    assert {"id", "operator_name", "operator_zip", "team"} <= set(rows[0].keys())
```

> Note: match however `tests/test_turso_db.py` already constructs a test
> `TursoDatabase` (it may use a fixture or in-memory path). Mirror the existing
> pattern in that file rather than the literal constructor above.

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_turso_db.py -k get_all_operators -q`
Expected: FAIL — `AttributeError: 'TursoDatabase' object has no attribute 'get_all_operators'`.

- [ ] **Step 3: Write minimal implementation**

```python
# db/_operators.py — add immediately before create_operator
    def get_all_operators(self) -> list[dict]:
        """Return every operator (no pagination). For bulk reconciliation."""
        _cols = ("id, operator_name, vending_business_name, operator_phone, "
                 "operator_email, operator_zip, operator_website, team")
        rows = self.execute(
            f"SELECT {_cols} FROM operators ORDER BY operator_name"
        )
        return [
            {
                "id": r[0], "operator_name": r[1], "vending_business_name": r[2],
                "operator_phone": r[3], "operator_email": r[4], "operator_zip": r[5],
                "operator_website": r[6], "team": r[7],
            }
            for r in rows
        ]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_turso_db.py -k get_all_operators -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add db/_operators.py tests/test_turso_db.py
git commit -m "feat: add get_all_operators() DB helper (HADES-ei7)"
```

---

### Task 4: UI — Upload Master CSV section on the Operators page

**Files:**
- Modify: `pages/3_Operators.py` (add a new section; insert just before the "ADD BUTTON" block, ~line 188, so it sits above the manual add form)

> Streamlit page logic is verified manually/at runtime, not unit-tested (matches
> existing HADES convention). All testable logic lives in `operator_import.py`
> (Tasks 1–2), already covered. This task wires that logic to widgets.

- [ ] **Step 1: Add the import**

In `pages/3_Operators.py`, add near the other imports (after `from utils import require_auth, format_phone`):

```python
from operator_import import parse_master_csv, reconcile_operators
```

- [ ] **Step 2: Add the upload section**

Insert before the `# ADD BUTTON` comment block (~line 188):

```python
# =============================================================================
# UPLOAD MASTER CSV
# =============================================================================
with st.expander("⬆ Upload Master CSV", expanded=False):
    st.caption(
        "Column-per-operator Master file (each operator is a column). "
        "Every column is read. Operators already in the database are shown "
        "for confirmation; only new ones are imported."
    )
    master_file = st.file_uploader("Master CSV", type=["csv"], key="op_master_csv")

    if master_file is not None:
        parse = parse_master_csv(master_file)

        if not parse.operators and not parse.skipped_no_name:
            st.warning(
                "No operator data found in the uploaded file. "
                "Check that it is a column-per-operator Master CSV."
            )
        else:
            existing = db.get_all_operators()
            rec = reconcile_operators(parse.operators, existing)
            n_new, n_matched = len(rec["new"]), len(rec["matched"])
            n_skip = len(parse.skipped_no_name)

            # Reconciliation summary — every column accounted for.
            st.info(
                f"File has {parse.total_columns} columns → "
                f"{n_new} new, {n_matched} already in DB, "
                f"{n_skip} skipped (no name), {parse.empty_columns} empty."
            )

            if parse.skipped_no_name:
                cols = ", ".join(str(c + 1) for c in parse.skipped_no_name)
                st.warning(
                    f"⚠ {n_skip} column(s) had data but no operator name and were "
                    f"NOT imported (file column #: {cols}). Fix the name cell and "
                    f"re-upload if these should be operators."
                )

            if rec["dupes_in_upload"]:
                dups = ", ".join(rec["dupes_in_upload"])
                st.warning(
                    f"⚠ Duplicate operator name(s) within the file: {dups}. "
                    f"Only the first occurrence of each will be imported."
                )

            if rec["matched"]:
                st.markdown(f"**Already in database ({n_matched})**")
                st.caption(
                    "Differences are shown for reference only and are NOT imported "
                    "— edit the operator to change stored values."
                )
                for m in rec["matched"]:
                    up, dbrow, drift = m["uploaded"], m["db"], m["drift"]
                    label = up["operator_name"]
                    flag = " ⚠ differs" if drift else ""
                    with st.expander(f"{label}{flag}", expanded=bool(drift)):
                        for f in ("vending_business_name", "operator_phone",
                                  "operator_email", "operator_zip",
                                  "operator_website", "team"):
                            u, d = up.get(f) or "—", dbrow.get(f) or "—"
                            mark = "⚠" if f in drift else "✓"
                            st.write(f"{mark} **{f}** — uploaded `{u}` | DB `{d}`")

            if rec["new"]:
                st.markdown(f"**New operators ({n_new})**")
                st.dataframe(
                    [
                        {
                            "Name": n["operator_name"],
                            "Business": n.get("vending_business_name") or "",
                            "Phone": n.get("operator_phone") or "",
                            "Email": n.get("operator_email") or "",
                            "ZIP": n.get("operator_zip") or "",
                            "Team": n.get("team") or "",
                        }
                        for n in rec["new"]
                    ],
                    use_container_width=True,
                    hide_index=True,
                )
                if st.button(f"Import {n_new} new operators", type="primary",
                             key="op_import_master"):
                    imported, skipped = 0, 0
                    try:
                        with db.transaction():
                            for n in rec["new"]:
                                try:
                                    db.create_operator(**n)
                                    imported += 1
                                except Exception as e:  # UNIQUE race / missed dupe
                                    if "UNIQUE" in str(e):
                                        skipped += 1
                                    else:
                                        raise
                        st.toast(
                            f"Imported {imported}, skipped {skipped} already present"
                        )
                        st.rerun()
                    except Exception as e:
                        logger.error("Master CSV import failed: %s", e, exc_info=True)
                        st.error("Import failed and was rolled back. Please try again.")
            elif not rec["matched"] and not parse.skipped_no_name:
                st.info("Nothing new to import.")
```

- [ ] **Step 3: Smoke-test the page imports**

Run: `python -c "import ast; ast.parse(open('pages/3_Operators.py').read()); print('parse OK')"`
Expected: `parse OK`.

Run: `python -c "import operator_import; print('import OK')"`
Expected: `import OK`.

- [ ] **Step 4: Commit**

```bash
git add pages/3_Operators.py
git commit -m "feat: Master CSV upload + reconciliation UI on Operators page (HADES-ei7)"
```

---

### Task 5: Full suite + bead close

**Files:** none (verification)

- [ ] **Step 1: Run the full test suite**

Run: `python -m pytest tests/ -x -q --tb=short`
Expected: all pass (prior count + ~13 new). If anything fails, fix before continuing — the pre-commit hook enforces this.

- [ ] **Step 2: Manual smoke (optional but recommended)**

Run `streamlit run app.py`, open Operators → "⬆ Upload Master CSV", upload a real
Master CSV. **Validate the row-offset assumption** (spec's highest risk): confirm
the parsed names/phones/zips line up with the file. If they're shifted by one row,
adjust the `MASTER_ROW_*` constants in `operator_import.py` (single edit) and
re-run Task 1 tests.

- [ ] **Step 3: Close the bead and sync**

```bash
bd close HADES-ei7 --reason="Master CSV upload with DB reconciliation implemented + tested"
bd sync
```

---

## Self-Review

**Spec coverage:**
- Full-column scan (not last 5) → Task 1 (`test_parse_scans_all_columns_not_just_last_five`).
- Match by normalized name + show DB record → Task 2 + Task 4 matched expander.
- Import New only, Matched read-only → Task 4 (no write on matched).
- Drift highlight + "not imported" note → Task 2 (`drift`) + Task 4 caption/marks.
- Silent-loss guards: dtype=str (Task 1 zip tests), skipped_no_name (Task 1 + Task 4 warning), dupes_in_upload (Task 2 + Task 4), UNIQUE skip+count + transaction rollback (Task 4), summary line (Task 4).
- Tests without Streamlit → Tasks 1–3.

**Placeholder scan:** none — every code step has complete code.

**Type consistency:** `MasterCsvParse` fields (`operators`, `total_columns`, `skipped_no_name`, `empty_columns`) used identically in Tasks 1 & 4. `reconcile_operators` output keys (`matched`/`new`/`dupes_in_upload`; matched entry `uploaded`/`db`/`drift`) consistent across Tasks 2 & 4. Operator dict keys match `create_operator(**kwargs)` parameter names. `get_all_operators()` returns the same keys reconciliation reads.
