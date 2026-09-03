"""SQLite database: connection and schema.

Plain `sqlite3` from the standard library - no ORM. Every statement in this
project is SQL you can read here and paste into a database console as-is.
"""
import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).parent / "data" / "challenge.db"

TABLES = ("hired_employees", "jobs", "departments", "rejected_records")

SCHEMA = """
CREATE TABLE IF NOT EXISTS departments (
    id         INTEGER PRIMARY KEY,
    department TEXT    NOT NULL
);

CREATE TABLE IF NOT EXISTS jobs (
    id  INTEGER PRIMARY KEY,
    job TEXT    NOT NULL
);

CREATE TABLE IF NOT EXISTS hired_employees (
    id            INTEGER PRIMARY KEY,
    name          TEXT    NOT NULL,
    datetime      TEXT    NOT NULL,
    department_id INTEGER NOT NULL REFERENCES departments(id),
    job_id        INTEGER NOT NULL REFERENCES jobs(id)
);

-- The logging mechanism the brief asks for. A table instead of a text file
-- because a rejection is data: it can be counted, grouped by reason and read
-- back to fix the source record.
CREATE TABLE IF NOT EXISTS rejected_records (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    table_name  TEXT    NOT NULL,
    source      TEXT    NOT NULL,   -- 'csv' or 'api'
    row_number  INTEGER,            -- position in the source file or batch
    payload     TEXT    NOT NULL,   -- the record exactly as it arrived
    errors      TEXT    NOT NULL,   -- why it was rejected
    rejected_at TEXT    NOT NULL DEFAULT (datetime('now'))
);
"""


def connect():
    """Open a connection with foreign keys enabled."""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row          # rows can be read by column name
    conn.execute("PRAGMA foreign_keys = ON")  # SQLite ignores them by default
    return conn


def create_schema(conn, reset=False):
    """Create the tables. With reset=True, drop them first."""
    if reset:
        for table in TABLES:
            conn.execute(f"DROP TABLE IF EXISTS {table}")
    conn.executescript(SCHEMA)
    conn.commit()
