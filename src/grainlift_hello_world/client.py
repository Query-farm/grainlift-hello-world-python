# Copyright (c) 2026 Query Farm LLC
# SPDX-License-Identifier: Apache-2.0
"""Use the normal ADBC driver manager to query the Python service."""

import os
from pathlib import Path

import adbc_driver_manager.dbapi as adbc


def main() -> None:
    """Connect through the native ADBC driver and run the example queries.

    Configure with GRAINLIFT_DRIVER (path to the native driver library) and optionally
    GRAINLIFT_ENDPOINT and GRAINLIFT_TOKEN (omit it to connect anonymously).
    """
    endpoint = os.environ.get("GRAINLIFT_ENDPOINT", "http://127.0.0.1:8080")
    options = {"grainlift.uri": endpoint, "grainlift.target": "hello"}
    if endpoint.startswith("tls+tcp://"):
        options.update(
            {
                "grainlift.tls.ca": os.environ["GRAINLIFT_TLS_CA"],
                "grainlift.tls.cert": os.environ["GRAINLIFT_TLS_CERT"],
                "grainlift.tls.key": os.environ["GRAINLIFT_TLS_KEY"],
                "grainlift.tls.server_name": os.environ["GRAINLIFT_TLS_SERVER_NAME"],
            }
        )
    elif token := os.environ.get("GRAINLIFT_TOKEN"):
        options["grainlift.auth.bearer_token"] = token
    with (
        adbc.connect(
            driver=Path(os.environ["GRAINLIFT_DRIVER"]).expanduser().resolve(strict=True),
            entrypoint="AdbcDriverGrainliftInit",
            db_kwargs=options,
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
        cursor.execute("SELECT * FROM running_total(2500)")
        table = cursor.fetch_arrow_table()
        print(f"running_total(2500): last row {table.slice(table.num_rows - 1).to_pylist()[0]}")
        cursor.execute("SELECT * FROM numbers(0)")
        empty = cursor.fetch_arrow_table()
        print(f"Empty result: {empty.num_rows} rows, schema: {empty.schema}")


if __name__ == "__main__":
    main()
