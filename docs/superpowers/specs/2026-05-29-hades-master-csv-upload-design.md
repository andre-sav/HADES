# Master CSV Upload for Operators — Design

**Date:** 2026-05-29
**Bead:** HADES-ei7
**Status:** Approved design → implementation plan

## Problem

A user migrating from the sibling app **VSDP** wants to bring their operator roster
into HADES by **uploading a Master CSV**, instead of typing each operator into the
Operators page form one at a time.

Today HADES has **no file-upload path** for operators. Operators live only in the
Turso `operators` table and are created via the manual form (`create_operator`) or
Zoho sync. VSDP, by contrast, was file-driven: it read operators from a Master Data
file each run. This feature ports that capability into HADES — but adapted to
HADES's persist-once, DB-driven model, and with a **trust/reconciliation step** the
user explicitly asked for.

## Goals

- Upload a column-per-operator Master CSV and parse **every** operator column
  (VSDP read only the last 5 — HADES reads all).
- Match each parsed operator against existing Turso records by **normalized
  operator name** and **show the matching DB record** so the user can trust the
  match before anything is written.
- Bulk-import **only New (unmatched)** operators. Matched operators are read-only.
- Surface field **drift** on matched operators (uploaded vs stored) for honesty,
  without building an update flow.

## Non-Goals (YAGNI)

- No row-per-operator CSV support (the file is column-oriented; confirmed).
- No updating/overwriting of existing operators from the upload.
- No fuzzy/near-duplicate matching ("Acme Co" vs "Acme Company"). Exact normalized
  name only. This is an explicit, documented limitation.
- No legacy `.xls` (BIFF) support — `.xlsx` and `.csv` only (`.xlsx` added after
  validation showed the real Master file is Excel; `xlrd` intentionally not added).

## Data model (existing, unchanged)

`operators` table — `operator_name TEXT UNIQUE NOT NULL`, `vending_business_name`,
`operator_phone`, `operator_email`, `operator_zip`, `operator_website`, `team`.
Insert via `create_operator(**kwargs)`. `operator_name` UNIQUE → duplicates raise.

## Master CSV layout (column-per-operator)

Each operator is a **column**; fields are at **fixed row positions** (VSDP's proven
layout). Canonical mapping (single source of truth, defined as constants):

| Field                  | Row index |
|------------------------|-----------|
| vending_business_name  | 3         |
| operator_name          | 4         |
| operator_phone         | 5         |
| operator_email         | 6         |
| operator_zip           | 7         |
| operator_website       | 8         |
| team                   | 11        |

Rows 0–2 and 9–10 are non-field rows — handled by positional indexing + null-safe
cell reads. **Column 0 is a field-label column** ("Operator Name", "TEAM", …),
not an operator; it is skipped by content (its name cell == "Operator Name"), not
by index, so a file without a label column never silently drops a real operator.
Real operators start at column 1.

> **VALIDATED (2026-05) against the real `Master_Data_VTI.xlsx`** (1320 columns,
> 1316 operators). The indices above are confirmed. VSDP's old reader used
> `pd.read_excel` with header=0 (consuming row 0), which is why its constants were
> all −1 relative to these; HADES reads with `header=None` so file rows map 1:1.
> Constants live in one place (`MASTER_ROW_*` in `operator_import.py`) for easy
> correction against future Master vintages. Accepts **.xlsx and .csv** (routed
> by extension); `.xls` is not supported (no `xlrd`).

## Architecture

Two layers, cleanly separated so parsing/matching is testable without Streamlit.

### `operator_import.py` (new, pure logic — no Streamlit)

```
parse_master_csv(file) -> MasterCsvParse
reconcile_operators(parsed: list[dict], existing: list[dict]) -> dict
normalize_operator_name(raw: str) -> str
```

`MasterCsvParse` is a small dataclass that carries the parsed operators **and the
diagnostics needed to prove nothing was dropped silently**:

```
@dataclass
class MasterCsvParse:
    operators: list[dict]          # columns that yielded a valid operator
    total_columns: int             # columns in the file
    skipped_no_name: list[int]     # column indices skipped (data present, name blank)
    empty_columns: int             # wholly-empty columns (expected spacers)
```

- **`parse_master_csv(file)`**
  - `pd.read_csv(file, header=None, dtype=str, encoding="utf-8-sig")`
    - `dtype=str` prevents ZIP/phone float coercion and leading-zero loss
      (`07030` staying `07030`, `75201` not `75201.0`). **Critical** — without
      this the import silently corrupts ZIPs and phones.
    - `utf-8-sig` strips a BOM if present.
  - Scan **every** column `0..ncols-1`.
  - For each column, read the 7 fields from the fixed row indices via a
    null-safe `safe_get` (ported from VSDP): coerce `NaN`→"", strip `\xa0` and
    whitespace, treat `"N/A"` (any case) as empty.
  - A column whose `operator_name` cell is empty is **not imported**, but we
    distinguish two cases so nothing vanishes silently:
    - column is *wholly empty* (a spacer) → counted in `empty_columns`, expected.
    - column has *some data* but a blank name → its index is recorded in
      `skipped_no_name`. The UI surfaces this loudly ("⚠ N column(s) had data but
      no operator name and were not imported — rows shown") so a real operator
      with a mis-keyed name cell can't be lost without the user seeing it.
  - Normalize on the way out: `operator_phone` via `utils.format_phone`,
    `operator_zip` via `utils.normalize_zip`. Empty strings → `None` so DB stores
    NULL, matching the manual-form behavior (`value or None`).
  - Returns a `MasterCsvParse` with empty `operators` on an empty/unparseable
    file (UI shows a friendly warning; no exception bubbles to the page).

- **`normalize_operator_name(raw)`** — `lower()`, strip, collapse internal
  whitespace runs to a single space. Shared by parse-side and DB-side so the keys
  line up.

- **`reconcile_operators(parsed, existing)`** returns:
  ```
  {
    "matched": [ {"uploaded": <parsed dict>, "db": <db row dict>,
                  "drift": {field: (uploaded_val, db_val), ...}} , ...],
    "new":     [ <parsed dict>, ... ],
    "dupes_in_upload": [ <normalized_name>, ... ],   # 2+ columns same name
  }
  ```
  - Build `{normalize_operator_name(db.operator_name): db_row}` from `existing`.
    (DB names are UNIQUE, so at most one row per key; if two DB names collapse to
    the same normalized key, keep the first and log a warning.)
  - For each parsed op: in map → **matched** (compute `drift` = fields where the
    uploaded value differs from the stored value, compared on cleaned strings);
    else → **new**.
  - Track normalized names seen more than once **within the upload** →
    `dupes_in_upload` (flagged in UI; only the first is offered for import, since
    the second would violate UNIQUE anyway).

### `pages/3_Operators.py` (UI — thin)

A new "Upload Master CSV" section (an `st.expander` near "+ Add operator"):

1. `st.file_uploader("Master CSV", type=["csv"])`.
2. On upload → `parse_master_csv` (→ `MasterCsvParse`) → load existing operators
   (new `get_all_operators()` helper, or `search_operators` with a large limit) →
   `reconcile_operators(parse.operators, existing)`.
3. Render a **reconciliation summary line first** so totals always add up visibly:
   *"File has C columns → M new, K already in DB, S skipped (no name), E empty."*
   Then:
   - **Skipped-no-name (if any)** — `st.warning` listing the offending column
     indices and their partial data, so a real-but-mis-keyed operator is never
     dropped silently.
   - **Matched (N)** — read-only. For each, show uploaded value beside the stored
     Turso record (id, name, business, phone, email, zip, website, team). Fields
     in `drift` are visually flagged (⚠). Caption: *"Differences are shown for
     reference only and are NOT imported — edit the operator to change stored
     values."* No write.
   - **Dupes-in-upload (if any)** — warn which names appear in multiple columns
     (only the first is offered for import).
   - **New (M)** — table of unmatched operators + a single
     **"Import M new operators"** button.
4. On import → `with db.transaction():` loop `create_operator(**fields)`. Wrap each
   in try/except: a `UNIQUE` violation (race / missed dupe) is skipped and counted,
   not fatal. Report `"Imported X, skipped Y already present"`. `st.toast`, clear
   uploader state, `st.rerun()` so the operator list refreshes.

## Silent-data-loss guarantees (primary design constraint)

Every place data could be dropped or altered without the user knowing is
enumerated here, each with the mechanism that makes it visible. This is the
feature's defining requirement.

| Where loss could hide | Mechanism that prevents it being silent |
|---|---|
| ZIP/phone type coercion (`07030`→`7030`, `75201`→`75201.0`) | `dtype=str` on read; values never pass through float. Locked by a fixture test with a leading-zero ZIP. |
| Changed phone/email/etc. on a **matched** operator | Drift highlight (⚠) beside the stored value + explicit "NOT imported — edit to change" caption. Never silently discarded. |
| A column with data but a **blank name cell** | Recorded in `skipped_no_name`, shown in a `st.warning` with the column's partial data. |
| Two upload columns with the **same name** | `dupes_in_upload` — only the first imports; the rest are reported, not silently swallowed by the UNIQUE constraint. |
| An operator already in the DB (would be a dup) | Counted as Matched and shown; never re-inserted, and the user sees it was recognized. |
| `UNIQUE` violation at import time (race / missed dupe) | Per-row skip **with a count** in the result toast ("Imported X, skipped Y already present"), not a swallowed exception. |
| Whole batch fails mid-import | Single `db.transaction()` → full rollback, so the user never ends up with a silent partial import they believe completed. |
| File parsed to nothing | Friendly explicit warning; never a silent no-op. |
| Counts not adding up | Summary line states C columns = M new + K matched + S skipped + E empty, so the user can verify every column is accounted for. |

The litmus test for any change to this feature: **for every operator column in
the file, the user can see exactly what happened to it.**

## Error handling

- Unparseable / empty CSV → `parse_master_csv` returns `[]`; UI shows
  "No operator data found in the uploaded file. Check the file format."
- Wrong-shape file (too few rows for the fixed indices) → `safe_get` returns "" →
  columns drop out as non-operators → empty result → same friendly warning.
- Import wrapped in a single transaction: any unexpected error rolls back the whole
  batch (no half-imported state). UNIQUE collisions are handled per-row (skip+count)
  and do not trigger rollback.

## Testing

`tests/test_operator_import.py` — no Streamlit needed:

- **Fixture CSV** in column-per-operator layout covering: 3 valid operators, one
  wholly-empty spacer column, one column with data but a **blank name cell**
  (must land in `skipped_no_name`), messy cells (`\xa0`, doubled spaces, `"N/A"`),
  a CT ZIP with a leading zero (`07030`), a numeric-looking ZIP (`75201` must not
  become `75201.0`).
- `parse_master_csv`: all columns scanned (not just last 5); spacer counted in
  `empty_columns`; the blank-name column captured in `skipped_no_name` (the
  silent-loss guard); field cleaning; ZIP/phone kept as strings; empty → None.
- `reconcile_operators`: matched vs new split; normalization tolerance
  (`" John  Smith "` matches DB `"John Smith"`); drift detection (changed phone
  appears in `drift`, unchanged fields do not); `dupes_in_upload` detection.
- Run the **full** suite (`python -m pytest tests/ -x -q --tb=short`) — pre-commit
  hook enforces it.

## Risks / open items

- **Row-index offset (header=None vs VSDP's header=0)** — must be validated against
  a real Master CSV during implementation; constants are centralized so a fix is
  one edit. (Highest-risk item.)
- **No fuzzy matching** — near-duplicate names create separate operators. Documented
  limitation, acceptable for v1.
- **Drift is display-only** — by design; updating existing operators stays in the
  existing Edit flow.
