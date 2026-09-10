#!/usr/bin/env python
"""Print the shape of the connected database. Reads nothing but the catalog.

`create table if not exists` skips a table that already exists, whatever shape
it is in, so a database carried over from an earlier version of the app can
satisfy the baseline migration and still be missing columns the later
migrations depend on. This reports what is actually there so the difference can
be reconciled deliberately rather than guessed at.

    python scripts/inspect_schema.py

No row contents are printed, only table and column names and row counts.
"""

from __future__ import annotations

import sys
from pathlib import Path

import psycopg2

sys.path.insert(0, str(Path(__file__).resolve().parent))

from apply_migrations import database_dsn  # noqa: E402


TABLES = """
select table_name
from information_schema.tables
where table_schema = 'public' and table_type = 'BASE TABLE'
order by table_name
"""

COLUMNS = """
select table_name, column_name, data_type, is_nullable
from information_schema.columns
where table_schema = 'public'
order by table_name, ordinal_position
"""


def main() -> int:
    connection = psycopg2.connect(database_dsn())

    try:
        with connection.cursor() as cursor:
            cursor.execute(TABLES)
            tables = [row[0] for row in cursor.fetchall()]

            cursor.execute(COLUMNS)
            columns: dict[str, list[str]] = {}

            for table, column, data_type, nullable in cursor.fetchall():
                null = "" if nullable == "YES" else " not null"
                columns.setdefault(table, []).append(f"{column} {data_type}{null}")

            print(f"\n{len(tables)} table(s) in schema public:\n")

            for table in tables:
                cursor.execute(f'select count(*) from public."{table}"')
                count = cursor.fetchone()[0]
                print(f"  {table}  ({count} rows)")

                for column in columns.get(table, []):
                    print(f"      {column}")

                print()
    finally:
        connection.close()

    return 0


if __name__ == "__main__":
    sys.exit(main())
