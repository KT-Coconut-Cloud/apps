import csv
import json
from dataclasses import replace

from pipeline import review
from tests.conftest import read_out, write_out


def reason(result, code, pattern=None):
    return next(r for r in result["statistics"]["by_reason"]
                if r["code"] == code and r.get("pattern") == pattern)


def test_clean_statistics(rules, out_dir):
    result = review.run(rules, out_dir, "20261123-01")
    assert result["statistics"] == {
        "total_rows": 6, "failed_rows": 0, "failed_row_rate_percent": 0.0,
        "total_files": 1, "failed_files": 0, "file_issue_count": 0, "by_reason": [],
    }


def test_overlapping_reasons_count_one_row(rules, table, out_dir):
    rows = read_out(out_dir, table)
    rows[0]["region"] = "010-0000-0001"
    rows[0]["payment_token"] = "invalid-token"
    write_out(out_dir, table, rows)
    result = review.run(rules, out_dir, "20261123-01")
    stats = result["statistics"]
    assert not result["passed"]
    assert stats["failed_rows"] == 1
    assert stats["failed_row_rate_percent"] == 16.666667
    assert reason(result, "pii_pattern", "phone")["failed_rows"] == 1
    assert reason(result, "invalid_token_format")["failed_rows"] == 1
    assert "010-0000-0001" not in json.dumps(result)
    assert "invalid-token" not in json.dumps(result)
    assert "indices" not in json.dumps(result)


def test_same_reason_across_columns_deduplicates_rows(rules, table, out_dir):
    rows = read_out(out_dir, table)
    rows[0]["region"] = "010-0000-0001"
    rows[0]["gender"] = "010-0000-0002"
    rows[1]["region"] = "010-0000-0003"
    write_out(out_dir, table, rows)
    result = review.run(rules, out_dir, "20261123-01")
    phone = reason(result, "pii_pattern", "phone")
    assert phone["failed_rows"] == 2
    assert phone["affected_cells"] == 3
    assert phone["issue_count"] == 2  # two column-specific messages
    assert result["statistics"]["failed_rows"] == 2


def test_legacy_message_count_does_not_become_row_count(rules, table, out_dir):
    rows = read_out(out_dir, table)
    for row in rows[:3]:
        row["payment_token"] = "invalid"
    write_out(out_dir, table, rows)
    result = review.run(rules, out_dir, "20261123-01")
    token = reason(result, "invalid_token_format")
    assert token["failed_rows"] == 3
    assert token["issue_count"] == 1
    # One format message and one duplicate-value message, as in existing reports.
    check = next(c for c in result["checks"] if c["item"] == "tokenization")
    assert check["value"] == 2
    assert result["statistics"]["failed_row_rate_percent"] == 50.0


def test_all_members_of_duplicate_group_are_affected(rules, table, out_dir):
    rows = read_out(out_dir, table)
    rows[1]["payment_token"] = rows[0]["payment_token"]
    write_out(out_dir, table, rows)
    result = review.run(rules, out_dir, "20261123-01")
    assert reason(result, "duplicate_value")["failed_rows"] == 2
    assert result["statistics"]["failed_rows"] == 2


def test_file_errors_do_not_invent_failed_rows(rules, table, out_dir):
    rows = read_out(out_dir, table)
    write_out(out_dir, table, [{**r, "name": "x"} for r in rows])
    result = review.run(rules, out_dir, "20261123-01")
    stats = result["statistics"]
    assert not result["passed"]
    assert stats["total_rows"] == 6 and stats["failed_rows"] == 0
    assert stats["failed_files"] == 1 and stats["file_issue_count"] == 2
    assert all(r["scope"] == "file" for r in stats["by_reason"])


def test_empty_output_has_no_division_by_zero(rules, table, out_dir):
    with (out_dir / table.filename).open("w", encoding="utf-8-sig", newline="") as f:
        csv.writer(f).writerow(table.output_columns)
    result = review.run(rules, out_dir, "20261123-01")
    stats = result["statistics"]
    assert not result["passed"]
    assert stats["total_rows"] == 0 and stats["failed_rows"] == 0
    assert stats["failed_row_rate_percent"] is None
    assert reason(result, "empty_output")["scope"] == "file"


def test_row_positions_in_different_tables_are_distinct(rules, table, out_dir):
    rows = read_out(out_dir, table)
    rows[0]["gender"] = "invalid"
    write_out(out_dir, table, rows)
    second = replace(table, name="second", output={**table.output, "filename": "second.csv"})
    (out_dir / second.filename).write_bytes((out_dir / table.filename).read_bytes())
    rules = replace(rules, tables={table.name: table, second.name: second})
    result = review.run(rules, out_dir, "20261123-01")
    stats = result["statistics"]
    assert stats["total_rows"] == 12 and stats["failed_rows"] == 2
    assert stats["failed_files"] == 2
    assert reason(result, "value_not_allowed")["failed_rows"] == 2


def test_missing_required_column_is_file_error(rules, table, out_dir):
    rows = [{k: v for k, v in r.items() if k != "gender"} for r in read_out(out_dir, table)]
    write_out(out_dir, table, rows)
    result = review.run(rules, out_dir, "20261123-01")
    assert not result["passed"]
    assert reason(result, "output_columns_mismatch")["scope"] == "file"
    assert result["statistics"]["failed_rows"] == 0
