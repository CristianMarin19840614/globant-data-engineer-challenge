# Globant Data Engineer Challenge

A proof of concept for migrating historical hiring data into a SQL database,
exposing a REST API to ingest new data with validation, backing every table up
to AVRO, and answering the two analytical questions.

**Stack:** Python 3.11 · SQLite (`sqlite3`, standard library) · FastAPI ·
Pydantic · fastavro · pytest

---

## Quick start

```bash
python -m venv .venv
.venv\Scripts\Activate.ps1          # Windows;  source .venv/bin/activate on Linux/macOS
pip install -r requirements-dev.txt

python load_csv.py --reset          # 1. load the three CSV files
python -m pytest -q                 # 2. run the tests
uvicorn api:app --reload            # 3. serve the API
```

Then open **http://localhost:8000/docs** for the interactive documentation.

With Docker:

```bash
docker build -t globant-challenge .
docker run -p 8000:8000 globant-challenge
```

---

## What the brief asked, and where it is

| # | Requirement | Where |
|---|---|---|
| 1.1 | Historical CSV → SQL migration | `load_csv.py` |
| 1.2 | REST API, batches of 1–1000 rows, all three tables | `api.py` |
| 1.3 | Validation rules; invalid rows not inserted **and** logged | `validation.py` |
| 1.4 | Backup every table to AVRO on the filesystem | `avro_backup.py` |
| 1.5 | Restore a table from an AVRO backup | `avro_backup.py` |
| 2.1 | Hires per job and department by quarter (2021) | `HIRES_BY_QUARTER` in `api.py` |
| 2.2 | Departments above the average hiring (2021) | `DEPARTMENTS_ABOVE_AVERAGE` in `api.py` |

---

## The one design decision

```
   data/raw/*.csv                       POST /hired-employees
   (no header row)                      (JSON, 1–1000 rows)
          │                                      │
          └──────────────►  ingest()  ◄──────────┘
                              │
                 ┌────────────┴────────────┐
             valid rows                invalid rows
                 │                          │
                 ▼                          ▼
   departments · jobs · hired_employees   rejected_records
```

Both entry points call the same `ingest()` in `validation.py`. There is exactly
one definition of a valid record, so a row the API would reject can never get
in through the migration script, and the other way round.

---

## Project structure

```
database.py       connection and schema (all the DDL, in plain SQL)
validation.py     the four rules of the brief, and the shared ingest()
load_csv.py       historical migration, in batches of 1000
avro_backup.py    backup to AVRO and restore from it
api.py            the REST API and the two analytical queries
tests/            14 tests, no fixtures and no HTTP client
data/raw/         the CSV files provided with the challenge
```

Nine files, no framework layers, no ORM. The SQL is written out and can be run
in any SQLite console exactly as it appears in the code.

---

## Validation rules, and what they caught

The four rules come straight from the brief:

1. all five fields are required
2. `datetime` must be ISO-8601 — `2021-07-27T16:02:08Z`
3. `department_id` must exist in `departments`
4. `job_id` must exist in `jobs`

An `id` that already exists is also rejected: overwriting a historical record
without telling anyone destroys information, so a duplicate is reported and the
caller decides.

Loading the provided files:

```
table                 read  inserted  rejected
departments             12        12         0
jobs                   183       183         0
hired_employees       1999      1929        70
```

The arithmetic closes: **1,929 + 70 = 1,999**. All 70 rejections are missing
mandatory fields — 21 `department_id`, 19 `name`, 16 `job_id`, 14 `datetime`.
There are no malformed dates and no orphan foreign keys in this dataset.

Every rejection is stored in `rejected_records` with the payload as it arrived,
its position in the source file and the reason:

```sql
SELECT errors, COUNT(*) FROM rejected_records GROUP BY errors;
```

---

## The two queries

**2.1 — hires per job and department, by quarter**

`GET /analytics/hires-by-quarter?year=2021` → 933 rows, ordered alphabetically
by department and job. Quarter totals: **249 / 454 / 453 / 487 = 1,643 hires**.

**2.2 — departments above the average**

`GET /analytics/departments-above-average?year=2021` → 7 departments, ordered
by hires descending. The average is **136.92**.

| department | hired |
|---|---|
| Support | 216 |
| Engineering | 205 |
| Human Resources | 201 |
| Services | 200 |
| Business Development | 185 |
| Research and Development | 148 |
| Marketing | 142 |

The year is a bind parameter in both queries, with 2021 as the default.

---

## Design decisions

**Plain `sqlite3` instead of an ORM.** SQLite needs nothing installed, so the
reviewer runs the project with one command. Without an ORM the SQL stays
visible and reviewable, which for an analytical workload is the part worth
reading. The cost is that moving to PostgreSQL means rewriting the connection
and adjusting `strftime`, rather than changing a URL.

**The rejection log is a table, not a file.** The brief lets me define the
logging mechanism. A table can be counted, grouped by reason and read back to
fix the source record; a text file cannot.

**A duplicate id is a rejection, not an upsert.** For a master-data feed an
upsert would be right. For a historical load it is not.

**The average is over the departments that hired.** Departments with zero hires
would drag the mean down and inflate the result. It is an interpretation, not a
fact — with this dataset both readings return the same seven, because all
twelve departments hired in 2021.

**Restoring a parent table defers the foreign-key check.** Emptying
`departments` breaks the foreign keys of `hired_employees` in the middle of the
transaction, even though the same ids come straight back. `PRAGMA
defer_foreign_keys` moves the check to `COMMIT` — it does not switch it off, so
a genuinely inconsistent backup still fails.

**One status code, an explicit body.** Every ingestion answers `200` with
`received`, `inserted`, `rejected` and one entry per rejected row. A production
API would distinguish `201`, `207` and `422`; here the body is authoritative
and the contract is smaller.

---

## Security considerations

The API has no authentication: it is a proof of concept meant to be run
locally. What I would add before it was reachable by anyone else, in order:

1. **Authentication on the write endpoints** — an API key header for a first
   step, OAuth2 with scopes (`ingest:write`, `backup:admin`, `analytics:read`)
   for anything real. The analytical endpoints can stay open.
2. **TLS at the gateway**, so credentials and payloads are not sent in clear.
3. **Rate limiting per client**, since the ingestion endpoints accept a
   thousand rows per request.
4. **Audit logging** of who ingested what, alongside the rejection log.

What is already in place: no SQL is built by string concatenation — every
query uses bind parameters, so the ingestion endpoints cannot be used for SQL
injection; the batch size is capped; and the container runs the app without
extra privileges.

---

## What I did not do, and what I would do next

- **Schema migrations.** The schema is created with `CREATE TABLE IF NOT
  EXISTS`. Real environments need versioned migrations (Alembic).
- **A bulk replay of the quarantine.** A corrected row can be resubmitted
  through the API, but nothing retries `rejected_records` in bulk.
- **Concurrency.** One process against a SQLite file says nothing about
  simultaneous writers. This would move to PostgreSQL before being shared.
- **Observability.** There are no metrics and no alert on the rejection rate,
  which for a data pipeline is the single most useful signal there is.

---

**Cristian Gregory Marin Chavez** — Senior Data Engineer
cristian.marin@pucp.pe
