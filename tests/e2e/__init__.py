"""M4 end-to-end tests: coordinator API + party agent UI over ASGI transports.

Synthetic data only. These exercise the real services and the real worker; they do not
drive a real browser (see evidence/m4/M4_REPORT.md for what that means).
"""
from __future__ import annotations
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for package in ("services/common", "services/party-agent", "services/coordinator"):
    path = str(ROOT / package)
    if path not in sys.path:
        sys.path.insert(0, path)

WORKER_BINARY = Path(os.environ.get("PROTECMED_WORKER",
                                    ROOT / "build/worker/protecmed-worker"))
OPENFHE_LIB = Path(os.environ.get("PROTECMED_OPENFHE_LIB", ROOT / ".local/openfhe/lib"))
WORKER_AVAILABLE = WORKER_BINARY.is_file() and os.access(WORKER_BINARY, os.X_OK)
SKIP_REASON = f"worker binary not built at {WORKER_BINARY}"
