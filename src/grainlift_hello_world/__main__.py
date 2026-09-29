# Copyright (c) 2026 Query Farm LLC
# SPDX-License-Identifier: Apache-2.0
"""Command-line entry point: ``grainlift-hello-world`` or ``python -m grainlift_hello_world``."""

from grainlift.cli import run


def main() -> None:
    """Serve HelloWorker on loopback; run with ``--help`` for hosting options.

    The service is read-only, so it accepts anonymous clients by default; pass
    ``--auth token`` to require a bearer token.
    """
    run("grainlift_hello_world.worker:HelloWorker", description="Grainlift hello-world ADBC service", auth="anonymous")


if __name__ == "__main__":
    main()
