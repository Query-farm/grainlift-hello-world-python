# Copyright (c) 2026 Query Farm LLC
# SPDX-License-Identifier: Apache-2.0
"""Unit tests for the in-process hello-world connection."""

import pyarrow as pa
import pytest
from grainlift import AdbcError

from grainlift_hello_world import HelloConnection


@pytest.mark.parametrize("count", [0, 1, 1023, 1024, 1025, 100000])
def test_numbers(count: int) -> None:
    """numbers(n) yields exactly n sequential rows in batches of at most 1024."""
    result = HelloConnection().execute(f"SELECT * FROM numbers({count})")
    batches = list(result.batches)
    assert sum(batch.num_rows for batch in batches) == count
    assert all(batch.num_rows <= 1024 for batch in batches)
    table = pa.Table.from_batches(batches, schema=result.schema)
    assert table.column("number").to_pylist() == list(range(count))


@pytest.mark.parametrize("query", ["SELECT * FROM numbers(100001)", "SELECT * FROM numbers(-1)", "DROP TABLE x"])
def test_invalid_query(query: str) -> None:
    """Unsupported or out-of-range queries raise invalid_arguments."""
    with pytest.raises(AdbcError) as exc:
        HelloConnection().execute(query)
    assert exc.value.status == "invalid_arguments"
