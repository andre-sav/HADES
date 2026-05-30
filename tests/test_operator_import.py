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


def test_normalize_operator_name_handles_none():
    assert normalize_operator_name(None) == ""


def test_parse_short_file_missing_rows_does_not_crash():
    short = "title,col\nsubtitle,\nAcme,Bobs\nJohn,Jane\n5551234567,\n"
    result = parse_master_csv(io.StringIO(short))
    assert result.operators[0]["team"] is None  # row 10 missing, no crash


def test_parse_latin1_encoded_file():
    # Windows CP-1252 smart quote (\x92) in a business name must not crash.
    raw = (
        "title,\nsubtitle,\nAcme\x92s Vending,\nJohn Smith,\n"
        "5551234567,\njohn@a.com,\n75201,\nacme.com,\n,\n,\nNorth Texas,\n"
    ).encode("latin-1")
    result = parse_master_csv(io.BytesIO(raw))
    assert result.operators[0]["operator_name"] == "John Smith"


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
