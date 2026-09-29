# Copyright (c) 2026 Query Farm LLC
# SPDX-License-Identifier: Apache-2.0
"""A minimal ADBC service written in Python with the Grainlift SDK.

Run it with ``grainlift-hello-world`` or ``python -m grainlift_hello_world``;
the worker itself lives in [`grainlift_hello_world.worker`][].
"""

from importlib.metadata import version

from .worker import HelloConnection, HelloStatement, HelloWorker, Query, RunningTotal, numbers

__version__ = version("grainlift-hello-world")
__all__ = ["HelloConnection", "HelloStatement", "HelloWorker", "Query", "RunningTotal", "numbers"]
