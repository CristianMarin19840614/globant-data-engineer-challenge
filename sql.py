"""Run one SQL statement against the database and print the rows as a table.

    python sql.py "SELECT COUNT(*) FROM hired_employees"
    python sql.py "SELECT errors, COUNT(*) AS n FROM rejected_records GROUP BY errors"
    python sql.py "PRAGMA foreign_key_check"

Here so the demo needs no SQLite client installed - `sqlite3` is a separate
program on Windows, and DB Browser is a download. Nothing else imports this
file; the solution does not depend on it.
"""
import sys

from database import connect

MAX_WIDTH = 64


def cell(value):
    text = "" if value is None else str(value)
    return text if len(text) <= MAX_WIDTH else text[: MAX_WIDTH - 1] + "…"


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return
    rows = connect().execute(sys.argv[1]).fetchall()
    if not rows:
        print("(no rows)")
        return

    columns = list(rows[0].keys())
    table = [[cell(row[c]) for c in columns] for row in rows]
    widths = [max(len(c), *(len(r[i]) for r in table)) for i, c in enumerate(columns)]

    line = "  ".join(c.ljust(w) for c, w in zip(columns, widths))
    print(line)
    print("  ".join("-" * w for w in widths))
    for r in table:
        print("  ".join(v.ljust(w) for v, w in zip(r, widths)))
    print(f"\n{len(rows)} row(s)")


if __name__ == "__main__":
    main()
