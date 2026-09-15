"""Coordinator HTTP API (blueprint 5.4, 5.6, 4.8).

Every POST requires an authenticated identity, a purpose-specific role and an
idempotency key. No route accepts a clinical XLSX or CSV, no payload carries a
filesystem path or URL, and no state-changing GET exists. Public API documentation,
CORS and stack traces are off: errors are symbolic tokens.
"""
from __future__ import annotations
import json
from pathlib import Path
from typing import Any, Callable

from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, Response, UploadFile
from fastapi.responses import JSONResponse

from protecmed_protocol.errors import IntegrityHold, ProtocolError

from .db import transaction
from .runtime import CoordinatorService
from .security import (Agent, MAX_BINARY_BYTES, MAX_JSON_BYTES, authenticate,
                       idempotency_key, read_json_body, remember, replay, require_role,
                       require_self)

API = "/api/v2"


def create_app(service: CoordinatorService, *, expose_docs: bool = False) -> FastAPI:
    app = FastAPI(title="PROTECMed coordinator", version="2.0",
                  docs_url="/docs" if expose_docs else None,
                  redoc_url=None,
                  openapi_url="/openapi.json" if expose_docs else None)
    app.state.service = service
    # No CORS middleware is installed: cross-origin calls are not part of this design.

    def agent_of(request: Request) -> Agent:
        return authenticate(service.connection, request)

    @app.exception_handler(ProtocolError)
    async def protocol_error(_: Request, error: ProtocolError) -> JSONResponse:
        status = 409 if isinstance(error, IntegrityHold) else 400
        return JSONResponse(status_code=status, content={"detail": error.token})

    @app.exception_handler(Exception)
    async def unexpected(_: Request, __: Exception) -> JSONResponse:
        # Never a stack trace or a raw exception message.
        return JSONResponse(status_code=500, content={"detail": "INTERNAL_ERROR"})

    async def idempotent_json(request: Request, agent: Agent, route: str,
                              action: Callable[[dict[str, Any]], dict[str, Any]],
                              status_code: int = 200) -> Response:
        document, raw = await read_json_body(request)
        key = idempotency_key(request)
        cached = replay(service.connection, agent, key, route, raw)
        if cached is not None:
            return JSONResponse(status_code=cached[0], content=cached[1])
        result = action(document)
        with transaction(service.connection) as connection:
            remember(connection, agent, key, route, raw, status_code, result)
        return JSONResponse(status_code=status_code, content=result)

    # --- studies and runs ----------------------------------------------------
    @app.post(f"{API}/studies")
    async def create_study(request: Request, agent: Agent = Depends(agent_of)) -> Response:
        require_role(agent, "coordinator")

        def action(document: dict[str, Any]) -> dict[str, Any]:
            service.create_study(document["study_id"])
            return {"study_id": document["study_id"]}

        return await idempotent_json(request, agent, "studies", action, 201)

    @app.post(API + "/studies/{study_id}/runs")
    async def create_run(study_id: str, request: Request,
                         agent: Agent = Depends(agent_of)) -> Response:
        require_role(agent, "coordinator")

        def action(document: dict[str, Any]) -> dict[str, Any]:
            return service.create_run(
                study_id=study_id, run_id=document["run_id"],
                roster_entries=document["roster"],
                recipient_ids=document["recipient_ids"],
                query_sha256=document["query_sha256"],
                mapping_sha256=document["mapping_sha256"])

        return await idempotent_json(request, agent, "runs", action, 201)

    def member_or_403(agent: Agent, run_id: str) -> dict[str, Any]:
        row = service.run_row(run_id)
        if row is None:
            raise HTTPException(status_code=404, detail="RUN_NOT_FOUND")
        plan = json.loads(row["plan_json"]) if row["plan_json"] else None
        members = {entry["party_id"] for entry in plan["roster"]} if plan else set()
        if agent.role == "coordinator" or agent.agent_id in members:
            return {"row": row, "plan": plan}
        if agent.role == "recipient" and plan and agent.agent_id in plan["recipient_ids"]:
            return {"row": row, "plan": plan}
        raise HTTPException(status_code=403, detail="NOT_A_RUN_MEMBER")

    @app.get(API + "/runs/{run_id}")
    async def read_run(run_id: str, agent: Agent = Depends(agent_of)) -> dict[str, Any]:
        """Sanitized state and the signed objects a member needs. A poll cannot approve."""
        context = member_or_403(agent, run_id)
        row = context["row"]
        coordinator = service.hydrate(run_id)
        return {
            "run_id": run_id, "study_id": row["study_id"], "state": row["state"],
            "plan_envelope": coordinator.plan_envelope,
            "epoch_envelope": coordinator.epoch_envelope,
            "context_sha256": row["context_sha256"],
            "key_rounds": [record.envelope for record in coordinator.key_rounds],
            "accepted_by": sorted(coordinator.acceptances),
            "confirmed_by": sorted(coordinator.confirmations),
            "submitted_by": sorted(coordinator.submissions),
            "approved_by": sorted(coordinator.partials),
            "rejected_by": sorted(coordinator.rejections),
            "input_set_envelope": coordinator.input_set_envelope,
            "submission_envelopes": [record.envelope
                                     for record in coordinator.submissions.values()],
            "aggregate_sha256": row["aggregate_sha256"],
            "request_envelope": coordinator.request_envelope,
        }

    # --- party-signed messages ------------------------------------------------
    def signed_route(kind: str, route: str):
        @app.post(f"{API}/runs/{{run_id}}/{route}")
        async def handler(run_id: str, request: Request,
                          agent: Agent = Depends(agent_of)) -> Response:
            require_role(agent, "party")
            member_or_403(agent, run_id)

            def action(document: dict[str, Any]) -> dict[str, Any]:
                require_self(agent, document.get("signer_id", ""))
                return service.accept_message(run_id=run_id, party_id=agent.agent_id,
                                              kind=kind, envelope=document)

            return await idempotent_json(request, agent, route, action, 202)

        handler.__name__ = f"post_{route.replace('-', '_')}"
        return handler

    signed_route("plan-acceptance", "plan-acceptances")
    signed_route("epoch-confirmation", "epoch-confirmations")
    signed_route("rejection", "rejections")

    async def multipart(kind: str, run_id: str, agent: Agent, envelope: str,
                        artifact: UploadFile, key: str) -> Response:
        require_role(agent, "party")
        member_or_403(agent, run_id)
        raw = envelope.encode("utf-8")
        if len(raw) > MAX_JSON_BYTES:
            raise HTTPException(status_code=413, detail="JSON_TOO_LARGE")
        from protecmed_protocol.canonical import parse_json
        document = parse_json(raw)
        require_self(agent, document.get("signer_id", ""))
        payload = await artifact.read(MAX_BINARY_BYTES + 1)
        if len(payload) > MAX_BINARY_BYTES:
            raise HTTPException(status_code=413, detail="ARTIFACT_SIZE")
        cached = replay(service.connection, agent, key, kind, raw)
        if cached is not None:
            return JSONResponse(status_code=cached[0], content=cached[1])
        result = service.accept_message(run_id=run_id, party_id=agent.agent_id, kind=kind,
                                        envelope=document, artifact=payload)
        with transaction(service.connection) as connection:
            remember(connection, agent, key, kind, raw, 202, result)
        return JSONResponse(status_code=202, content=result)

    @app.post(API + "/runs/{run_id}/key-rounds")
    async def post_key_round(run_id: str, request: Request, envelope: str = Form(...),
                             artifact: UploadFile = File(...),
                             agent: Agent = Depends(agent_of)) -> Response:
        return await multipart("key-round", run_id, agent, envelope, artifact,
                               idempotency_key(request))

    @app.post(API + "/runs/{run_id}/submissions")
    async def post_submission(run_id: str, request: Request, envelope: str = Form(...),
                              artifact: UploadFile = File(...),
                              agent: Agent = Depends(agent_of)) -> Response:
        return await multipart("encrypted-count", run_id, agent, envelope, artifact,
                               idempotency_key(request))

    @app.post(API + "/runs/{run_id}/partials")
    async def post_partial(run_id: str, request: Request, envelope: str = Form(...),
                           artifact: UploadFile = File(...),
                           agent: Agent = Depends(agent_of)) -> Response:
        return await multipart("partial", run_id, agent, envelope, artifact,
                               idempotency_key(request))

    # --- coordinator operations ----------------------------------------------
    @app.post(API + "/runs/{run_id}/context")
    async def post_context(run_id: str, request: Request,
                           agent: Agent = Depends(agent_of)) -> Response:
        require_role(agent, "coordinator")
        return await idempotent_json(
            request, agent, "context",
            lambda _: {"context_sha256": service.create_context(run_id)}, 201)

    @app.post(API + "/runs/{run_id}/epoch")
    async def post_epoch(run_id: str, request: Request,
                         agent: Agent = Depends(agent_of)) -> Response:
        require_role(agent, "coordinator")
        return await idempotent_json(request, agent, "epoch",
                                     lambda _: service.publish_epoch(run_id), 201)

    @app.post(API + "/runs/{run_id}/evaluate")
    async def post_evaluate(run_id: str, request: Request,
                            agent: Agent = Depends(agent_of)) -> Response:
        require_role(agent, "coordinator")
        return await idempotent_json(request, agent, "evaluate",
                                     lambda _: service.evaluate(run_id), 201)

    @app.post(API + "/runs/{run_id}/decryption-request")
    async def post_request(run_id: str, request: Request,
                           agent: Agent = Depends(agent_of)) -> Response:
        require_role(agent, "coordinator")
        return await idempotent_json(
            request, agent, "decryption-request",
            lambda document: service.create_request(
                run_id, ttl_seconds=int(document.get("ttl_seconds", 900))), 201)

    @app.post(API + "/runs/{run_id}/fuse")
    async def post_fuse(run_id: str, request: Request,
                        agent: Agent = Depends(agent_of)) -> Response:
        """The all-party gate lives in the protocol layer; n comes from the frozen plan."""
        require_role(agent, "coordinator")
        return await idempotent_json(request, agent, "fuse",
                                     lambda _: service.fuse(run_id), 200)

    # --- reads ----------------------------------------------------------------
    @app.get(API + "/runs/{run_id}/result")
    async def read_result(run_id: str, agent: Agent = Depends(agent_of)) -> dict[str, Any]:
        context = member_or_403(agent, run_id)
        plan = context["plan"]
        if agent.role == "recipient" and agent.agent_id not in plan["recipient_ids"]:
            raise HTTPException(status_code=403, detail="NOT_A_RECIPIENT")
        if agent.role == "party":
            raise HTTPException(status_code=403, detail="NOT_A_RECIPIENT")
        receipt = service.receipt(run_id)
        if receipt is None:
            # No value exists before release; the route does not hint at one either.
            return {"run_id": run_id, "state": context["row"]["state"], "released": False}
        return {"run_id": run_id, "state": context["row"]["state"], "released": True,
                "aggregate": receipt["aggregate"], "fused_at": receipt["fused_at"]}

    @app.get(API + "/runs/{run_id}/evidence")
    async def read_evidence(run_id: str, agent: Agent = Depends(agent_of)) -> dict[str, Any]:
        """Sanitized export: hashes and signed decisions, never the partial binaries.

        The full set of partials plus the aggregate is a decryption-capable archive
        (blueprint 4.6), so it is deliberately not part of this response.
        """
        member_or_403(agent, run_id)
        require_role(agent, "coordinator", "recipient")
        coordinator = service.hydrate(run_id)
        receipt = service.receipt(run_id)
        return {
            "run_id": run_id,
            "state": coordinator.state.state,
            "run_plan_sha256": coordinator.plan_sha256,
            "epoch_sha256": coordinator.epoch_sha256,
            "context_sha256": coordinator.context_sha256,
            "aggregate_sha256": coordinator.aggregate_sha256,
            "input_set_sha256": (coordinator.request or {}).get("input_set_sha256"),
            "decisions": [
                {"party_id": party_id, "decision": "APPROVE",
                 "approved_at": record.payload["approved_at"],
                 "role": record.payload["role"],
                 "partial_sha256": record.payload["partial_sha256"]}
                for party_id, record in sorted(coordinator.partials.items())
            ] + [
                {"party_id": party_id, "decision": "REJECT",
                 "rejected_at": payload["rejected_at"],
                 "reason_code": payload["reason_code"]}
                for party_id, payload in sorted(coordinator.rejections.items())
            ],
            "released_aggregate": receipt["aggregate"] if receipt else None,
            "partial_binaries_included": False,
        }

    @app.get(API + "/runs/{run_id}/artifacts/{digest}")
    async def read_artifact(run_id: str, digest: str,
                            agent: Agent = Depends(agent_of)) -> Response:
        # Run membership is checked even for a known content hash.
        member_or_403(agent, run_id)
        payload = service.artifacts.get(service.connection, run_id=run_id, digest=digest)
        return Response(content=payload, media_type="application/octet-stream")

    return app
