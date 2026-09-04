"""Historical migration: the three CSV files into SQLite.

    python load_csv.py            # load into the existing database
    python load_csv.py --reset    # drop and recreate the tables first

The files have no header row, so the column order comes from the data
dictionary in the brief (see COLUMNS in validation.py). Rows are loaded in
batches of 1000 - the same limit the API enforces - so memory does not grow
with the size of the file.
"""
import csv
import os
import sys
from pathlib import Path

from database import connect, create_schema
from validation import COLUMNS, ingest

RAW_DIR = Path(os.getenv("RAW_DIR", Path(__file__).parent / "data" / "raw"))
BATCH_SIZE = 1000

# Parents before children, so the foreign keys of hired_employees resolve.
FILES = [
    ("departments", "departments.csv"),
    ("jobs", "jobs.csv"),
    ("hired_employees", "hired_employees.csv"),
]


def read_csv(path, columns):
    """Yield one dict per line, mapping positions to the column names."""
    with path.open(newline="", encoding="utf-8-sig") as handle:
        for line in csv.reader(handle):
            if not line or all(not cell.strip() for cell in line):
                continue  # blank line
            row = {}
            for index, column in enumerate(columns):
                value = line[index].strip() if index < len(line) else ""
                row[column] = value or None  # an empty cell means missing
            yield row


def batches(rows, size):
    """Group an iterable into lists of `size` items."""
    batch = []
    for row in rows:
        batch.append(row)
        if len(batch) == size:
            yield batch
            batch = []
    if batch:
        yield batch


def main():
    conn = connect()
    create_schema(conn, reset="--reset" in sys.argv)

    print(f"{'table':<18}{'read':>8}{'inserted':>10}{'rejected':>10}")
    total_rejected = 0

    for table, filename in FILES:
        path = RAW_DIR / filename
        read = inserted = rejected = 0
        row_number = 1
        for batch in batches(read_csv(path, COLUMNS[table]), BATCH_SIZE):
            result = ingest(conn, table, batch, source="csv", start_row=row_number)
            read += result["received"]
            inserted += result["inserted"]
            rejected += result["rejected"]
            row_number += len(batch)
        total_rejected += rejected
        print(f"{table:<18}{read:>8}{inserted:>10}{rejected:>10}")

    if total_rejected:
        print(f"\n{total_rejected} record(s) rejected -> table `rejected_records`")
        print('   python sql.py "SELECT errors, COUNT(*) FROM rejected_records GROUP BY 1"')
    conn.close()


if __name__ == "__main__":
    main()
