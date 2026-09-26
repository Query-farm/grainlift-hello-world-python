# grainlift-hello-world-python

A Python-authored ADBC service using grainlift-python and VGI-RPC.
The application uses the normal Grainlift native ADBC driver. The server uses
neither a downstream ADBC driver nor a SQL engine.

Requires Python 3.13+, uv, and Rust 1.97+ to build the native driver. The lockfile
pins public Git revisions of the [toolkit](https://github.com/Query-farm/grainlift-python)
and [VGI-RPC](https://github.com/Query-farm/vgi-rpc-python), including the required
Arrow schema and structured-error support. Their package-index publication is a
separate release step; do not substitute registry VGI-RPC 0.47.1 for this pin.

Clone this repository, then build the ordinary Grainlift client driver:

    git clone https://github.com/Query-farm/grainlift.git ../grainlift
    cd ../grainlift
    cargo build --locked -p adbc-driver-grainlift
    cd ../grainlift-hello-world-python
    uv sync --locked

Start the worker:

    export GRAINLIFT_TOKEN=local-development-token
    uv run grainlift-hello-world

In another terminal, from this directory:

    export GRAINLIFT_TOKEN=local-development-token
    export GRAINLIFT_DRIVER=../grainlift/target/debug/libadbc_driver_grainlift.dylib
    uv run grainlift-hello-client

On Linux use libadbc_driver_grainlift.so; on Windows use adbc_driver_grainlift.dll.
GRAINLIFT_ENDPOINT defaults to http://127.0.0.1:8080; --port changes the worker port.

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
Only authenticated loopback HTTP is validated. This is a development example,
with the limitations and resource/security contract in the toolkit README.
