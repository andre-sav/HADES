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


def parse_master_csv(file) -> MasterCsvParse:
    """Parse a column-per-operator Master CSV into operator dicts.

    `file` may be a path or a file-like object. dtype=str prevents
    ZIP/phone float coercion; utf-8-sig strips a BOM if present.
    """
    try:
        df = pd.read_csv(file, header=None, dtype=str, encoding="utf-8-sig")
    except UnicodeDecodeError:
        # Windows Excel often saves CP-1252/latin-1; retry once.
        try:
            if hasattr(file, "seek"):
                file.seek(0)
            df = pd.read_csv(file, header=None, dtype=str, encoding="latin-1")
        except Exception as e:
            logger.warning("Master CSV unparseable (encoding fallback failed): %s", e)
            return MasterCsvParse()
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

    for op in parsed:
        key = normalize_operator_name(op.get("operator_name"))
        if not key:
            continue  # blank-name rows are filtered by parse_master_csv; guard anyway
        if key in seen:
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

    return {"matched": matched, "new": new, "dupes_in_upload": dupes}
