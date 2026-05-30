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
