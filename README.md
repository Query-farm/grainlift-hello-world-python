# grainlift-hello-world

A complete ADBC service in about 200 lines of Python, built with
the [Grainlift SDK](https://pypi.org/project/grainlift/) (`pip install grainlift`). Any ADBC
application connects to it through the native Grainlift driver; the service
itself needs no database, SQL engine or downstream driver.

## Quickstart

Requires Python 3.13+, [uv](https://docs.astral.sh/uv/) and Rust 1.97+ (to
build the native Grainlift ADBC driver once).

    git clone https://github.com/Query-farm/grainlift.git ../grainlift
    (cd ../grainlift && cargo build --locked -p adbc-driver-grainlift)
    uv sync --locked

Start the service (`python -m grainlift_hello_world` works too):

    uv run grainlift-hello-world

No credentials are needed. The service is read-only, so it accepts anonymous
clients (see [Authentication](#authentication)).

### Query it from SQL

[Haybarn](https://github.com/Query-farm-haybarn/haybarn), Query.Farm's DuckDB
distribution, loads the Grainlift driver through the `adbc_scanner` extension.
In a second terminal, run [`examples/query.sql`](examples/query.sql):

    export GRAINLIFT_DRIVER=$PWD/../grainlift/target/debug/libadbc_driver_grainlift.dylib  # .so on Linux
    uvx haybarn-cli < examples/query.sql

The same script runs unchanged in the DuckDB CLI. It prints:

    ┌───────────────┐
    │    message    │
    │    varchar    │
    ├───────────────┤
    │ Hello, world! │
    └───────────────┘
    ┌─────────┬────────────┐
    │ numbers │   total    │
    │  int64  │   int128   │
    ├─────────┼────────────┤
    │  100000 │ 4999950000 │
    └─────────┴────────────┘
    ...

`adbc_scan` sends its quoted SQL to this service. The rows come back as an
ordinary relation that you can join, aggregate or export locally.

### Query it from Python

[`examples/python_client.py`](examples/python_client.py) uses the standard ADBC
driver manager:

    uv run examples/python_client.py

## What's in the package

| Module | Contents |
| --- | --- |
| [`grainlift_hello_world.worker`](src/grainlift_hello_world/worker.py) | The service: `HelloWorker` → `HelloConnection` → `HelloStatement`, plus the two result styles below |
| [`grainlift_hello_world.__main__`](src/grainlift_hello_world/__main__.py) | The `grainlift-hello-world` command |

The service answers three queries:

| Query | Result | Demonstrates |
| --- | --- | --- |
| `SELECT 'Hello, world!' AS message` | one row | the smallest possible result |
| `SELECT * FROM numbers(n)` | 0..n-1 | a **generator** of Arrow batches |
| `SELECT * FROM running_total(n)` | 0..n-1 with a running sum | a serializable **`ResultProducer`** |

`n` ranges from 0 to 100000. Anything else is an ADBC `INVALID_ARGUMENT` error
with SQLSTATE 42000. The example matches these queries exactly rather than
pretending to parse SQL.

`HelloStatement` implements the ADBC statement lifecycle: set the SQL, then
`prepare`, `execute_schema` and `execute`. Preparation matters because clients
such as `adbc_scanner` prepare every query before running it.

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

## Authentication

Anonymous access is opt-in in the Grainlift SDK. This example enables it because
it only serves public, read-only data: its command calls
`grainlift.cli.run(..., auth="anonymous")`. Requests without credentials act as
the shared `anonymous` principal.

- Set `GRAINLIFT_TOKEN` on both sides to connect as an authenticated principal
  instead. A client that sends a wrong token is rejected, never downgraded to
  anonymous.
- Run `uv run grainlift-hello-world --auth token` to require a token. The server
  prints a generated token when `GRAINLIFT_TOKEN` is unset.

For a service that can write data or expose private data, keep the default
token authentication. In your own hosting code, anonymous access is
`Service.app(anonymous_principal="anonymous")`, optionally alongside `tokens=`.

## Hosting options

`uv run grainlift-hello-world --help` lists them. The same command-line host is
available for any worker as `grainlift serve module:Factory`.

- `--host waitress` (default): loopback HTTP for development.
- `--host granian`: supervised loopback HTTP that drains on SIGTERM/SIGINT.
- `--host mtls`: verified TCP/mTLS; client certificates identify callers.
- `--port`: listening port (default 8080). Point the client at a different
  port with `GRAINLIFT_ENDPOINT`.
- `--storage-endpoint`, `--storage-bucket` (with `--storage-region` and
  `--storage-prefix`): send large requests and results through an S3-compatible
  bucket (AWS S3, Cloudflare R2, MinIO) over HTTP. Clients upload requests over
  the request limit to presigned URLs and fetch large results from the bucket.
  Credentials come from `AWS_ACCESS_KEY_ID` and `AWS_SECRET_ACCESS_KEY`; install
  the SDK's storage extra (`uv run --with 'grainlift[storage]' grainlift-hello-world ...`).
  The hello-world results are small, so this matters for your own workers.

For mTLS, supply the server chain, key, client CA and authorized client URI SAN:

    uv run grainlift-hello-world --host mtls --port 8443 \
      --tls-cert server.pem --tls-key server-key.pem \
      --client-ca clients-ca.pem --client-uri spiffe://example.org/client

    export GRAINLIFT_ENDPOINT=tls+tcp://127.0.0.1:8443
    export GRAINLIFT_TLS_CA=server-ca.pem GRAINLIFT_TLS_CERT=client.pem GRAINLIFT_TLS_KEY=client-key.pem
    export GRAINLIFT_TLS_SERVER_NAME=localhost   # the DNS name in the server certificate
    uv run examples/python_client.py

These hosts are for development and bind to loopback. For production
deployment, limits and the security contract, see the SDK's
[HOSTING.md](https://github.com/Query-farm/grainlift-python/blob/main/docs/HOSTING.md).

## Development

    uv run --no-sync ruff check src tests examples && uv run --no-sync ruff format --check src tests examples
    uv run --no-sync mypy src tests examples
    uvx pydoclint --config pyproject.toml src/ tests/ examples/
    GRAINLIFT_DRIVER=../grainlift/target/debug/libadbc_driver_grainlift.dylib uv run --no-sync pytest

Native integration tests skip when `GRAINLIFT_DRIVER` is unset. They include
running `examples/query.sql` in the Haybarn CLI (a dev dependency), which
downloads the `adbc_scanner` extension on first use. CI builds a
pinned native-driver revision and runs everything on Linux and macOS with
Python 3.13 and 3.14. See [VALIDATION.md](VALIDATION.md) for a recorded local run.
