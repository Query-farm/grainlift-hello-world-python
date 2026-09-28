# Copyright (c) 2026 Query Farm LLC
# SPDX-License-Identifier: Apache-2.0
"""A minimal ADBC service written in Python: three queries, no SQL engine.

``SELECT 'Hello, world!' AS message``
    A single-row result.

``SELECT * FROM numbers(n)``
    Rows 0..n-1 from a **generator**. Simple, and fine whenever the server keeps
    the cursor in memory; it can also hold resources such as a database cursor.

``SELECT * FROM running_total(n)``
    Rows 0..n-1 with a running sum, from a serializable **ResultProducer**. Over
    HTTP the producer's fields travel in the encrypted continuation token after
    every batch, so the server keeps no per-result iterator, and a retried fetch
    recomputes its batch from the token.
"""

import re
from collections.abc import Iterator
from dataclasses import dataclass

import pyarrow as pa
from grainlift import AdbcError, Connection, QueryResult, ResultProducer, Worker
from grainlift.cli import run

MAX_ROWS = 100_000
BATCH_ROWS = 1024

HELLO_SCHEMA = pa.schema([("message", pa.string())])
NUMBERS_SCHEMA = pa.schema([("number", pa.int64())])
RUNNING_TOTAL_SCHEMA = pa.schema([("number", pa.int64()), ("total", pa.int64())])

_TABLE_FUNCTION = re.compile(r"select \* from (numbers|running_total)\(([0-9]{1,6})\)")


def numbers(count: int) -> Iterator[pa.RecordBatch]:
    """Generate 0..count-1 in batches of at most BATCH_ROWS rows.

    Args:
        count: Number of rows to generate.

    Yields:
        One record batch per BATCH_ROWS rows.
    """
    for start in range(0, count, BATCH_ROWS):
        yield pa.RecordBatch.from_pydict(
            {"number": range(start, min(start + BATCH_ROWS, count))}, schema=NUMBERS_SCHEMA
        )


@dataclass
class RunningTotal(ResultProducer):
    """Resumable state for ``running_total(n)``; each field survives between batches.

    Attributes:
        count: Number of rows to produce.
        position: Next number to emit.
        total: Sum of every number emitted so far.
    """

    count: int
    position: int = 0
    total: int = 0

    def produce(self) -> pa.RecordBatch | None:
        """Emit the next batch and advance the state, or return None when done.

        Returns:
            The next batch, or None at the end of the result.
        """
        if self.position >= self.count:
            return None
        batch_numbers = range(self.position, min(self.position + BATCH_ROWS, self.count))
        totals = []
        for number in batch_numbers:
            self.total += number
            totals.append(self.total)
        self.position = batch_numbers.stop
        return pa.RecordBatch.from_pydict({"number": batch_numbers, "total": totals}, schema=RUNNING_TOTAL_SCHEMA)


def _unsupported() -> AdbcError:
    return AdbcError(
        "Supported queries: SELECT 'Hello, world!' AS message; "
        f"SELECT * FROM numbers(n) or running_total(n), where 0 <= n <= {MAX_ROWS}",
        "invalid_arguments",
        sqlstate="42000",
    )


class HelloConnection(Connection):
    """Answer the three demo queries; everything else is an ADBC INVALID_ARGUMENT error."""

    def execute(self, sql: str) -> QueryResult:
        """Run a supported query.

        Args:
            sql: The query text.

        Returns:
            The result schema and its batches.
        """
        query = sql.strip().removesuffix(";").strip().lower()
        if query == "select 'hello, world!' as message":
            return QueryResult(HELLO_SCHEMA, iter([pa.record_batch([["Hello, world!"]], schema=HELLO_SCHEMA)]))
        match = _TABLE_FUNCTION.fullmatch(query)
        if match is None or int(match[2]) > MAX_ROWS:
            raise _unsupported()
        count = int(match[2])
        if match[1] == "numbers":
            return QueryResult(NUMBERS_SCHEMA, numbers(count))
        return QueryResult.from_producer(RUNNING_TOTAL_SCHEMA, RunningTotal(count))

    def execute_schema(self, sql: str) -> pa.Schema:
        """Return a query's result schema without producing rows.

        Args:
            sql: The query text.

        Returns:
            The Arrow schema the query would produce.
        """
        return self.execute(sql).schema


class HelloWorker(Worker):
    """Serve the ``hello`` target; each authenticated client gets its own connection."""

    target = "hello"

    def connect(self, principal: str) -> HelloConnection:
        """Open a connection for an authenticated principal.

        Args:
            principal: The authenticated principal name.

        Returns:
            A new hello-world connection.
        """
        return HelloConnection()


def main() -> None:
    """Serve HelloWorker on loopback; run with ``--help`` for hosting options."""
    run("grainlift_hello_world:HelloWorker", description="Grainlift hello-world ADBC service")
