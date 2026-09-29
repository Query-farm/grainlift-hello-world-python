# Copyright (c) 2026 Query Farm LLC
# SPDX-License-Identifier: Apache-2.0
"""Run the shipped SQL example with the Haybarn CLI and its adbc_scanner extension."""

import json
import os
import shutil
import subprocess
import sys
import threading
from collections.abc import Iterator
from pathlib import Path
from typing import Any
from wsgiref.simple_server import WSGIRequestHandler, make_server

import pytest
from grainlift import Service

from grainlift_hello_world import HelloWorker

EXAMPLE = Path(__file__).parent.parent / "examples" / "query.sql"
HAYBARN = shutil.which("haybarn", path=str(Path(sys.executable).parent)) or shutil.which("haybarn")

pytestmark = [
    pytest.mark.skipif(not os.environ.get("GRAINLIFT_DRIVER"), reason="Set GRAINLIFT_DRIVER"),
    pytest.mark.skipif(HAYBARN is None, reason="Install haybarn-cli"),
]


class QuietHandler(WSGIRequestHandler):
    """WSGI request handler that suppresses access logging."""

    def log_message(self, format: str, *args: object) -> None:
        """Discard the log line."""


@pytest.fixture
def anonymous_url() -> Iterator[str]:
    """Serve the hello worker anonymously, as ``grainlift-hello-world`` does by default.

    Yields:
        The endpoint URL.
    """
    with Service(HelloWorker()) as service:
        server = make_server("127.0.0.1", 0, service.app(anonymous_principal="anonymous"), handler_class=QuietHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            yield f"http://127.0.0.1:{server.server_port}"
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)


def results(output: str) -> list[list[dict[str, Any]]]:
    """Split the CLI's JSON output into one row list per result set."""
    decoder, position, parsed = json.JSONDecoder(), 0, []
    while position < len(output):
        if output[position].isspace():
            position += 1
            continue
        value, position = decoder.raw_decode(output, position)
        parsed.append(value)
    return parsed


def test_sql_example_in_haybarn(anonymous_url: str) -> None:
    """``haybarn < examples/query.sql`` returns the documented results through adbc_scanner."""
    assert HAYBARN is not None
    completed = subprocess.run(
        [HAYBARN, "-json"],
        input=EXAMPLE.read_text().replace("http://127.0.0.1:8080", anonymous_url),
        env={**os.environ, "GRAINLIFT_DRIVER": str(Path(os.environ["GRAINLIFT_DRIVER"]).resolve(strict=True))},
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    hello, numbers, running_total, disconnected = results(completed.stdout)
    assert hello == [{"message": "Hello, world!"}]
    assert numbers == [{"numbers": 100000, "total": "4999950000"}]  # HUGEINT sums are emitted as strings.
    assert running_total == [
        {"number": 2499, "total": 3123750},
        {"number": 2498, "total": 3121251},
        {"number": 2497, "total": 3118753},
    ]
    assert list(disconnected[0].values()) == [True]
