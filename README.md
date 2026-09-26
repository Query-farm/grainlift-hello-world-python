# grainlift-hello-world-python

A Python-authored ADBC service using grainlift-python and VGI-RPC.
The application uses the normal Grainlift native ADBC driver. The server uses
neither a downstream ADBC driver nor a SQL engine.

Requires Python 3.13+, uv, and Rust 1.97+ to build the native driver. The lockfile
pins a public Git revision of the [toolkit](https://github.com/Query-farm/grainlift-python).
The toolkit uses the published VGI-RPC 0.47.1 runtime; no modified VGI runtime is
required. SDK package-index publication remains a separate release step.

Clone this repository, then build the ordinary Grainlift client driver:

    git clone https://github.com/Query-farm/grainlift.git ../grainlift
    cd ../grainlift
    cargo build --locked -p adbc-driver-grainlift
    cd ../grainlift-hello-world-python
    uv sync --locked

Start the worker:

    export GRAINLIFT_TOKEN=local-development-token
    uv run grainlift-hello-world --host granian

In another terminal, from this directory:

    export GRAINLIFT_TOKEN=local-development-token
    export GRAINLIFT_DRIVER=../grainlift/target/debug/libadbc_driver_grainlift.dylib
    uv run grainlift-hello-client

On Linux use libadbc_driver_grainlift.so; on Windows use adbc_driver_grainlift.dll.
GRAINLIFT_ENDPOINT defaults to http://127.0.0.1:8080; --port changes the worker port.
`--host waitress` retains the original development host and remains the CLI
default. Granian runs one serving process and drains on SIGTERM/SIGINT.

For verified TCP/mTLS, supply your server chain, key, client CA and authorized
client certificate URI SAN:

    uv run grainlift-hello-world --host mtls --port 8443 \
      --tls-cert server.pem --tls-key server-key.pem \
      --client-ca clients-ca.pem --client-uri spiffe://example.org/client

The native client then uses:

    export GRAINLIFT_ENDPOINT=tls+tcp://127.0.0.1:8443
    export GRAINLIFT_TLS_CA=server-ca.pem
    export GRAINLIFT_TLS_CERT=client.pem
    export GRAINLIFT_TLS_KEY=client-key.pem
    export GRAINLIFT_TLS_SERVER_NAME=localhost
    uv run grainlift-hello-client

Use the actual DNS name in your server certificate for `GRAINLIFT_TLS_SERVER_NAME`.
The mTLS example stays on loopback and requires no bearer token. SIGTERM/SIGINT
drains its listener and closes the owned service. Configure remote exposure and
resource limits in an application using the SDK's hosting APIs.

Expected output:

    {'message': ['Hello, world!']}
    numbers(2500): [1024, 1024, 452] rows per Arrow batch
    Empty result: 0 rows, schema: number: int64

The demo recognizes exactly two query forms (case-insensitive, optional trailing
semicolon): SELECT 'Hello, world!' AS message and SELECT * FROM numbers(n).
Numbers range from zero through n-1; n must be between 0 and 100000.
Other SQL produces an ADBC INVALID_ARGUMENT error with SQLSTATE 42000.
This deliberately demonstrates the statement interface without pretending to
implement a general SQL parser.

See src/grainlift_hello_world/__init__.py for the worker and client.py for the
ordinary ADBC application. Results are generated lazily in batches of at most
1024 rows. Authentication, handles, continuation tokens and cleanup live in
the toolkit.

Run checks:

    uv run --no-sync ruff check src tests
    uv run --no-sync ruff format --check src tests
    uv run --no-sync pytest
    GRAINLIFT_DRIVER=../grainlift/target/debug/libadbc_driver_grainlift.dylib uv run --no-sync pytest

Native integration tests skip when GRAINLIFT_DRIVER is unset.
CI builds a reviewed native-driver revision and sets this variable on
Linux/macOS with Python 3.13/3.14, exercising the installed example wheel and all
native tests. Consult Actions results for the revision being deployed; workflow
configuration alone does not establish a passing matrix.
This is a development example. The SDK documents its supported hosts, lifecycle
limits and security contract in [HOSTING.md](https://github.com/Query-farm/grainlift-python/blob/main/docs/HOSTING.md).
