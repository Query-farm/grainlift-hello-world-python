# Copyright (c) 2026 Query Farm LLC
# SPDX-License-Identifier: Apache-2.0
"""Use the normal ADBC driver manager to query the Python service."""

import os
from pathlib import Path

import adbc_driver_manager.dbapi as adbc


def main():
    with (
        adbc.connect(
            driver=Path(os.environ["GRAINLIFT_DRIVER"]).expanduser().resolve(strict=True),
            entrypoint="AdbcDriverGrainliftInit",
            db_kwargs={
                "grainlift.uri": os.environ.get("GRAINLIFT_ENDPOINT", "http://127.0.0.1:8080"),
                "grainlift.target": "hello",
                "grainlift.auth.bearer_token": os.environ["GRAINLIFT_TOKEN"],
            },
            autocommit=True,
        ) as connection,
        connection.cursor() as cursor,
    ):
        cursor.execute("SELECT 'Hello, world!' AS message")
        print(cursor.fetch_arrow_table().to_pydict())
        cursor.execute("SELECT * FROM numbers(2500)")
        reader = cursor.fetch_record_batch()
        sizes = [batch.num_rows for batch in reader]
        print(f"numbers(2500): {sizes} rows per Arrow batch")
        assert sizes == [1024, 1024, 452]
        cursor.execute("SELECT * FROM numbers(0)")
        empty = cursor.fetch_arrow_table()
        print(f"Empty result: {empty.num_rows} rows, schema: {empty.schema}")


if __name__ == "__main__":
    main()
