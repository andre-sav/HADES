# tests/test_operator_import.py
import io
import pytest
import pandas as pd

from operator_import import (
    MasterCsvParse,
    normalize_operator_name,
    parse_master_file,
)

# Column-per-operator fixture. Rows are POSITIONAL (header=None), matching the
# real VTI Master layout: row3=business, row4=name, row5=phone, row6=email,
# row7=zip, row8=website, row11=team. Rows 0-2, 9-10 are non-field rows.
# Columns: 0=LABEL column ("Operator Name" etc., must be skipped),
#          1=valid (John), 2=valid w/ messy data + leading-zero zip (Bob),
#          3=wholly empty spacer, 4=data but BLANK name (skip-no-name).
FIXTURE = (
    "x,,,,\n"                                                          # row0
    "x,,,,\n"                                                          # row1
    "x,,,,\n"                                                          # row2
    "Vending Business Name,Acme Vending,Bob's Snacks,,Ghost Co\n"      # row3 business
    "Operator Name,John Smith, Bob   Jones ,,\n"                       # row4 name (col4 blank)
    "Operator Phone #,5551234567,N/A,,5559999999\n"                    # row5 phone
    "Operator Email Address,john@a.com,bob@b.com,,ghost@x.com\n"       # row6 email
    "Operator Zip Code,75201,07030,,30301\n"                           # row7 zip
    "Operator Website Address,acme.com,bobs.com,,ghost.com\n"          # row8 website
    ",,,,\n"                                                           # row9 gap
    ",,,,\n"                                                           # row10 gap
    "TEAM,North Texas,New Jersey\xa0,,Georgia\n"                       # row11 team
)


def _parse(text):
    return parse_master_file(io.StringIO(text))


def test_normalize_collapses_case_and_whitespace():
    assert normalize_operator_name("  John   Smith ") == "john smith"
    assert normalize_operator_name("John Smith") == "john smith"


def test_parse_returns_master_csv_parse():
    result = _parse(FIXTURE)
    assert isinstance(result, MasterCsvParse)


def test_parse_scans_all_columns_not_just_last_five():
    # 5 columns total; cols 1 & 2 are operators (col 0 is the label column).
    result = _parse(FIXTURE)
    assert result.total_columns == 5
    names = [op["operator_name"] for op in result.operators]
    assert names == ["John Smith", "Bob Jones"]  # in column order, label skipped


def test_parse_skips_label_column():
    result = _parse(FIXTURE)
    assert result.label_columns == 1  # column 0
    names = [op["operator_name"] for op in result.operators]
    assert "Operator Name" not in names  # label never imported as an operator


def test_parse_skips_empty_spacer_and_records_blank_name_column():
    result = _parse(FIXTURE)
    assert result.empty_columns == 1            # column 3
    assert result.skipped_no_name == [4]        # column 4 index (data, no name)


def test_parse_accounting_identity_closes():
    # Every column lands in exactly one bucket — the no-silent-loss guarantee.
    r = _parse(FIXTURE)
    assert (len(r.operators) + len(r.skipped_no_name)
            + r.empty_columns + r.label_columns) == r.total_columns


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


def test_parse_xlsx_file_matches_csv():
    # Same data via .xlsx routes through read_excel and yields the same result.
    df = pd.read_csv(io.StringIO(FIXTURE), header=None, dtype=str)
    buf = io.BytesIO()
    df.to_excel(buf, header=False, index=False)
    buf.seek(0)
    result = parse_master_file(buf, filename="Master_Data.xlsx")
    names = [op["operator_name"] for op in result.operators]
    assert names == ["John Smith", "Bob Jones"]
    assert result.label_columns == 1
    assert result.skipped_no_name == [4]


def test_normalize_operator_name_handles_none():
    assert normalize_operator_name(None) == ""


def test_parse_short_file_missing_rows_does_not_crash():
    # Fewer rows than MASTER_ROW_TEAM (11): must not crash; team -> None.
    short = "a,b\na,b\na,b\na,Bobs\na,John\na,5551234567\n"
    result = parse_master_file(io.StringIO(short))
    assert all(op["team"] is None for op in result.operators)


def test_parse_latin1_encoded_file():
    # Windows CP-1252 smart quote (\x92) in a business name must not crash.
    raw = (
        "filler,\ntitle,\nsubtitle,\nAcme\x92s Vending,\nJohn Smith,\n"
        "5551234567,\njohn@a.com,\n75201,\nacme.com,\n,\n,\nNorth Texas,\n"
    ).encode("latin-1")
    result = parse_master_file(io.BytesIO(raw))
    assert result.operators[0]["operator_name"] == "John Smith"


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
    assert out["dupes_in_upload"] == ["Dup Co"]  # original name of first occurrence
    assert [n["operator_name"] for n in out["new"]] == ["Dup Co"]  # only first


def test_reconcile_no_drift_when_upload_none_and_db_empty():
    # None (upload) and "" (DB) are equivalent -> no drift flagged.
    parsed = [{"operator_name": "John Smith", "operator_phone": None,
               "vending_business_name": "Acme Vending", "operator_email": "john@a.com",
               "operator_zip": "75201", "operator_website": "acme.com", "team": "North Texas"}]
    existing = [_db_row("John Smith")]
    existing[0]["operator_phone"] = ""
    out = reconcile_operators(parsed, existing)
    assert "operator_phone" not in out["matched"][0]["drift"]


def test_reconcile_drift_when_upload_has_value_db_has_none():
    # Upload provides a value the DB lacks (None) -> drift flagged.
    parsed = [{"operator_name": "John Smith", "operator_phone": "(555) 123-4567",
               "vending_business_name": "Acme Vending", "operator_email": "john@a.com",
               "operator_zip": "75201", "operator_website": "acme.com", "team": "New Team"}]
    existing = [_db_row("John Smith")]
    existing[0]["team"] = None
    out = reconcile_operators(parsed, existing)
    drift = out["matched"][0]["drift"]
    assert "team" in drift
    assert drift["team"] == ("New Team", None)


def test_reconcile_db_match_plus_intra_upload_duplicate():
    # An operator both in the DB and duplicated in the upload: first occurrence
    # -> matched; second -> dupes; nothing leaks into new.
    parsed = [
        {"operator_name": "John Smith", "operator_phone": "(555) 123-4567",
         "vending_business_name": "Acme Vending", "operator_email": "john@a.com",
         "operator_zip": "75201", "operator_website": "acme.com", "team": "North Texas"},
        {"operator_name": "john smith", "operator_phone": "(555) 123-4567",
         "vending_business_name": "Acme Vending", "operator_email": "john@a.com",
         "operator_zip": "75201", "operator_website": "acme.com", "team": "North Texas"},
    ]
    existing = [_db_row("John Smith")]
    out = reconcile_operators(parsed, existing)
    assert len(out["matched"]) == 1
    assert out["new"] == []
    assert out["dupes_in_upload"] == ["John Smith"]


def test_reconcile_counts_skipped_duplicate_columns():
    # [Alice, Alice, Bob] with none in DB: new=[Alice, Bob], one Alice discarded.
    def _op(name):
        return {"operator_name": name, "operator_phone": None,
                "vending_business_name": None, "operator_email": None,
                "operator_zip": None, "operator_website": None, "team": None}
    parsed = [_op("Alice"), _op("Alice"), _op("Bob")]
    out = reconcile_operators(parsed, [])
    assert out["skipped_dupe_columns"] == 1
    assert out["dupes_in_upload"] == ["Alice"]
    assert [n["operator_name"] for n in out["new"]] == ["Alice", "Bob"]
