# Copyright (c) 2026 Query Farm LLC
# SPDX-License-Identifier: Apache-2.0
"""Real C-ABI coverage; no Python VGI client substitutes for the native driver."""

import os
import socket
import subprocess
import sys
import threading
import time
from collections.abc import Iterator
from pathlib import Path
from wsgiref.simple_server import WSGIRequestHandler, make_server

import adbc_driver_manager as manager
import adbc_driver_manager.dbapi as adbc
import pytest
from grainlift import AdbcError, QueryResult, Service

from grainlift_hello_world import HelloConnection, HelloWorker

pytestmark = pytest.mark.skipif(not os.environ.get("GRAINLIFT_DRIVER"), reason="Set GRAINLIFT_DRIVER")


class QuietHandler(WSGIRequestHandler):
    """WSGI request handler that suppresses access logging."""

    def log_message(self, format: str, *args: object) -> None:
        """Discard the log line."""
        pass


@pytest.fixture
def endpoint() -> Iterator[tuple[str, Service]]:
    """Serve the hello worker over HTTP on an ephemeral port.

    Yields:
        The endpoint URL and the backing service.
    """
    with Service(HelloWorker()) as service:
        app = service.app(tokens={"test-token": "alice", "other-token": "bob"})
        server = make_server("127.0.0.1", 0, app, handler_class=QuietHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            yield f"http://127.0.0.1:{server.server_port}", service
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)


def connect(endpoint: str, token: str = "test-token") -> adbc.Connection:
    """Connect to an endpoint through the native Grainlift ADBC driver.

    Args:
        endpoint: The service URL.
        token: The bearer token to authenticate with.

    Returns:
        An autocommit DB-API connection.
    """
    return adbc.connect(
        driver=Path(os.environ["GRAINLIFT_DRIVER"]).resolve(strict=True),
        entrypoint="AdbcDriverGrainliftInit",
        db_kwargs={
            "grainlift.uri": endpoint,
            "grainlift.target": "hello",
            "grainlift.auth.bearer_token": token,
        },
        autocommit=True,
    )


def test_real_adbc_queries_schema_errors_and_cleanup(endpoint: tuple[str, Service]) -> None:
    """Queries, schema inference, errors and cursor cleanup work through real ADBC."""
    url, service = endpoint
    with connect(url) as connection:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 'Hello, world!' AS message")
            assert cursor.fetch_arrow_table().to_pydict() == {"message": ["Hello, world!"]}
            cursor.execute("SELECT * FROM numbers(2500)")
            batches = list(cursor.fetch_record_batch())
            assert [batch.num_rows for batch in batches] == [1024, 1024, 452]
            assert batches[-1].column(0)[-1].as_py() == 2499
            cursor.execute("SELECT * FROM running_total(2500)")
            batches = list(cursor.fetch_record_batch())
            assert [batch.num_rows for batch in batches] == [1024, 1024, 452]
            assert batches[-1].column("total")[-1].as_py() == 2499 * 2500 // 2
            assert all(
                result.producer is not None
                for session in service._sessions.values()
                for result in session.results.values()
            )
            cursor.execute("SELECT * FROM numbers(0)")
            empty = cursor.fetch_arrow_table()
            assert empty.num_rows == 0
            assert empty.schema.names == ["number"]
            assert cursor.adbc_execute_schema("SELECT * FROM numbers(0)") == empty.schema
            with pytest.raises(manager.ProgrammingError) as exc:
                cursor.execute("unsupported")
            assert exc.value.sqlstate == "42000"
            cursor.execute("SELECT * FROM numbers(100000)")
            reader = cursor.fetch_record_batch()
            assert reader.read_next_batch().num_rows == 1024
            reader.close()
        assert all(not session.results for session in service._sessions.values())
    assert not service._sessions


def test_authentication_required(endpoint: tuple[str, Service]) -> None:
    """A wrong bearer token is rejected before a session is opened."""
    url, service = endpoint
    with pytest.raises(manager.Error):
        connect(url, "wrong-token")
    assert not service._sessions


def test_granian_cli_through_native_adbc() -> None:
    """Run the public CLI and its child-side factory through real ADBC."""
    with socket.socket() as reservation:
        reservation.bind(("127.0.0.1", 0))
        port = reservation.getsockname()[1]
    process = subprocess.Popen(
        [
            sys.executable,
            "-c",
            "from grainlift_hello_world import main; main()",
            "--host",
            "granian",
            "--port",
            str(port),
        ],
        env={**os.environ, "GRAINLIFT_TOKEN": "test-token"},
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    try:
        deadline = time.monotonic() + 15
        while True:
            assert process.poll() is None
            try:
                with socket.create_connection(("127.0.0.1", port), timeout=0.2):
                    break
            except OSError:
                assert time.monotonic() < deadline
                time.sleep(0.05)
        with connect(f"http://127.0.0.1:{port}") as connection, connection.cursor() as cursor:
            cursor.execute("SELECT 'Hello, world!' AS message")
            assert cursor.fetch_arrow_table().to_pydict() == {"message": ["Hello, world!"]}
            cursor.execute("SELECT * FROM numbers(2500)")
            assert [batch.num_rows for batch in cursor.fetch_record_batch()] == [1024, 1024, 452]
        process.terminate()
        assert process.wait(timeout=20) == 0
    finally:
        if process.poll() is None:
            process.terminate()
        try:
            process.communicate(timeout=20)
        except subprocess.TimeoutExpired:
            process.kill()
            process.communicate(timeout=5)


@pytest.mark.parametrize("details", [{}, {"binary": b"\x00\xff"}])
def test_structured_adbc_error(
    endpoint: tuple[str, Service], monkeypatch: pytest.MonkeyPatch, details: dict[str, bytes]
) -> None:
    """Structured AdbcError fields reach the ADBC client."""
    url, _ = endpoint

    def fail(self: HelloConnection, sql: str) -> QueryResult:
        raise AdbcError(
            "Invalid data",
            "invalid_data",
            sqlstate="22000",
            vendor_code=42,
            details=details,
        )

    monkeypatch.setattr(HelloConnection, "execute", fail)
    with connect(url) as connection, connection.cursor() as cursor:
        with pytest.raises(manager.DataError) as exc:
            cursor.execute("SELECT 'Hello, world!' AS message")
        assert exc.value.sqlstate == "22000"
        # The current Rust ADBC 1.1 FFI exporter uses the vendor-code slot for
        # its private-data sentinel. The wire still carries 42; see toolkit README.
        assert exc.value.vendor_code is None
        # adbc_driver_manager's stub types detail keys as str, but the runtime returns bytes.
        assert exc.value.details == [  # type: ignore[comparison-overlap]
            (key.encode(), data) for key, data in details.items()
        ]
