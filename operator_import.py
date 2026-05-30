# operator_import.py
"""Parse a column-per-operator Master file (.xlsx/.xls/.csv) and reconcile it
against the operators table. Pure logic — no Streamlit. See
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
# Verified against a real VTI Master Data export (2026-05): the first
# operator column is column 1 (column 0 holds the field labels below).
MASTER_ROW_BUSINESS_NAME = 3
MASTER_ROW_OPERATOR_NAME = 4
MASTER_ROW_PHONE = 5
MASTER_ROW_EMAIL = 6
MASTER_ROW_ZIP = 7
MASTER_ROW_WEBSITE = 8
MASTER_ROW_TEAM = 11

# The Master sheet's first column holds the field labels ("Operator Name",
# etc.), not an operator. We detect it by the label in the name row rather
# than by a fixed column index, so a file without a label column never has a
# real operator silently dropped.
MASTER_LABEL_NAME = "Operator Name"


@dataclass
class MasterCsvParse:
    operators: list[dict] = field(default_factory=list)
    total_columns: int = 0
    skipped_no_name: list[int] = field(default_factory=list)
    empty_columns: int = 0
    label_columns: int = 0


def normalize_operator_name(raw: str | None) -> str:
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


def _read_master_dataframe(file, filename: str | None) -> pd.DataFrame:
    """Read a Master file into a positional (header=None) string DataFrame.

    Routes by extension: .xlsx/.xls via read_excel, otherwise CSV with a
    utf-8-sig → latin-1 fallback (Windows Excel often saves CP-1252).
    dtype=str everywhere prevents ZIP/phone float coercion and leading-zero
    loss. Raises on an unreadable file; the caller turns that into an empty
    parse + a user-facing warning.
    """
    name = (filename or "").lower()
    if name.endswith((".xlsx", ".xls")):
        return pd.read_excel(file, header=None, dtype=str)
    try:
        return pd.read_csv(file, header=None, dtype=str, encoding="utf-8-sig")
    except UnicodeDecodeError:
        if hasattr(file, "seek"):
            file.seek(0)
        return pd.read_csv(file, header=None, dtype=str, encoding="latin-1")


def parse_master_file(file, filename: str | None = None) -> MasterCsvParse:
    """Parse a column-per-operator Master file (.xlsx/.xls/.csv) into operators.

    `file` may be a path or a file-like object; `filename` (when given) routes
    .xlsx/.xls through read_excel, else CSV. Each operator is a COLUMN with
    fields at fixed row positions. Column 0 (the field-label column) is skipped
    by content, not index. Returns an empty parse (never raises) on an
    unreadable/empty file so the UI can show a friendly warning.
    """
    try:
        df = _read_master_dataframe(file, filename)
    except Exception as e:
        # Untrusted upload boundary: a malformed file must surface as a clear
        # "no data" warning, never crash the page.
        logger.warning("Master file unparseable: %s", e)
        return MasterCsvParse()

    result = MasterCsvParse(total_columns=int(df.shape[1]))
    label_key = normalize_operator_name(MASTER_LABEL_NAME)

    for col in range(df.shape[1]):
        name = _clean_cell(df, MASTER_ROW_OPERATOR_NAME, col)

        # Skip the field-label column (detected by content, not index).
        if normalize_operator_name(name) == label_key:
            result.label_columns += 1
            continue

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
    ``dupes_in_upload`` (original name of the first occurrence);
    only that first occurrence is offered as new/matched.
    The number of discarded duplicate occurrences is returned as
    ``skipped_dupe_columns`` so callers can account for every column.
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
    seen_display: dict[str, str] = {}  # normalized key -> first original name
    dupes: list[str] = []
    dupe_columns = 0

    for op in parsed:
        key = normalize_operator_name(op.get("operator_name"))
        if not key:
            continue  # blank-name rows are filtered by parse_master_file; guard anyway
        if key in seen:
            dupe_columns += 1
            original = seen_display[key]
            if original not in dupes:
                dupes.append(original)
            continue
        seen.add(key)
        seen_display[key] = op.get("operator_name") or ""

        db_row = by_name.get(key)
        if db_row is not None:
            drift = {}
            for f in _DRIFT_FIELDS:
                up = str(op.get(f) or "")
                cur = str(db_row.get(f) or "")
                if up != cur:
                    drift[f] = (op.get(f), db_row.get(f))
            matched.append({"uploaded": op, "db": db_row, "drift": drift})
        else:
            new.append(op)

    return {
        "matched": matched,
        "new": new,
        "dupes_in_upload": dupes,
        "skipped_dupe_columns": dupe_columns,
    }
