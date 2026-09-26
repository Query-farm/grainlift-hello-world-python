# Local validation

Validated on 2026-09-25 on macOS with Python 3.14.7, PyArrow 25.0.1,
adbc-driver-manager 1.12.0, and Rust 1.97.1. The native client was built
from Grainlift commit 98fe6f4 using cargo build -p adbc-driver-grainlift.
No Grainlift Rust source changes were needed.

The local VGI-RPC 0.47.1 checkout includes the unreleased explicit batch-schema
and raw error-message changes required by this prototype.

| Check | Result |
| --- | --- |
| grainlift-python: uv run pytest -q | 31 passed |
| Example: GRAINLIFT_DRIVER=../grainlift/target/debug/libadbc_driver_grainlift.dylib uv run pytest -q | 13 passed |
| VGI-RPC: new unary batch tests plus test_rpc.py, test_http.py, test_log.py | 695 passed |
| Ruff lint and formatting for both new projects and changed VGI-RPC Python files | Passed |
| Python compilation for both new projects | Passed |
| mypy and ty for the two changed VGI-RPC source modules | Passed |

The example CLI was also run against a live loopback HTTP worker through the
native ADBC driver. It returned the greeting, batches of 1024/1024/452 rows for
numbers(2500), and an empty numbers(0) result retaining its schema.

These are functional checks, not load/conformance results. No TCP, mTLS, Iroh,
multi-process deployment, hard timeout, or forced downstream cancellation claim
is made. See the toolkit README for limits and the existing native vendor-code
limitation.
