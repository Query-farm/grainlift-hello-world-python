# Copyright (c) 2026 Query Farm LLC
# SPDX-License-Identifier: Apache-2.0
"""Unit tests for the in-process hello-world connection."""

import pyarrow as pa
import pytest
from grainlift import AdbcError

from grainlift_hello_world import HelloConnection, RunningTotal


@pytest.mark.parametrize("count", [0, 1, 1023, 1024, 1025, 100000])
def test_numbers(count: int) -> None:
    """numbers(n) yields exactly n sequential rows in batches of at most 1024."""
    result = HelloConnection().execute(f"SELECT * FROM numbers({count})")
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
    """Unsupported or out-of-range queries raise invalid_arguments."""
    with pytest.raises(AdbcError) as exc:
        HelloConnection().execute(query)
    assert exc.value.status == "invalid_arguments"


@pytest.mark.parametrize("count", [0, 1, 1024, 2500])
def test_running_total(count: int) -> None:
    """running_total(n) carries its sum across batch boundaries."""
    result = HelloConnection().execute(f"SELECT * FROM running_total({count})")
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
