"""VanillaSoft lead-history parsing (HADES-dio). Pure logic — no Streamlit.

Parses a VanillaSoft contact export CSV into rows for the
vanillasoft_leads table so export dedup can see leads created OUTSIDE
HADES (other reps, pre-HADES records, VTI direct). Column facts verified
against the real 294k-row export (2026-07-12): ContactID unique, Added
Date 100% coverage as 'MM/DD/YYYY HH:MM:SS AM', phones clean 10-digit,
6.5% of ZIPs are 4-digit Excel-stripped, HADES-pushed rows carry
'Batch: HADES-...' in Import Notes.
"""
from __future__ import annotations

import csv
import io
import logging
import re
import sys
from dataclasses import dataclass, field
from datetime import datetime

from dedup import normalize_company_name
from utils import normalize_phone_key, normalize_zip

logger = logging.getLogger(__name__)

_ADDED_DATE_FORMAT = "%m/%d/%Y %I:%M:%S %p"
_HADES_MARKER = re.compile(r"HADES-", re.IGNORECASE)

# Sorts after any real date, so a row whose Added Date could not be parsed
# stays inside the dedup window rather than silently falling out of it.
_UNKNOWN_DATE_SENTINEL = "9999-12-31 00:00:00"


@dataclass
class VsParse:
    rows: list[dict] = field(default_factory=list)
    total_rows: int = 0
    skipped_unmatchable: int = 0
    skipped_no_id: int = 0
    hades_count: int = 0
    bad_dates: int = 0


def normalize_phone(raw: str | None) -> str:
    """Reduce a phone to a 10-digit match key ('' when not a usable phone).

    Thin alias for utils.normalize_phone_key so the VS and in-session dedup
    paths cannot drift apart on what counts as a valid number (N2 tail).
    """
    return normalize_phone_key(raw)


def _text_stream(file, filename: str | None):
    """Return a text stream over a path, text file-like, or binary upload.

    Streamlit's UploadedFile is reused across reruns with a retained read
    position; rewind so a re-parse on rerun doesn't read an empty stream.
    """
    if isinstance(file, str):
        return open(file, encoding="utf-8-sig", newline="")
    if hasattr(file, "seek"):
        file.seek(0)
    data = file.read()
    if isinstance(data, bytes):
        text = data.decode("utf-8-sig", errors="replace")
    else:
        text = data.lstrip("\ufeff")
    return io.StringIO(text)


def parse_vs_export(file, filename: str | None = None) -> VsParse:
    """Parse a VanillaSoft contact export into vanillasoft_leads rows.

    Rows with neither a company name nor any phone can never match a
    search result and are skipped (counted in skipped_unmatchable).
    Returns an empty parse (never raises) on an unreadable file so the
    UI can show a friendly warning.
    """
    # Call History is free text spanning years — far beyond csv's default
    # 128KB field cap.
    csv.field_size_limit(sys.maxsize)

    result = VsParse()
    try:
        stream = _text_stream(file, filename)
        reader = csv.DictReader(stream)
        for raw in reader:
            result.total_rows += 1
            row = _parse_row(raw, result)
            if row is not None:
                result.rows.append(row)
    except Exception as e:
        # Untrusted upload boundary: a malformed file must surface as a
        # clear "no data" warning, never crash the page.
        logger.warning("VanillaSoft export unparseable: %s", e)
        return VsParse()
    return result


def _parse_row(raw: dict, result: VsParse) -> dict | None:
    def cell(key: str) -> str:
        return (raw.get(key) or "").strip()

    # contact_id is the PRIMARY KEY and the upsert is INSERT OR REPLACE, so
    # every blank id collides on "" and each row silently overwrites the last
    # (N2 tail). Skip and count instead of collapsing thousands of rows to one.
    contact_id = cell("ContactID")
    if not contact_id:
        result.skipped_no_id += 1
        return None

    company = cell("Company")
    phones = {
        "phone_business": normalize_phone(cell("Business")),
        "phone_mobile": normalize_phone(cell("Mobile")),
        "phone_home": normalize_phone(cell("Home")),
    }
    if not company and not any(phones.values()):
        result.skipped_unmatchable += 1
        return None

    # An unparseable date must NOT become "" — get_vs_dedup_index filters on
    # `added_date >= datetime(...)`, and "" loses that lexicographic
    # comparison, so the row would drop out of the dedup window forever and
    # its company could be re-contacted (N2 tail). Fail safe: treat unknown
    # as recent so the row keeps protecting against duplicates.
    added_date = _UNKNOWN_DATE_SENTINEL
    raw_date = cell("Added Date")
    if raw_date:
        try:
            added_date = datetime.strptime(
                raw_date, _ADDED_DATE_FORMAT).strftime("%Y-%m-%d %H:%M:%S")
        except ValueError:
            result.bad_dates += 1

    is_hades = bool(_HADES_MARKER.search(cell("Import Notes")))
    if is_hades:
        result.hades_count += 1

    return {
        "contact_id": contact_id,
        "company_name": company,
        "company_norm": normalize_company_name(company),
        **phones,
        "zip": normalize_zip(cell("Zip Code")) or "",
        "state": cell("State"),
        "lead_status": cell("Lead Status"),
        "added_date": added_date,
        "is_hades": is_hades,
        "list_source": cell("List Source"),
    }
