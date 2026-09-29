# Copyright (c) 2026 Query Farm LLC
# SPDX-License-Identifier: Apache-2.0
"""The hello-world worker: three queries, no SQL engine.

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

from __future__ import annotations

import re
from collections.abc import Iterator
from dataclasses import dataclass

import pyarrow as pa
from grainlift import AdbcError, Connection, QueryResult, ResultProducer, Statement, Worker

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


@dataclass(frozen=True)
class Query:
    """A recognized query.

    Attributes:
        function: ``hello``, ``numbers`` or ``running_total``.
        count: Requested row count for the table functions.
    """

    function: str
    count: int = 0

    @classmethod
    def parse(cls, sql: str) -> Query:
        """Recognize one of the supported queries (case-insensitive, optional trailing semicolon).

        Args:
            sql: The query text.

        Returns:
            The recognized query.
        """
        text = sql.strip().removesuffix(";").strip().lower()
        if text == "select 'hello, world!' as message":
            return cls("hello")
        match = _TABLE_FUNCTION.fullmatch(text)
        if match is None or int(match[2]) > MAX_ROWS:
            raise AdbcError(
                "Supported queries: SELECT 'Hello, world!' AS message; "
                f"SELECT * FROM numbers(n) or running_total(n), where 0 <= n <= {MAX_ROWS}",
                "invalid_arguments",
                sqlstate="42000",
            )
        return cls(match[1], int(match[2]))

    @property
    def schema(self) -> pa.Schema:
        """The Arrow schema of this query's result."""
        return {"hello": HELLO_SCHEMA, "numbers": NUMBERS_SCHEMA}.get(self.function, RUNNING_TOTAL_SCHEMA)

    def run(self) -> QueryResult:
        """Start producing this query's result.

        Returns:
            The result schema and its lazily produced batches.
        """
        if self.function == "hello":
            return QueryResult(HELLO_SCHEMA, iter([pa.record_batch([["Hello, world!"]], schema=HELLO_SCHEMA)]))
        if self.function == "numbers":
            return QueryResult(NUMBERS_SCHEMA, numbers(self.count))
        return QueryResult.from_producer(RUNNING_TOTAL_SCHEMA, RunningTotal(self.count))


class HelloStatement(Statement):
    """One ADBC statement: set a query, optionally prepare it, then execute it."""

    def __init__(self) -> None:
        """Start without a query."""
        self.sql: str | None = None

    def set_sql_query(self, sql: str) -> None:
        """Store the query text; it is validated when prepared or executed.

        Args:
            sql: The query text.
        """
        self.sql = sql

    def _query(self) -> Query:
        if self.sql is None:
            raise AdbcError("Set a query before executing the statement", "invalid_state")
        return Query.parse(self.sql)

    def prepare(self) -> None:
        """Validate the query; clients such as DuckDB's adbc_scanner prepare before executing."""
        self._query()

    def get_parameter_schema(self) -> pa.Schema:
        """Report that the supported queries take no parameters.

        Returns:
            An empty schema.
        """
        self._query()
        return pa.schema([])

    def execute_schema(self) -> pa.Schema:
        """Return the result schema without producing rows.

        Returns:
            The Arrow schema the query produces.
        """
        return self._query().schema

    def execute(self) -> QueryResult:
        """Execute the query.

        Returns:
            The result schema and its batches.
        """
        return self._query().run()


class HelloConnection(Connection):
    """A client connection; each statement is independent."""

    def new_statement(self) -> HelloStatement:
        """Create a statement.

        Returns:
            A new statement with no query set.
        """
        return HelloStatement()


class HelloWorker(Worker):
    """Serve the ``hello`` target; each client connection gets its own HelloConnection."""

    target = "hello"

    def connect(self, principal: str) -> HelloConnection:
        """Open a connection for an authenticated (or anonymous) principal.

        Args:
            principal: The client's principal name.

        Returns:
            A new hello-world connection.
        """
        return HelloConnection()
