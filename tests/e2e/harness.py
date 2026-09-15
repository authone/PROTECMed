"""Wires the coordinator service, two or three party agents and the real worker.

Transport is httpx over ASGI, so there are no sockets and no ports, but the requests,
headers, cookies, CSRF tokens and multipart bodies are the real ones. Separate
directories on one host remain a SIMULATION of institutional separation.
"""
from __future__ import annotations
import csv
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx
from fastapi.testclient import TestClient

from protecmed_agent.app import create_app as create_agent_app
from protecmed_agent.poller import CoordinatorClient
from protecmed_agent.runtime import AgentRuntime
from protecmed_coordinator.app import create_app as create_coordinator_app
from protecmed_coordinator.runtime import CoordinatorService
from protecmed_coordinator.security import provision_agent
from protecmed_party.canonical import FIELDS
from protecmed_party.importer import read_canonical_csv
from protecmed_party.splitter import split_rows, write_shards
from protecmed_protocol.canonical import payload_hash, sha256_hex
from protecmed_protocol.identity import Identity, Roster
from protecmed_worker import WorkerClient

STUDY_ID = "synthetic-study"
RUN_ID = "synthetic-run"
RECIPIENTS = ["recipient-one"]
AGENT_HOST = "127.0.0.1:8081"


class OfflineTransport(httpx.BaseTransport):
    """Every request fails as if the coordinator were unreachable."""

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("offline", request=request)


@dataclass
class Deployment:
    root: Path
    worker_binary: Path
    library: Path
    party_count: int = 2
    catalogue: Path = field(default=Path("config/query-catalog.json"))
    mapping: Path = field(default=Path("config/iocn-mapping.json"))

    def __post_init__(self) -> None:
        repository = Path(__file__).resolve().parents[2]
        self.catalogue = repository / self.catalogue
        self.mapping = repository / self.mapping
        self.names = ["party-a", "party-b", "party-c"][: self.party_count]
        worker = WorkerClient(self.worker_binary, library_path=self.library)

        self.service = CoordinatorService(database=self.root / "coordinator.db",
                                          storage=self.root / "coordinator",
                                          worker=worker)
        self.coordinator_app = create_coordinator_app(self.service)
        self.shards = self._make_shards()
        self.agents: dict[str, AgentRuntime] = {}
        self.clients: dict[str, TestClient] = {}
        self.http: dict[str, httpx.Client] = {}

        # Each endpoint generates its own identity key locally (blueprint 4.2). The
        # coordinator enrols the resulting public key; it never generates a party key.
        for name in self.names:
            self._build_agent(name, worker)
        self.identities = {name: runtime.identity for name, runtime in self.agents.items()}
        self.tokens = {
            name: provision_agent(self.service.connection, name, "party",
                                  public_key_hex=identity.public_key
                                  .public_bytes_raw().hex())
            for name, identity in self.identities.items()}
        for name, token in self.tokens.items():
            self.agents[name].coordinator.token = token
        self.operator_token = provision_agent(self.service.connection, "operator",
                                              "coordinator")
        self.recipient_token = provision_agent(self.service.connection, "recipient-one",
                                               "recipient")
        # Fingerprints are compared out of band before the roster is locked.
        pinned = {name: identity.public_key for name, identity in self.identities.items()}
        pinned["coordinator"] = self.service.identity.public_key
        self.roster = Roster(pinned)
        for runtime in self.agents.values():
            runtime.pin_roster(self.roster)

    # --- setup helpers -------------------------------------------------------
    def _make_shards(self) -> dict[str, Path]:
        repository = Path(__file__).resolve().parents[2]
        records, _ = read_canonical_csv(repository / "fixtures/synthetic_cohorts.csv")
        directory = self.root / "shards"
        paths = write_shards(split_rows(records, self.party_count), directory)
        return dict(zip(self.names, paths))

    def _build_agent(self, name: str, worker: WorkerClient) -> None:
        private = self.root / name
        private.mkdir(parents=True, exist_ok=True)
        os.chmod(private, 0o700)
        import_directory = private / "import"
        import_directory.mkdir(exist_ok=True)
        shard = self.shards[name]
        (import_directory / "cohort.csv").write_bytes(shard.read_bytes())

        # TestClient is an httpx.Client with a synchronous ASGI transport, so the
        # agent's ordinary outbound client works unchanged against the in-process app.
        http = TestClient(self.coordinator_app, base_url="http://coordinator")
        self.http[name] = http
        client = CoordinatorClient(base_url="http://coordinator/api/v2",
                                   token="pending-enrolment", client=http)
        runtime = AgentRuntime(
            party_id=name, private_directory=private,
            import_directory=import_directory,
            registry_directory=private / "registry", worker=worker,
            catalogue_path=self.catalogue, mapping_path=self.mapping,
            coordinator=client, study_id=STUDY_ID)
        self.agents[name] = runtime
        app = create_agent_app(runtime, allowed_hosts={AGENT_HOST}, run_id=RUN_ID)
        self.clients[name] = TestClient(app, base_url=f"http://{AGENT_HOST}")

    def go_offline(self, name: str) -> None:
        self._online = getattr(self, "_online", {})
        self._online[name] = self.http[name]._transport
        self.http[name]._transport = OfflineTransport()

    def go_online(self, name: str) -> None:
        self.http[name]._transport = self._online[name]

    # --- coordinator API -----------------------------------------------------
    def api(self, method: str, path: str, *, token: str | None = None,
            key: str | None = None, **kwargs) -> httpx.Response:
        headers = {"Authorization": f"Bearer {token or self.operator_token}"}
        if key:
            headers["Idempotency-Key"] = key
        if not hasattr(self, "_operator_client"):
            self._operator_client = TestClient(self.coordinator_app,
                                               base_url="http://coordinator")
        return self._operator_client.request(method, f"/api/v2{path}", headers=headers,
                                             **kwargs)

    def query_sha256(self, query_id: str = "Q004") -> str:
        entry = next(q for q in self.agents[self.names[0]].catalogue
                     if q["query_id"] == query_id)
        return payload_hash(entry)

    def freeze_run(self, query_id: str = "Q004") -> httpx.Response:
        self.api("POST", "/studies", key="key-study-000001",
                 json={"study_id": STUDY_ID})
        roster = [{"party_id": name,
                   "identity_key_sha256": self.identities[name].fingerprint,
                   "snapshot_token": self.agents[name].snapshot.snapshot_token}
                  for name in self.names]
        return self.api("POST", f"/studies/{STUDY_ID}/runs", key="key-run-000001",
                        json={"run_id": RUN_ID, "roster": roster,
                              "recipient_ids": RECIPIENTS,
                              "query_sha256": self.query_sha256(query_id),
                              "mapping_sha256": sha256_hex(self.mapping.read_bytes())})

    # --- UI driving ----------------------------------------------------------
    def login(self, name: str) -> TestClient:
        client = self.clients[name]
        store = client.app.state.sessions
        response = client.post("/local/v2/login",
                               data={"operator_token": store.operator_token},
                               follow_redirects=False)
        assert response.status_code == 303, response.status_code
        return client

    @staticmethod
    def csrf_of(client: TestClient, path: str = "/local/v2/import") -> str:
        html = client.get(path).text
        marker = 'name="csrf_token" value="'
        start = html.index(marker) + len(marker)
        return html[start:html.index('"', start)]

    def ui_post(self, name: str, path: str, **data: Any) -> httpx.Response:
        client = self.clients[name]
        token = self.csrf_of(client, "/local/v2/run" if "import" not in path
                             else "/local/v2/import")
        return client.post(path, data={"csrf_token": token, **data},
                           follow_redirects=False)

    def notice_of(self, response: httpx.Response) -> str:
        location = response.headers.get("location", "")
        return location.partition("notice=")[2]
