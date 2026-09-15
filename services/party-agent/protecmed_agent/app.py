"""Local provider service and UI (blueprint 5.5, 4.8).

Three server-rendered screens: import and mapping status; run/key/submission status; the
verified decryption request with Approve/Reject. Loopback only, session-authenticated,
CSRF-protected, no state-changing GET, no external assets and no patient rows on screen.
"""
from __future__ import annotations
from pathlib import Path
from typing import Any, Callable

from fastapi import FastAPI, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from protecmed_protocol.errors import ProtocolError

from .poller import CoordinatorOffline, CoordinatorRejected
from .runtime import AgentRuntime
from .sessions import CSRF_FIELD, SessionStore, check_origin, set_session_cookie

LOCAL = "/local/v2"
HERE = Path(__file__).resolve().parent
MODES = {"synthetic-demo": "DEMONSTRATIE SINTETICA",
         "clinical-validation": "VALIDARE IOCN RESTRICTIONATA"}


def create_app(runtime: AgentRuntime, *, allowed_hosts: set[str],
               mode: str = "synthetic-demo", run_id: str = "synthetic-run") -> FastAPI:
    if mode not in MODES:
        raise ValueError("UNKNOWN_MODE")
    app = FastAPI(title=f"PROTECMed {runtime.party_id}", version="2.0",
                  docs_url=None, redoc_url=None, openapi_url=None)
    templates = Jinja2Templates(directory=str(HERE / "templates"))
    app.mount("/static", StaticFiles(directory=str(HERE / "static")), name="static")
    sessions = SessionStore(runtime.party_id)
    app.state.sessions = sessions
    app.state.runtime = runtime
    app.state.run_id = run_id

    def page(request: Request, name: str, **context: Any) -> HTMLResponse:
        session = sessions.require(request)
        return templates.TemplateResponse(request, name, {
            "csrf_token": session.csrf_token, "party_id": runtime.party_id,
            "mode_banner": MODES[mode], "mode": mode, "run_id": app.state.run_id,
            **context})

    def guard(request: Request, csrf_token: str):
        check_origin(request, allowed_hosts)
        session = sessions.require(request)
        sessions.check_csrf(session, csrf_token)
        return session

    def act(action: Callable[[], Any], redirect: str) -> RedirectResponse:
        """Run one local action; a transport failure never changes local state."""
        try:
            action()
        except CoordinatorOffline:
            return RedirectResponse(f"{redirect}?notice=OFFLINE", status_code=303)
        except CoordinatorRejected as rejected:
            return RedirectResponse(f"{redirect}?notice={rejected.token}", status_code=303)
        except ProtocolError as error:
            return RedirectResponse(f"{redirect}?notice={error.token}", status_code=303)
        return RedirectResponse(f"{redirect}?notice=OK", status_code=303)

    @app.exception_handler(ProtocolError)
    async def protocol_error(_: Request, error: ProtocolError) -> JSONResponse:
        return JSONResponse(status_code=400, content={"detail": error.token})

    # --- session -------------------------------------------------------------
    @app.get("/", response_class=HTMLResponse)
    async def root() -> RedirectResponse:
        return RedirectResponse(f"{LOCAL}/import", status_code=303)

    @app.get(f"{LOCAL}/login", response_class=HTMLResponse)
    async def login_form(request: Request) -> HTMLResponse:
        return templates.TemplateResponse(request, "login.html", {
            "party_id": runtime.party_id, "mode_banner": MODES[mode]})

    @app.post(f"{LOCAL}/login")
    async def login(request: Request, operator_token: str = Form(...)) -> RedirectResponse:
        check_origin(request, allowed_hosts)
        session = sessions.login(operator_token)
        response = RedirectResponse(f"{LOCAL}/import", status_code=303)
        set_session_cookie(response, sessions, session)
        return response

    # --- screen 1: import and mapping ---------------------------------------
    @app.get(f"{LOCAL}/import", response_class=HTMLResponse)
    async def import_screen(request: Request, notice: str | None = None) -> HTMLResponse:
        if sessions.current(request) is None:
            return RedirectResponse(f"{LOCAL}/login", status_code=303)
        return page(request, "import.html", files=runtime.list_import_files(),
                    status=runtime.import_status, notice=notice,
                    mapping_id=runtime.mapping.mapping_id)

    @app.post(f"{LOCAL}/import")
    async def do_import(request: Request, selection_token: str = Form(...),
                        import_mode: str = Form("literal-only"),
                        acknowledge_cache: str = Form(""),
                        csrf_token: str = Form(..., alias=CSRF_FIELD)) -> RedirectResponse:
        guard(request, csrf_token)
        return act(lambda: runtime.import_selected(
            selection_token, mode=import_mode,
            acknowledge_cache=acknowledge_cache == "on"), f"{LOCAL}/import")

    # --- screen 2: run, key and submission ----------------------------------
    @app.get(f"{LOCAL}/run", response_class=HTMLResponse)
    async def run_screen(request: Request, notice: str | None = None) -> HTMLResponse:
        if sessions.current(request) is None:
            return RedirectResponse(f"{LOCAL}/login", status_code=303)
        try:
            status = runtime.status(app.state.run_id)
        except (CoordinatorOffline, CoordinatorRejected):
            status = runtime.status(None)
            notice = notice or "OFFLINE"
        return page(request, "run.html", status=status, notice=notice)

    def step(route: str, action: Callable[[AgentRuntime, str], Any]):
        @app.post(f"{LOCAL}/{route}")
        async def handler(request: Request,
                          csrf_token: str = Form(..., alias=CSRF_FIELD)) -> RedirectResponse:
            guard(request, csrf_token)
            return act(lambda: action(runtime, app.state.run_id), f"{LOCAL}/run")

        handler.__name__ = f"post_{route.replace('-', '_')}"
        return handler

    step("accept-plan", lambda runtime_, run: runtime_.accept_plan(run))
    step("key-round", lambda runtime_, run: runtime_.key_round(run))
    step("confirm-epoch", lambda runtime_, run: runtime_.confirm_epoch(run))
    step("prepare-count", lambda runtime_, _: runtime_.prepare_count())
    step("encrypt-submit", lambda runtime_, run: runtime_.encrypt_submit(run))

    # --- screen 3: verified decryption request ------------------------------
    @app.get(f"{LOCAL}/request", response_class=HTMLResponse)
    async def request_screen(request: Request, notice: str | None = None) -> HTMLResponse:
        if sessions.current(request) is None:
            return RedirectResponse(f"{LOCAL}/login", status_code=303)
        verification = runtime.verification
        query = None
        if verification is not None:
            query = runtime.query_for(verification.request["query_sha256"])
        return page(request, "request.html", verification=verification, query=query,
                    notice=notice, decision=runtime.decision)

    @app.post(f"{LOCAL}/review-request")
    async def review(request: Request,
                     csrf_token: str = Form(..., alias=CSRF_FIELD)) -> RedirectResponse:
        guard(request, csrf_token)
        return act(lambda: runtime.review_request(app.state.run_id), f"{LOCAL}/request")

    @app.post(f"{LOCAL}/approve")
    async def approve(request: Request,
                      csrf_token: str = Form(..., alias=CSRF_FIELD)) -> RedirectResponse:
        # This form submission IS the authenticated local operator action of 4.4 step 7.
        guard(request, csrf_token)
        return act(lambda: runtime.approve(app.state.run_id), f"{LOCAL}/request")

    @app.post(f"{LOCAL}/reject")
    async def reject(request: Request, reason_code: str = Form("OPERATOR_DECLINED"),
                     csrf_token: str = Form(..., alias=CSRF_FIELD)) -> RedirectResponse:
        guard(request, csrf_token)
        return act(lambda: runtime.reject(app.state.run_id, reason_code),
                   f"{LOCAL}/request")

    # --- status --------------------------------------------------------------
    @app.get(f"{LOCAL}/status")
    async def status(request: Request) -> dict[str, Any]:
        sessions.require(request)
        try:
            return runtime.status(app.state.run_id)
        except (CoordinatorOffline, CoordinatorRejected):
            return {**runtime.status(None), "transport": "OFFLINE"}

    return app
