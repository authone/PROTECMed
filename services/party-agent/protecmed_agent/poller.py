"""Outbound-only coordinator client (blueprint 1.3, 4.7).

Party traffic is outbound. The coordinator never calls a network-facing provider
decryption API: this agent polls for work, downloads immutable public artifacts and
uploads signed responses. A poll can announce a request; it cannot approve one.

A retry resends the identical bytes under the identical idempotency key, so a lost
response costs a round trip, never a second cryptographic artifact.
"""
from __future__ import annotations
import hashlib
import json
from dataclasses import dataclass
from typing import Any

import httpx


class CoordinatorOffline(RuntimeError):
    """The coordinator could not be reached. The local run state is unchanged."""


class CoordinatorRejected(RuntimeError):
    def __init__(self, status_code: int, token: str) -> None:
        super().__init__(f"{status_code}: {token}")
        self.status_code = status_code
        self.token = token


@dataclass
class CoordinatorClient:
    base_url: str
    token: str
    client: httpx.Client

    def _headers(self, idempotency_key: str | None = None) -> dict[str, str]:
        headers = {"Authorization": f"Bearer {self.token}"}
        if idempotency_key:
            headers["Idempotency-Key"] = idempotency_key
        return headers

    @staticmethod
    def stable_key(*parts: str) -> str:
        """Deterministic per (run, party, action) so a retry reuses the same key."""
        return "k-" + hashlib.sha256("|".join(parts).encode("ascii")).hexdigest()[:40]

    def _send(self, request: httpx.Request) -> httpx.Response:
        try:
            response = self.client.send(request)
        except httpx.HTTPError:
            raise CoordinatorOffline("COORDINATOR_UNREACHABLE") from None
        if response.status_code >= 400:
            detail = "REQUEST_FAILED"
            try:
                detail = response.json().get("detail", detail)
            except ValueError:
                pass
            raise CoordinatorRejected(response.status_code, str(detail))
        return response

    def get_run(self, run_id: str) -> dict[str, Any]:
        request = self.client.build_request(
            "GET", f"{self.base_url}/runs/{run_id}", headers=self._headers())
        return self._send(request).json()

    def get_artifact(self, run_id: str, digest: str) -> bytes:
        request = self.client.build_request(
            "GET", f"{self.base_url}/runs/{run_id}/artifacts/{digest}",
            headers=self._headers())
        payload = self._send(request).content
        if hashlib.sha256(payload).hexdigest() != digest:
            raise CoordinatorRejected(200, "ARTIFACT_HASH_MISMATCH")
        return payload

    def post_envelope(self, run_id: str, route: str, envelope: dict[str, Any],
                      key: str) -> dict[str, Any]:
        request = self.client.build_request(
            "POST", f"{self.base_url}/runs/{run_id}/{route}",
            headers={**self._headers(key), "Content-Type": "application/json"},
            content=json.dumps(envelope, sort_keys=True).encode("ascii"))
        return self._send(request).json()

    def post_artifact(self, run_id: str, route: str, envelope: dict[str, Any],
                      artifact: bytes, key: str) -> dict[str, Any]:
        request = self.client.build_request(
            "POST", f"{self.base_url}/runs/{run_id}/{route}", headers=self._headers(key),
            data={"envelope": json.dumps(envelope, sort_keys=True)},
            files={"artifact": ("artifact.bin", artifact, "application/octet-stream")})
        return self._send(request).json()
