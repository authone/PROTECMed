"""Safe invocation of the isolated OpenFHE worker (blueprint 5.2, 5.3).

Every call is an argv array with ``shell=False``, a fixed worker binary, a per-job
directory created by the caller, a timeout and a minimal environment. Counts and secret
bytes are passed on stdin or through files, never in argv. The worker's stderr is
reduced to one symbolic token and is never forwarded verbatim to a browser.
"""
from __future__ import annotations
import json
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence

DEFAULT_TIMEOUT_SECONDS = 300
MAX_OUTPUT_BYTES = 64 * 1024

EXIT_TOKENS = {
    0: "OK",
    10: "INVALID_COMMAND",
    11: "PROFILE_MISMATCH",
    12: "SERIALIZATION_FAILURE",
    13: "SHAPE_MISMATCH",
    14: "CRYPTO_FAILURE",
    15: "ROLE_FAILURE",
    16: "RANGE_FAILURE",
    17: "AGGREGATE_MISMATCH",
    20: "FILESYSTEM_FAILURE",
    21: "RESOURCE_LIMIT",
}

COMMANDS = frozenset({
    "context-create", "keygen-first", "keygen-next", "encrypt-count", "add-counts",
    "verify-aggregate", "partial-decrypt", "fuse", "inspect-public",
})


class WorkerFailure(RuntimeError):
    """A worker call that did not exit 0. Carries the exit code and symbolic token."""

    def __init__(self, command: str, returncode: int, token: str) -> None:
        super().__init__(f"{command}: {token} (exit {returncode})")
        self.command = command
        self.returncode = returncode
        self.token = token
        self.category = EXIT_TOKENS.get(returncode, "UNKNOWN_EXIT")


@dataclass(frozen=True)
class WorkerResult:
    command: str
    returncode: int
    payload: dict[str, Any]
    token: str


class WorkerClient:
    def __init__(self, binary: Path, *, library_path: Path | None = None,
                 timeout: float = DEFAULT_TIMEOUT_SECONDS) -> None:
        self.binary = Path(binary).resolve()
        if not self.binary.is_file() or not os.access(self.binary, os.X_OK):
            raise FileNotFoundError(f"worker binary not executable: {self.binary}")
        self.library_path = Path(library_path).resolve() if library_path else None
        self.timeout = timeout

    def _environment(self) -> dict[str, str]:
        # Minimal environment: no inherited credentials, proxies or locale surprises.
        environment = {"PATH": "/usr/bin:/bin", "LC_ALL": "C"}
        if self.library_path:
            environment["LD_LIBRARY_PATH"] = str(self.library_path)
        return environment

    def run(self, command: str, arguments: Sequence[str] = (), *,
            stdin_bytes: bytes | None = None, check: bool = True) -> WorkerResult:
        if command not in COMMANDS:
            raise ValueError("UNKNOWN_WORKER_COMMAND")
        argv = [str(self.binary), command, *[str(a) for a in arguments]]
        try:
            completed = subprocess.run(  # noqa: S603 - fixed binary, argv array, no shell
                argv, input=stdin_bytes or b"", capture_output=True, shell=False,
                timeout=self.timeout, env=self._environment(), cwd="/")
        except subprocess.TimeoutExpired:
            raise WorkerFailure(command, 21, "WORKER_TIMEOUT") from None
        token = _first_token(completed.stderr)
        payload = _parse_payload(completed.stdout)
        if check and completed.returncode != 0:
            raise WorkerFailure(command, completed.returncode, token)
        return WorkerResult(command, completed.returncode, payload, token)


def _first_token(stderr: bytes) -> str:
    """Reduce the worker's stderr to one uppercase symbolic token."""
    text = stderr[:MAX_OUTPUT_BYTES].decode("ascii", "replace").strip().splitlines()
    if not text:
        return ""
    candidate = text[0].strip()
    allowed = set("ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_")
    if candidate and len(candidate) <= 64 and set(candidate) <= allowed:
        return candidate
    return "WORKER_FAILED"


def _parse_payload(stdout: bytes) -> dict[str, Any]:
    if not stdout.strip():
        return {}
    if len(stdout) > MAX_OUTPUT_BYTES:
        raise WorkerFailure("worker", 21, "WORKER_OUTPUT_TOO_LARGE")
    try:
        payload = json.loads(stdout.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        raise WorkerFailure("worker", 12, "WORKER_OUTPUT_NOT_JSON") from None
    if type(payload) is not dict:
        raise WorkerFailure("worker", 12, "WORKER_OUTPUT_NOT_JSON")
    return payload
