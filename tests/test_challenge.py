"""Tests for the validation rules and the two analytical queries.

They run against a throwaway in-memory database, so nothing here touches
data/challenge.db. No fixtures and no HTTP client: every test builds the two
or three rows it needs and calls the same functions the application calls.

    pytest -q
"""
import sqlite3
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from api import DEPARTMENTS_ABOVE_AVERAGE, HIRES_BY_QUARTER, Batch  # noqa: E402
from database import SCHEMA  # noqa: E402
from validation import ingest, validate  # noqa: E402

VALID = {"id": 1, "name": "Ada Lovelace", "datetime": "2021-07-27T16:02:08Z",
         "department_id": 1, "job_id": 1}


def fresh_db():
    """An empty database with the schema and one department and one job."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    conn.execute("INSERT INTO departments VALUES (1, 'Engineering')")
    conn.execute("INSERT INTO jobs VALUES (1, 'Data Engineer')")
    return conn


# ------------------------------------------------- Challenge #1.3, the rules
@pytest.mark.parametrize("field", ["id", "name", "datetime", "department_id", "job_id"])
def test_every_field_is_required(field):
    row = dict(VALID, **{field: ""})
    valid, rejected = validate(fresh_db(), "hired_employees", [row])
    assert valid == []
    assert f"{field} is required" in rejected[0]["errors"]


@pytest.mark.parametrize("moment", ["2021-05-30", "30/05/2021", "20210530T054346Z", "not-a-date"])
def test_datetime_must_be_iso(moment):
    valid, rejected = validate(fresh_db(), "hired_employees", [dict(VALID, datetime=moment)])
    assert valid == []
    assert "ISO-8601" in rejected[0]["errors"][0]


def test_foreign_keys_must_exist():
    conn = fresh_db()
    _, rejected = validate(conn, "hired_employees", [dict(VALID, department_id=999)])
    assert "department_id 999 does not exist" in rejected[0]["errors"]
    _, rejected = validate(conn, "hired_employees", [dict(VALID, job_id=999)])
    assert "job_id 999 does not exist" in rejected[0]["errors"]


def test_valid_row_is_accepted():
    valid, rejected = validate(fresh_db(), "hired_employees", [VALID])
    assert len(valid) == 1 and rejected == []


def test_invalid_rows_are_not_inserted_but_are_logged():
    conn = fresh_db()
    result = ingest(conn, "hired_employees", [VALID, dict(VALID, id=2, name="")], source="api")

    assert (result["received"], result["inserted"], result["rejected"]) == (2, 1, 1)
    assert conn.execute("SELECT COUNT(*) FROM hired_employees").fetchone()[0] == 1
    assert conn.execute("SELECT COUNT(*) FROM rejected_records").fetchone()[0] == 1


# ------------------------------------------------- Challenge #1.2, the bounds
def test_batch_must_hold_between_1_and_1000_rows():
    Batch(rows=[VALID])                                    # the lower bound
    Batch(rows=[VALID] * 1000)                             # the upper bound
    for size in (0, 1001):
        with pytest.raises(ValueError):
            Batch(rows=[VALID] * size)


# ------------------------------------------------------------ Challenge #2
def test_queries_against_a_hand_built_fixture():
    """Six hires with answers you can work out on paper - plus one from 2022
    that must be excluded."""
    conn = fresh_db()
    conn.execute("INSERT INTO departments VALUES (2, 'Support')")
    rows = [
        dict(VALID, id=1, datetime="2021-02-01T00:00:00Z", department_id=1),  # Q1
        dict(VALID, id=2, datetime="2021-05-01T00:00:00Z", department_id=1),  # Q2
        dict(VALID, id=3, datetime="2021-08-01T00:00:00Z", department_id=1),  # Q3
        dict(VALID, id=4, datetime="2021-11-01T00:00:00Z", department_id=1),  # Q4
        dict(VALID, id=5, datetime="2021-11-02T00:00:00Z", department_id=1),  # Q4
        dict(VALID, id=6, datetime="2021-03-01T00:00:00Z", department_id=2),  # Q1
        dict(VALID, id=7, datetime="2022-03-01T00:00:00Z", department_id=2),  # excluded
    ]
    assert ingest(conn, "hired_employees", rows, source="test")["inserted"] == 7

    quarters = [dict(r) for r in conn.execute(HIRES_BY_QUARTER, ("2021",))]
    assert quarters == [
        {"department": "Engineering", "job": "Data Engineer", "Q1": 1, "Q2": 1, "Q3": 1, "Q4": 2},
        {"department": "Support",     "job": "Data Engineer", "Q1": 1, "Q2": 0, "Q3": 0, "Q4": 0},
    ]

    # Engineering hired 5, Support 1, average 3 -> only Engineering is above it.
    above = [dict(r) for r in conn.execute(DEPARTMENTS_ABOVE_AVERAGE, ("2021",))]
    assert above == [{"id": 1, "department": "Engineering", "hired": 5}]
