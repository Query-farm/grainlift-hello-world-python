# Copyright (c) 2026 Query Farm LLC
# SPDX-License-Identifier: Apache-2.0
"""An ADBC service written in Python, with no downstream driver or SQL engine."""

import argparse
import os
import re
import signal
import threading

import pyarrow as pa
from grainlift import (
    AdbcError,
    Connection,
    QueryResult,
    Service,
    TcpServer,
    TLSConfig,
    Worker,
    serve,
    serve_granian,
)

HELLO_SCHEMA = pa.schema([("message", pa.string())])
NUMBERS_SCHEMA = pa.schema([("number", pa.int64())])
MAX_NUMBERS = 100_000
BATCH_ROWS = 1024


class HelloConnection(Connection):
    def _query(self, sql):
        normalized = sql.strip().removesuffix(";").strip().lower()
        if normalized == "select 'hello, world!' as message":
            return HELLO_SCHEMA, None
        match = re.fullmatch(r"select \* from numbers\(([0-9]{1,6})\)", normalized)
        if match and int(match[1]) <= MAX_NUMBERS:
            return NUMBERS_SCHEMA, int(match[1])
        raise AdbcError(
            "Supported queries: SELECT 'Hello, world!' AS message; "
            "SELECT * FROM numbers(n), where 0 <= n <= 100000",
            "invalid_arguments",
            sqlstate="42000",
        )

    def execute_schema(self, sql):
        return self._query(sql)[0]

    def execute(self, sql):
        schema, count = self._query(sql)

        def batches():
            if count is None:
                yield pa.RecordBatch.from_pydict({"message": ["Hello, world!"]}, schema=schema)
            else:
                for start in range(0, count, BATCH_ROWS):
                    yield pa.RecordBatch.from_pydict(
                        {"number": range(start, min(start + BATCH_ROWS, count))}, schema=schema
                    )

        return QueryResult(schema, batches())


class HelloWorker(Worker):
    target = "hello"

    def connect(self, principal):
        return HelloConnection()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8080)
    parser.add_argument("--host", choices=("waitress", "granian", "mtls"), default="waitress")
    parser.add_argument("--tls-cert")
    parser.add_argument("--tls-key")
    parser.add_argument("--client-ca")
    parser.add_argument("--client-uri")
    args = parser.parse_args()
    if args.host == "mtls":
        if not all((args.tls_cert, args.tls_key, args.client_ca, args.client_uri)):
            parser.error("mTLS requires --tls-cert, --tls-key, --client-ca and --client-uri")
        stop = threading.Event()
        signal.signal(signal.SIGTERM, lambda *_: stop.set())
        signal.signal(signal.SIGINT, lambda *_: stop.set())
        tls = TLSConfig(args.tls_cert, args.tls_key, args.client_ca, {args.client_uri: "developer"})
        with TcpServer(Service(HelloWorker()), port=args.port, tls=tls):
            stop.wait()
        return
    token = os.environ.get("GRAINLIFT_TOKEN")
    if not token:
        parser.error("Set GRAINLIFT_TOKEN to a development bearer token")
    if args.host == "granian":
        serve_granian(
            "grainlift_hello_world:HelloWorker", tokens={token: "developer"}, port=args.port
        )
    else:
        serve(HelloWorker(), token=token, port=args.port)
