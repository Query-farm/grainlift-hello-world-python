# Copyright (c) 2026 Query Farm LLC
# SPDX-License-Identifier: Apache-2.0
"""Unit tests for the hello-world worker, called in-process without a transport."""

import pyarrow as pa
import pytest
from grainlift import AdbcError, QueryResult

from grainlift_hello_world import HelloConnection, HelloStatement, RunningTotal


def statement(sql: str) -> HelloStatement:
    """Create a statement holding the given query."""
    created = HelloConnection().new_statement()
    created.set_sql_query(sql)
    return created


def execute(sql: str) -> QueryResult:
    """Execute a query the way the service does: through a new statement."""
    return statement(sql).execute()


@pytest.mark.parametrize("count", [0, 1, 1023, 1024, 1025, 100000])
def test_numbers(count: int) -> None:
    """numbers(n) yields exactly n sequential rows in batches of at most 1024."""
    result = execute(f"SELECT * FROM numbers({count})")
    batches = list(result.batches)
    assert sum(batch.num_rows for batch in batches) == count
    assert all(batch.num_rows <= 1024 for batch in batches)
    table = pa.Table.from_batches(batches, schema=result.schema)
    assert table.column("number").to_pylist() == list(range(count))


@pytest.mark.parametrize(
    "query",
    [
        "SELECT * FROM numbers(100001)",
        "SELECT * FROM numbers(-1)",
        "SELECT * FROM running_total(100001)",
        "DROP TABLE x",
    ],
)
def test_invalid_query(query: str) -> None:
    """Unsupported or out-of-range queries fail preparation and execution with invalid_arguments."""
    for operation in (statement(query).prepare, statement(query).execute):
        with pytest.raises(AdbcError) as exc:
            operation()
        assert exc.value.status == "invalid_arguments"


@pytest.mark.parametrize(
    ("query", "columns"),
    [
        ("SELECT 'Hello, world!' AS message;", ["message"]),
        ("select * from NUMBERS(5)", ["number"]),
        ("SELECT * FROM running_total(5)", ["number", "total"]),
    ],
)
def test_prepare_and_schema_without_execution(query: str, columns: list[str]) -> None:
    """Preparation, parameter and result schemas work before execution, as DuckDB's adbc_scanner requires."""
    prepared = statement(query)
    prepared.prepare()
    assert prepared.get_parameter_schema() == pa.schema([])
    assert prepared.execute_schema().names == columns
    assert prepared.execute().schema.names == columns


def test_statement_without_query_is_invalid_state() -> None:
    """Executing before setting a query is an ADBC INVALID_STATE error."""
    with pytest.raises(AdbcError) as exc:
        HelloConnection().new_statement().execute()
    assert exc.value.status == "invalid_state"


@pytest.mark.parametrize("count", [0, 1, 1024, 2500])
def test_running_total(count: int) -> None:
    """running_total(n) carries its sum across batch boundaries."""
    result = execute(f"SELECT * FROM running_total({count})")
    assert result.producer is not None
    table = pa.Table.from_batches(list(result.batches), schema=result.schema)
    assert table.column("number").to_pylist() == list(range(count))
    assert table.column("total").to_pylist() == [n * (n + 1) // 2 for n in range(count)]


def test_running_total_state_round_trips() -> None:
    """The producer resumes identically after serialization, as it does between HTTP fetches."""
    producer = RunningTotal(3000)
    first = producer.produce()
    resumed = RunningTotal.decode(producer.encode())
    assert first is not None and resumed == producer
    assert resumed.produce() == producer.produce()
