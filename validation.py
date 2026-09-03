"""The validation rules, one per bullet of the brief.

This module is the whole point of the design: the CSV loader and the REST API
both call `validate()`, so there is exactly one definition of a valid record
and the two entry points cannot drift apart.
"""
import json
import re

# "datetime must be in ISO format (e.g. 2021-07-27T16:02:08Z)"
ISO_DATETIME = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(Z|[+-]\d{2}:\d{2})$")

# Column order comes from the data dictionary in the brief: the CSV files have
# no header row, so it cannot be read from the file.
COLUMNS = {
    "departments":     ["id", "department"],
    "jobs":            ["id", "job"],
    "hired_employees": ["id", "name", "datetime", "department_id", "job_id"],
}


def _is_empty(value):
    """A blank cell in a CSV means 'missing', and so does an empty string."""
    return value is None or str(value).strip() == ""


def _as_int(value):
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


def validate(conn, table, rows, start_row=1):
    """Split a batch into (valid, rejected).

    Each rejection carries the row's position, the payload as it arrived and
    the list of rules it broke.
    """
    columns = COLUMNS[table]

    # Foreign keys and existing ids are read ONCE per batch, not once per row:
    # three queries for a thousand rows instead of three thousand.
    existing_ids = {r["id"] for r in conn.execute(f"SELECT id FROM {table}")}
    department_ids = job_ids = set()
    if table == "hired_employees":
        department_ids = {r["id"] for r in conn.execute("SELECT id FROM departments")}
        job_ids = {r["id"] for r in conn.execute("SELECT id FROM jobs")}

    valid, rejected, seen_in_batch = [], [], set()

    for offset, row in enumerate(rows):
        errors = []

        # Rule 1: all fields are required.
        for column in columns:
            if _is_empty(row.get(column)):
                errors.append(f"{column} is required")

        row_id = _as_int(row.get("id"))
        if row_id is None and not _is_empty(row.get("id")):
            errors.append("id must be an integer")
        elif row_id is not None and (row_id in existing_ids or row_id in seen_in_batch):
            # An existing id is a rejection, not an overwrite: silently
            # replacing a historical record would destroy information.
            errors.append(f"id {row_id} already exists")

        if table == "hired_employees":
            # Rule 2: datetime must be ISO-8601.
            if not _is_empty(row.get("datetime")):
                if not ISO_DATETIME.match(str(row["datetime"]).strip()):
                    errors.append("datetime must be ISO-8601, e.g. 2021-07-27T16:02:08Z")

            # Rules 3 and 4: the foreign keys must resolve.
            if not _is_empty(row.get("department_id")):
                if _as_int(row["department_id"]) not in department_ids:
                    errors.append(f"department_id {row['department_id']} does not exist")
            if not _is_empty(row.get("job_id")):
                if _as_int(row["job_id"]) not in job_ids:
                    errors.append(f"job_id {row['job_id']} does not exist")

        if errors:
            rejected.append({"row_number": start_row + offset,
                             "payload": row, "errors": errors})
        else:
            seen_in_batch.add(row_id)
            valid.append(row)

    return valid, rejected


def insert(conn, table, rows):
    """Insert already-validated rows."""
    columns = COLUMNS[table]
    conn.executemany(
        f"INSERT INTO {table} ({', '.join(columns)}) "
        f"VALUES ({', '.join('?' * len(columns))})",
        [[row[column] for column in columns] for row in rows],
    )


def save_rejections(conn, table, source, rejections):
    """Persist rejected records - the logging mechanism the brief asks for."""
    conn.executemany(
        "INSERT INTO rejected_records (table_name, source, row_number, payload, errors) "
        "VALUES (?, ?, ?, ?, ?)",
        [(table, source, r["row_number"], json.dumps(r["payload"]), json.dumps(r["errors"]))
         for r in rejections],
    )


def ingest(conn, table, rows, source, start_row=1):
    """Validate, insert what is valid, log what is not. Used by both entry points."""
    valid, rejected = validate(conn, table, rows, start_row)
    insert(conn, table, valid)
    save_rejections(conn, table, source, rejected)
    conn.commit()
    return {"received": len(rows), "inserted": len(valid),
            "rejected": len(rejected), "rejections": rejected}
