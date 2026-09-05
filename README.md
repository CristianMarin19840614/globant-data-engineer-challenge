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

To read the database without installing a SQLite client:

```bash
python sql.py "SELECT errors, COUNT(*) FROM rejected_records GROUP BY 1"
python sql.py "PRAGMA foreign_key_check"
```

Then open **http://localhost:8000/docs** for the interactive documentation.

With Docker:

```bash
docker compose run --rm load     # load the CSV files, then exit
docker compose up                # the API on http://localhost:8000
```

The database and the AVRO backups live on a mounted volume, so they survive a
rebuild of the image.

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

Dockerfile · docker-compose.yml    run it anywhere, with a volume for the data
.github/workflows/ci.yml           tests and a migration check on every push
DEPLOYMENT.md                      the cloud path, and what would have to change
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


## Optional visualization

From `globant-challenge`, with the virtual environment active and the CSVs
already loaded, run:

```powershell
python dashboard.py
Start-Process .\dashboard.html
```

`dashboard.py` imports both SQL constants from `api.py`, opens the configured
SQLite database read-only, and writes a self-contained HTML with SVG charts.
It uses the existing project dependencies, requires no running API, JavaScript
or network access, and contains no employee names.

The default year is 2021. The quarter chart totals all department/job pairs;
expand the detail to see all 933 combinations in alphabetical order. The second
chart and table show the seven departments above the active-department average
(1,643 / 12 = 136.92), ordered by `hired DESC`. These are reference results for
the supplied CSVs, not hardcoded values. New database records can change them.
The page is a snapshot: rerun the script after changing the database.

Options: `--year 2021`, `--db data/challenge.db`, `--output dashboard.html`.
Without `--db`, it follows `DB_PATH` from `database.py`. The default HTML is
written beside the script. A missing database fails without creating a file;
a year without hires produces an explicit empty result.

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

## Security

The write surface — the three ingestion endpoints, `backup` and `restore` —
requires an API key. The analytical endpoints stay open so the queries can be
demoed without credentials.

```bash
API_KEY=your-key uvicorn api:app          # enable it
curl -X POST localhost:8000/departments -H "X-API-Key: your-key" ...
```

Leaving `API_KEY` empty disables the check, which is what the test suite and a
local demo use. The key is compared with `secrets.compare_digest`, not `==`: a
plain string comparison stops at the first differing character, and the timing
difference leaks the key one byte at a time.

**This is proof-of-concept authentication and I would not ship it.** A shared
key proves the caller knows a secret; it does not say who they are, cannot be
revoked for one client without rotating it for everyone, and never expires.
What I would add, in order:

1. **OAuth2 with scopes** — `ingest:write`, `backup:admin`, `analytics:read` —
   plugged into the same dependency, so the endpoint signatures do not change.
2. **TLS at the gateway**, so the key and the payloads are not sent in clear.
3. **Rate limiting per client**, since ingestion accepts a thousand rows per
   request.
4. **The key in a managed secret store** rather than an environment variable,
   and **audit logging** of who ingested what, alongside the rejection log.

What is already right: no SQL is built by string concatenation — every query
uses bind parameters, so the ingestion endpoints cannot be used for injection;
the batch size is capped; and unknown tables are rejected by name before any
query is built.

---

## Git workflow

`main` holds the working history. Each unit of work happened on a branch and
came back with a merge commit, so the history shows what was done together:

```
*   merge: environment-driven configuration and the deployment guide
|\
| * feat(config): every path configurable by environment variable
|/
*   merge: docker compose and CI
|\
| * build: compose stack and CI on GitHub Actions
|/
*   merge: API key on the write endpoints
|\
| * feat(security): API key on the write endpoints
|/
* docs: README with instructions, decisions and limitations
* build: minimal Dockerfile
* test: 14 tests over the rules, the bounds and both queries
...
```

Commits follow Conventional Commits (`feat`, `fix`, `test`, `build`, `docs`,
`chore`) with a scope, and the body says why rather than what — the diff
already says what.

---

## Continuous integration

`.github/workflows/ci.yml` runs on every push to `main` or a `feature/**`
branch, and on every pull request. It does two things: runs the test suite,
and then loads the CSV files and asserts the migration still ends at **1,929
inserted and 70 rejected**. A change that silently alters a validation rule
fails the build even if every unit test still passes.

---

## Cloud

The application holds no state of its own: `DB_PATH`, `BACKUP_DIR` and
`RAW_DIR` are environment variables, so the same image runs on a laptop, in a
container and in a cloud runtime.

**It is not deployed.** [`DEPLOYMENT.md`](DEPLOYMENT.md) documents the exact
Cloud Run and Azure Container Apps commands, and — more usefully — what would
have to change first: Cloud Run's filesystem is ephemeral and its instances do
not share one, so a SQLite file on local disk is the wrong shape there. The
first real change is a managed PostgreSQL instance, and the AVRO backups move
to object storage, where they land in exactly the format BigQuery loads
natively.

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
