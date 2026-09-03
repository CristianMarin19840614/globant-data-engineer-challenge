"""Backup every table to AVRO, and restore one table from its backup.

AVRO and not CSV because the schema travels inside the file: a restore does
not depend on the code that wrote the backup.
"""
import os
from datetime import datetime, timezone
from pathlib import Path

import fastavro

from validation import COLUMNS, insert

# BACKUP_DIR=/data/backups in a container, or a mounted object-storage path.
BACKUP_DIR = Path(os.getenv("BACKUP_DIR", Path(__file__).parent / "data" / "backups"))

AVRO_SCHEMAS = {
    "departments": {
        "type": "record", "name": "Department",
        "fields": [{"name": "id", "type": "int"},
                   {"name": "department", "type": "string"}],
    },
    "jobs": {
        "type": "record", "name": "Job",
        "fields": [{"name": "id", "type": "int"},
                   {"name": "job", "type": "string"}],
    },
    "hired_employees": {
        "type": "record", "name": "HiredEmployee",
        "fields": [{"name": "id", "type": "int"},
                   {"name": "name", "type": "string"},
                   {"name": "datetime", "type": "string"},
                   {"name": "department_id", "type": "int"},
                   {"name": "job_id", "type": "int"}],
    },
}


def backup_table(conn, table):
    """Write every row of one table to a timestamped .avro file."""
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    rows = [dict(row) for row in conn.execute(f"SELECT * FROM {table}")]
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    path = BACKUP_DIR / f"{table}_{stamp}.avro"
    with path.open("wb") as handle:
        fastavro.writer(handle, AVRO_SCHEMAS[table], rows, codec="deflate")
    return {"table": table, "file": str(path), "records": len(rows)}


def backup_all(conn):
    return [backup_table(conn, table) for table in COLUMNS]


def latest_backup(table):
    """The most recent .avro file for a table, or None."""
    files = sorted(BACKUP_DIR.glob(f"{table}_*.avro"))
    return files[-1] if files else None


def restore_table(conn, table):
    """Replace the table's contents with the newest backup."""
    path = latest_backup(table)
    if path is None:
        raise FileNotFoundError(f"no backup found for {table}")
    with path.open("rb") as handle:
        rows = list(fastavro.reader(handle))

    # `departments` and `jobs` are parent tables: emptying one breaks the
    # foreign keys of hired_employees in the middle of the transaction, even
    # though the same ids come straight back. Deferring moves the check to
    # COMMIT - it does not switch it off, so a genuinely broken backup still
    # fails.
    conn.isolation_level = None       # take manual control of the transaction
    try:
        conn.execute("BEGIN")
        conn.execute("PRAGMA defer_foreign_keys = ON")
        conn.execute(f"DELETE FROM {table}")
        insert(conn, table, rows)
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise
    finally:
        conn.isolation_level = ""     # back to the default behaviour
    return {"table": table, "file": str(path), "restored": len(rows)}
