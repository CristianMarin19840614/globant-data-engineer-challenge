"""REST API for the challenge.

    uvicorn api:app --reload      ->  http://localhost:8000/docs

Three ingestion endpoints (one per table), backup and restore, and the two
analytical queries. Every ingestion goes through the same `ingest()` used by
the CSV loader.
"""
import os
import secrets

from fastapi import Depends, FastAPI, Header, HTTPException
from pydantic import BaseModel, Field

from avro_backup import backup_all, restore_table
from database import connect, create_schema
from validation import COLUMNS, ingest

app = FastAPI(
    title="Globant Data Engineer Challenge",
    description="CSV migration, batch ingestion with validation, AVRO backup "
                "and restore, and the two analytical queries.\n\n"
                "Write endpoints require the `X-API-Key` header when API_KEY is set; "
                "the analytical endpoints are always open.",
)


class Batch(BaseModel):
    """1 to 1000 rows per request, as the brief requires."""
    rows: list[dict] = Field(min_length=1, max_length=1000)


# ------------------------------------------------------------------ security
# A shared key on the write surface. Proof-of-concept level and deliberately
# so: it proves the caller knows the secret, it does not say who they are.
# Set API_KEY in the environment; leaving it empty disables the check, which
# is what the tests and a local demo use.
API_KEY = os.getenv("API_KEY", "")


def require_api_key(x_api_key: str | None = Header(default=None)):
    if not API_KEY:
        return                                    # disabled
    if not x_api_key or not secrets.compare_digest(x_api_key, API_KEY):
        # compare_digest, not ==: a plain comparison stops at the first
        # differing character, and the timing leaks the key one byte at a time.
        raise HTTPException(status_code=401,
                            detail="Missing or invalid API key. Send it in the X-API-Key header.")


WRITE = [Depends(require_api_key)]                # the read endpoints stay open


# --------------------------------------------------------------- ingestion
def _ingest(table, batch):
    conn = connect()
    create_schema(conn)
    try:
        result = ingest(conn, table, batch.rows, source="api")
    finally:
        conn.close()
    return result


@app.post("/departments", dependencies=WRITE, summary="Insert departments (1-1000 rows)")
def post_departments(batch: Batch):
    return _ingest("departments", batch)


@app.post("/jobs", dependencies=WRITE, summary="Insert jobs (1-1000 rows)")
def post_jobs(batch: Batch):
    return _ingest("jobs", batch)


@app.post("/hired-employees", dependencies=WRITE, summary="Insert hired employees (1-1000 rows)")
def post_hired_employees(batch: Batch):
    return _ingest("hired_employees", batch)


# ----------------------------------------------------------- backup/restore
@app.post("/backup", dependencies=WRITE, summary="Back every table up to AVRO")
def post_backup():
    conn = connect()
    try:
        return backup_all(conn)
    finally:
        conn.close()


@app.post("/restore/{table}", dependencies=WRITE, summary="Restore one table from its newest AVRO backup")
def post_restore(table: str):
    if table not in COLUMNS:
        raise HTTPException(status_code=404, detail=f"unknown table: {table}")
    conn = connect()
    try:
        return restore_table(conn, table)
    except FileNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error))
    finally:
        conn.close()


# ---------------------------------------------------------------- analytics
# Challenge #2.1 - hires per job and department, by quarter.
HIRES_BY_QUARTER = """
SELECT d.department,
       j.job,
       SUM(CASE WHEN CAST(strftime('%m', h.datetime) AS INTEGER) BETWEEN 1 AND 3  THEN 1 ELSE 0 END) AS Q1,
       SUM(CASE WHEN CAST(strftime('%m', h.datetime) AS INTEGER) BETWEEN 4 AND 6  THEN 1 ELSE 0 END) AS Q2,
       SUM(CASE WHEN CAST(strftime('%m', h.datetime) AS INTEGER) BETWEEN 7 AND 9  THEN 1 ELSE 0 END) AS Q3,
       SUM(CASE WHEN CAST(strftime('%m', h.datetime) AS INTEGER) BETWEEN 10 AND 12 THEN 1 ELSE 0 END) AS Q4
FROM hired_employees h
JOIN departments d ON d.id = h.department_id
JOIN jobs        j ON j.id = h.job_id
WHERE strftime('%Y', h.datetime) = ?
GROUP BY d.department, j.job
ORDER BY d.department, j.job
"""

# Challenge #2.2 - departments that hired above the average.

DEPARTMENTS_ABOVE_AVERAGE = """
WITH hires AS (
    SELECT d.id, d.department, COUNT(*) AS hired
    FROM hired_employees h
    JOIN departments d ON d.id = h.department_id
    WHERE strftime('%Y', h.datetime) = ?
    GROUP BY d.id, d.department
)
SELECT id, department, hired
FROM hires
WHERE hired > (SELECT AVG(hired) FROM hires)
ORDER BY hired DESC
"""


def _query(sql, year):
    conn = connect()
    try:
        return [dict(row) for row in conn.execute(sql, (str(year),))]
    finally:
        conn.close()


@app.get("/analytics/hires-by-quarter",
         summary="Employees hired per job and department, split by quarter")
def hires_by_quarter(year: int = 2021):
    return _query(HIRES_BY_QUARTER, year)


@app.get("/analytics/departments-above-average",
         summary="Departments that hired more than the average")
def departments_above_average(year: int = 2021):
    return _query(DEPARTMENTS_ABOVE_AVERAGE, year)


# ------------------------------------------------------------------- health
@app.get("/health", summary="Row counts, read straight from the database")
def health():
    conn = connect()
    create_schema(conn)
    try:
        tables = list(COLUMNS) + ["rejected_records"]
        return {"status": "ok",
                "counts": {t: conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
                           for t in tables}}
    finally:
        conn.close()
