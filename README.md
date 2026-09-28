# grainlift-hello-world-python

A complete ADBC service in about 100 lines of Python, built with
[grainlift-python](https://github.com/Query-farm/grainlift-python). Any ADBC
application connects to it through the native Grainlift driver; the service
itself needs no database, SQL engine or downstream driver.

## Quickstart

Requires Python 3.13+, [uv](https://docs.astral.sh/uv/) and Rust 1.97+ (to
build the native client driver once).

    git clone https://github.com/Query-farm/grainlift.git ../grainlift
    (cd ../grainlift && cargo build --locked -p adbc-driver-grainlift)
    uv sync --locked

Start the service:

    uv run grainlift-hello-world

It prints a generated bearer token (set `GRAINLIFT_TOKEN` yourself to choose
one). In a second terminal, export that token and run the ADBC client:

    export GRAINLIFT_TOKEN=<printed token>
    export GRAINLIFT_DRIVER=../grainlift/target/debug/libadbc_driver_grainlift.dylib  # .so on Linux
    uv run grainlift-hello-client

Expected output:

    {'message': ['Hello, world!']}
    numbers(2500): [1024, 1024, 452] rows per Arrow batch
    running_total(2500): last row {'number': 2499, 'total': 3123750}
    Empty result: 0 rows, schema: number: int64

## What's in the service

All of it is in [`src/grainlift_hello_world/__init__.py`](src/grainlift_hello_world/__init__.py):

| Query | Result | Demonstrates |
| --- | --- | --- |
| `SELECT 'Hello, world!' AS message` | one row | the smallest possible result |
| `SELECT * FROM numbers(n)` | 0..n-1 | a **generator** of Arrow batches |
| `SELECT * FROM running_total(n)` | 0..n-1 with a running sum | a serializable **`ResultProducer`** |

`n` ranges from 0 to 100000. Anything else is an ADBC `INVALID_ARGUMENT` error
with SQLSTATE 42000. The example matches these queries exactly rather than
pretending to parse SQL.

### Generators vs. producers

Both styles stream lazily in batches of at most 1024 rows, and you can mix them
freely within one service.

- **Generator** (`numbers`): return `QueryResult(schema, iterator)`. It's the
  simplest option, and it can hold resources such as an open database cursor.
  The iterator lives in server memory until the client finishes or releases the
  result.
- **Producer** (`running_total`): subclass `ResultProducer` as a dataclass whose
  fields are the entire resumable state, implement `produce()`, and return
  `QueryResult.from_producer(schema, state)`. Over HTTP the state is serialized
  into the encrypted continuation token after each batch. The server keeps no
  iterator or replay batch between fetches, and a retried fetch recomputes its
  batch from the token. This is the same approach VGI-RPC streams use.

Pick a producer when the state is small and serializable, such as offsets,
keyset cursors or counters. Pick a generator when it isn't.

## Hosting options

`uv run grainlift-hello-world --help` lists them. The same command-line host is
available for any worker as `grainlift serve module:Factory`.

- `--host waitress` (default): loopback HTTP for development.
- `--host granian`: supervised loopback HTTP that drains on SIGTERM/SIGINT.
- `--host mtls`: verified TCP/mTLS; no bearer token needed.
- `--port`: listening port (default 8080). Point the client at a different
  port with `GRAINLIFT_ENDPOINT`.

For mTLS, supply the server chain, key, client CA and authorized client URI SAN:

    uv run grainlift-hello-world --host mtls --port 8443 \
      --tls-cert server.pem --tls-key server-key.pem \
      --client-ca clients-ca.pem --client-uri spiffe://example.org/client

    export GRAINLIFT_ENDPOINT=tls+tcp://127.0.0.1:8443
    export GRAINLIFT_TLS_CA=server-ca.pem GRAINLIFT_TLS_CERT=client.pem GRAINLIFT_TLS_KEY=client-key.pem
    export GRAINLIFT_TLS_SERVER_NAME=localhost   # the DNS name in the server certificate
    uv run grainlift-hello-client

These hosts are for development and bind to loopback. For production
deployment, limits and the security contract, see the SDK's
[HOSTING.md](https://github.com/Query-farm/grainlift-python/blob/main/docs/HOSTING.md).

## Development

    uv run --no-sync ruff check src tests && uv run --no-sync ruff format --check src tests
    uv run --no-sync mypy src tests
    uvx pydoclint --config pyproject.toml src/ tests/
    GRAINLIFT_DRIVER=../grainlift/target/debug/libadbc_driver_grainlift.dylib uv run --no-sync pytest

Native integration tests skip when `GRAINLIFT_DRIVER` is unset. CI builds a
pinned native-driver revision and runs everything on Linux and macOS with
Python 3.13 and 3.14. See [VALIDATION.md](VALIDATION.md) for a recorded local run.
