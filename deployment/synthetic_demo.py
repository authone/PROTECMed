"""D1 synthetic single-host demonstration launcher (blueprint 6.3).

Starts one coordinator and two or three party agents on loopback ports with invented
fixture data. Three containers or three processes on ONE laptop are a reproducible
simulation, not institutional separation: the host administrator can inspect all of them.

Never point this at a clinical workbook.
"""
from __future__ import annotations
import argparse
import os
import sys
import threading
from pathlib import Path

import httpx
import uvicorn

ROOT = Path(__file__).resolve().parents[1]
for package in ("services/common", "services/party-agent", "services/coordinator"):
    sys.path.insert(0, str(ROOT / package))

from protecmed_agent.app import create_app as create_agent_app          # noqa: E402
from protecmed_agent.poller import CoordinatorClient                    # noqa: E402
from protecmed_agent.runtime import AgentRuntime                        # noqa: E402
from protecmed_coordinator.app import create_app as create_coordinator_app  # noqa: E402
from protecmed_coordinator.runtime import CoordinatorService            # noqa: E402
from protecmed_coordinator.security import provision_agent              # noqa: E402
from protecmed_party.importer import read_canonical_csv                 # noqa: E402
from protecmed_party.splitter import split_rows, write_shards           # noqa: E402
from protecmed_protocol.identity import Roster                          # noqa: E402
from protecmed_worker import WorkerClient                               # noqa: E402

COORDINATOR_PORT = 8080
FIRST_PARTY_PORT = 8081


def serve(app, port: int) -> threading.Thread:
    # Loopback only. A published container port must also be 127.0.0.1-bound.
    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    return thread


def main() -> int:
    parser = argparse.ArgumentParser(description="Synthetic single-host demo. No clinical data.")
    parser.add_argument("--parties", type=int, choices=(2, 3), default=2)
    parser.add_argument("--state", type=Path, required=True,
                        help="scratch directory for databases, keys and artifacts")
    parser.add_argument("--worker", type=Path,
                        default=ROOT / "build/worker/protecmed-worker")
    parser.add_argument("--openfhe-lib", type=Path, default=ROOT / ".local/openfhe/lib")
    arguments = parser.parse_args()

    # Line-buffer stdout: an operator reading the banner must see every line as it is
    # printed, not a block-buffered fragment.
    sys.stdout.reconfigure(line_buffering=True)

    state = arguments.state.resolve()
    state.mkdir(parents=True, exist_ok=True)
    worker = WorkerClient(arguments.worker.resolve(),
                          library_path=arguments.openfhe_lib.resolve())

    service = CoordinatorService(database=state / "coordinator.db",
                                 storage=state / "coordinator", worker=worker)
    coordinator_app = create_coordinator_app(service)
    serve(coordinator_app, COORDINATOR_PORT)

    records, _ = read_canonical_csv(ROOT / "fixtures/synthetic_cohorts.csv")
    shards = write_shards(split_rows(records, arguments.parties), state / "shards")
    names = ["party-a", "party-b", "party-c"][: arguments.parties]

    runtimes = {}
    for index, name in enumerate(names):
        private = state / name
        private.mkdir(parents=True, exist_ok=True)
        os.chmod(private, 0o700)
        import_directory = private / "import"
        import_directory.mkdir(exist_ok=True)
        (import_directory / "cohort.csv").write_bytes(shards[index].read_bytes())
        client = CoordinatorClient(
            base_url=f"http://127.0.0.1:{COORDINATOR_PORT}/api/v2",
            token="pending-enrolment", client=httpx.Client(timeout=30.0))
        runtimes[name] = AgentRuntime(
            party_id=name, private_directory=private,
            import_directory=import_directory, registry_directory=private / "registry",
            worker=worker, catalogue_path=ROOT / "config/query-catalog.json",
            mapping_path=ROOT / "config/iocn-mapping.json", coordinator=client,
            study_id="synthetic-study")

    # Enrolment: each endpoint generated its own key; the operator compares fingerprints
    # out of band, then the coordinator pins them.
    tokens = {name: provision_agent(service.connection, name, "party",
                                    public_key_hex=runtime.identity.public_key
                                    .public_bytes_raw().hex())
              for name, runtime in runtimes.items()}
    operator_token = provision_agent(service.connection, "operator", "coordinator")
    provision_agent(service.connection, "recipient-one", "recipient")
    pinned = {name: runtime.identity.public_key for name, runtime in runtimes.items()}
    pinned["coordinator"] = service.identity.public_key
    roster = Roster(pinned)

    print("\n=== PROTECMed synthetic single-host demo (D1) ===")
    print("SIMULATION: separate directories on one host, not separate institutions.\n")
    print(f"coordinator API   http://127.0.0.1:{COORDINATOR_PORT}/api/v2")
    print(f"operator token    {operator_token}")
    for index, name in enumerate(names):
        runtime = runtimes[name]
        runtime.coordinator.token = tokens[name]
        runtime.pin_roster(roster)
        port = FIRST_PARTY_PORT + index
        app = create_agent_app(runtime, allowed_hosts={f"127.0.0.1:{port}"},
                               run_id="synthetic-run")
        serve(app, port)
        print(f"{name:9} UI      http://127.0.0.1:{port}/local/v2/login")
        print(f"{name:9} token   {app.state.sessions.operator_token}")
        print(f"{name:9} finger  {runtime.identity.fingerprint}")
    print("\nCtrl-C to stop.\n")
    threading.Event().wait()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
