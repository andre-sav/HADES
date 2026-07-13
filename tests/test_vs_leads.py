"""Tests for vs_leads.py — VanillaSoft lead-history parsing (HADES-dio).

The VS contact export is the source of truth for leads created OUTSIDE
HADES (other reps, pre-HADES 2024 records, VTI direct). Parsing it into
the vanillasoft_leads table lets export dedup see them.
"""

import io
import sys
from unittest.mock import MagicMock


sys.modules.setdefault("streamlit", MagicMock())
sys.modules.setdefault("libsql_experimental", MagicMock())

from vs_leads import VsParse, normalize_phone, parse_vs_export


# Header matches the real VS export (77 cols in production; the parser
# reads by name so a subset with the consumed columns is representative).
HEADER = (
    '"ContactID","Company","State","Zip Code","Lead Status","Added Date",'
    '"Business","Mobile","Home","List Source","Import Notes","Call History"'
)


def make_csv(*rows: str, bom: bool = False) -> io.StringIO:
    text = HEADER + "\n" + "\n".join(rows) + "\n"
    if bom:
        return io.BytesIO(text.encode("utf-8-sig"))
    return io.StringIO(text)


GOOD_ROW = (
    '"439062737","Woodmere Health Care Center, Inc.","NY","11598","Warm",'
    '"01/18/2026 10:38:24 AM","5163749300","","","Intelemark","note",""'
)


class TestNormalizePhone:
    def test_clean_ten_digit_passthrough(self):
        assert normalize_phone("5163749300") == "5163749300"

    def test_formatted_phone_stripped_to_digits(self):
        assert normalize_phone("(516) 374-9300") == "5163749300"

    def test_leading_country_code_one_stripped(self):
        assert normalize_phone("1-516-374-9300") == "5163749300"

    def test_garbage_and_short_numbers_empty(self):
        assert normalize_phone("call front desk") == ""
        assert normalize_phone("12345") == ""
        assert normalize_phone(None) == ""


class TestParseVsExport:
    def test_happy_row_all_fields(self):
        result = parse_vs_export(make_csv(GOOD_ROW))
        assert isinstance(result, VsParse)
        assert result.total_rows == 1
        (row,) = result.rows
        assert row["contact_id"] == "439062737"
        assert row["company_name"] == "Woodmere Health Care Center, Inc."
        assert row["company_norm"]  # normalized via dedup.normalize_company_name
        assert row["state"] == "NY"
        assert row["zip"] == "11598"
        assert row["lead_status"] == "Warm"
        assert row["added_date"] == "2026-01-18 10:38:24"
        assert row["phone_business"] == "5163749300"
        assert row["is_hades"] is False
        assert row["list_source"] == "Intelemark"

    def test_hades_batch_marker_detected(self):
        row = (
            '"1","Acme Corp","TX","75201","","03/10/2026 06:21:54 AM",'
            '"2145550100","","","","Batch: HADES-20260306-001 | Score: 82",""'
        )
        result = parse_vs_export(make_csv(row))
        assert result.rows[0]["is_hades"] is True
        assert result.hades_count == 1

    def test_four_digit_excel_stripped_zip_zero_padded(self):
        row = '"2","Bridgeport Co","CT","6614","","01/01/2026 01:00:00 PM","2035550100","","","","",""'
        result = parse_vs_export(make_csv(row))
        assert result.rows[0]["zip"] == "06614"

    def test_zip_plus_four_truncated(self):
        row = '"3","Acme","NY","11598-1234","","01/01/2026 01:00:00 PM","5163749300","","","","",""'
        result = parse_vs_export(make_csv(row))
        assert result.rows[0]["zip"] == "11598"

    def test_unmatchable_rows_skipped_and_counted(self):
        # No company AND no phone -> can never match anything; don't store.
        row = '"4","","","","","01/16/2017 08:03:07 AM","","","","","",""'
        result = parse_vs_export(make_csv(row, GOOD_ROW))
        assert result.total_rows == 2
        assert result.skipped_unmatchable == 1
        assert len(result.rows) == 1

    def test_phone_only_row_kept(self):
        # 98.9% have a phone; a phone with no company is still matchable.
        row = '"5","","TX","","","01/01/2026 01:00:00 PM","","2145550199","","","",""'
        result = parse_vs_export(make_csv(row))
        assert len(result.rows) == 1
        assert result.rows[0]["phone_mobile"] == "2145550199"

    def test_multiline_call_history_field(self):
        row = (
            '"6","Beta Inc","TX","75201","Dead","02/02/2026 02:00:00 PM",'
            '"2145550100","","","","","line one\nline two\nline three"'
        )
        result = parse_vs_export(make_csv(row))
        assert result.rows[0]["company_name"] == "Beta Inc"

    def test_bad_added_date_kept_with_empty_date(self):
        row = '"7","Gamma LLC","TX","75201","","not a date","2145550100","","","","",""'
        result = parse_vs_export(make_csv(row))
        assert result.rows[0]["added_date"] == ""
        assert result.bad_dates == 1

    def test_utf8_sig_bom_handled(self):
        result = parse_vs_export(make_csv(GOOD_ROW, bom=True))
        assert result.rows[0]["contact_id"] == "439062737"

    def test_same_file_object_parses_twice(self):
        # Streamlit UploadedFile is reused across reruns with a retained
        # read position — parser must rewind (bd memory: operator import bug).
        f = make_csv(GOOD_ROW)
        first = parse_vs_export(f)
        second = parse_vs_export(f)
        assert len(first.rows) == len(second.rows) == 1

    def test_unreadable_file_returns_empty_parse(self):
        result = parse_vs_export(io.BytesIO(b"\x00\x01\x02"))
        assert result.rows == []


class TestVsLeadsMixin:
    def _db(self):
        from db import TursoDatabase

        db = TursoDatabase.__new__(TursoDatabase)
        db.execute = MagicMock(return_value=[])
        db.execute_many = MagicMock()
        db.execute_write = MagicMock()
        return db

    def _row(self, **overrides):
        row = {
            "contact_id": "439062737",
            "company_name": "Woodmere Health Care Center, Inc.",
            "company_norm": "woodmere health care center",
            "phone_business": "5163749300",
            "phone_mobile": "",
            "phone_home": "",
            "zip": "11598",
            "state": "NY",
            "lead_status": "Warm",
            "added_date": "2026-01-18 10:38:24",
            "is_hades": False,
            "list_source": "Intelemark",
        }
        row.update(overrides)
        return row

    def test_upsert_uses_insert_or_replace_keyed_on_contact_id(self):
        db = self._db()
        db.upsert_vs_leads_batch([self._row()])
        sql = db.execute_many.call_args[0][0]
        assert "INSERT OR REPLACE INTO vanillasoft_leads" in sql
        params = db.execute_many.call_args[0][1]
        assert params[0][0] == "439062737"
        # execute_many rebuilds the VALUES row from the tuple length, so
        # every column must be a bound param — an inline CURRENT_TIMESTAMP
        # would be silently dropped by the multi-row INSERT optimizer.
        assert sql.count("?") == len(params[0])
        assert "CURRENT_TIMESTAMP" not in sql

    def test_upsert_empty_list_is_noop(self):
        db = self._db()
        db.upsert_vs_leads_batch([])
        db.execute_many.assert_not_called()

    def test_dedup_index_excludes_hades_rows_and_applies_cutoff(self):
        db = self._db()
        db.get_vs_dedup_index(days_back=365)
        sql = db.execute.call_args[0][0]
        assert "is_hades = 0" in sql
        assert "added_date >=" in sql
        params = db.execute.call_args[0][1]
        assert "-365 days" in params

    def test_dedup_index_returns_dicts(self):
        db = self._db()
        db.execute = MagicMock(return_value=[
            ("Woodmere", "woodmere", "5163749300", "", "",
             "11598", "NY", "Warm", "2026-01-18 10:38:24"),
        ])
        rows = db.get_vs_dedup_index()
        assert rows == [{
            "company_name": "Woodmere",
            "company_norm": "woodmere",
            "phone_business": "5163749300",
            "phone_mobile": "",
            "phone_home": "",
            "zip": "11598",
            "state": "NY",
            "lead_status": "Warm",
            "added_date": "2026-01-18 10:38:24",
        }]

    def test_stats_counts(self):
        db = self._db()
        db.execute = MagicMock(return_value=[(294000, 2138, "2026-07-10 09:00:00")])
        stats = db.get_vs_leads_stats()
        assert stats == {
            "total": 294000,
            "hades": 2138,
            "latest_added": "2026-07-10 09:00:00",
        }
