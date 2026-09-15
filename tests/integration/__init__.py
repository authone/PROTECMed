"""M2 integration tests: the real OpenFHE worker in separate processes.

These are NOT unit tests with a fake worker. If the worker binary is missing they are
skipped, never silently passed. Build it with:

    cmake -S cpp/fhe-core -B build/worker -DCMAKE_PREFIX_PATH="$PWD/.local/openfhe"
    cmake --build build/worker --parallel 2
"""
from __future__ import annotations
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for package in ("services/common", "services/party-agent"):
    path = str(ROOT / package)
    if path not in sys.path:
        sys.path.insert(0, path)

WORKER_BINARY = Path(os.environ.get("PROTECMED_WORKER",
                                    ROOT / "build/worker/protecmed-worker"))
OPENFHE_LIB = Path(os.environ.get("PROTECMED_OPENFHE_LIB", ROOT / ".local/openfhe/lib"))
WORKER_AVAILABLE = WORKER_BINARY.is_file() and os.access(WORKER_BINARY, os.X_OK)
SKIP_REASON = f"worker binary not built at {WORKER_BINARY}"
