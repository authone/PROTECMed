"""Local operator sessions, CSRF and origin checks (blueprint 4.8).

The local UI is reachable only over loopback. Cookies do not isolate applications by
port, so each agent uses a distinct cookie name. State-changing requests need a session,
a CSRF token and an exact Host/Origin match; there are no state-changing GET routes.
"""
from __future__ import annotations
import hmac
import secrets
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import HTTPException, Request

SESSION_TTL_MINUTES = 60
CSRF_FIELD = "csrf_token"


@dataclass
class Session:
    session_id: str
    csrf_token: str
    expires_at: datetime


@dataclass
class SessionStore:
    """In-memory only: local sessions are cleared when the agent restarts (4.8/6.6)."""

    party_id: str
    operator_token: str = field(default_factory=lambda: secrets.token_urlsafe(24))
    sessions: dict[str, Session] = field(default_factory=dict)

    @property
    def cookie_name(self) -> str:
        return f"protecmed_session_{self.party_id.replace('-', '_')}"

    def login(self, token: str) -> Session:
        if not hmac.compare_digest(token, self.operator_token):
            raise HTTPException(status_code=401, detail="BAD_OPERATOR_TOKEN")
        session = Session(secrets.token_urlsafe(24), secrets.token_urlsafe(24),
                          datetime.now(timezone.utc) +
                          timedelta(minutes=SESSION_TTL_MINUTES))
        self.sessions[session.session_id] = session
        return session

    def current(self, request: Request) -> Session | None:
        session_id = request.cookies.get(self.cookie_name)
        session = self.sessions.get(session_id or "")
        if session is None:
            return None
        if session.expires_at <= datetime.now(timezone.utc):
            self.sessions.pop(session.session_id, None)
            return None
        return session

    def require(self, request: Request) -> Session:
        session = self.current(request)
        if session is None:
            raise HTTPException(status_code=401, detail="LOGIN_REQUIRED")
        return session

    def check_csrf(self, session: Session, submitted: str | None) -> None:
        if not submitted or not hmac.compare_digest(session.csrf_token, submitted):
            raise HTTPException(status_code=403, detail="CSRF_TOKEN_INVALID")


def check_origin(request: Request, allowed_hosts: set[str]) -> None:
    """Exact Host check, and an exact Origin match when the browser sends one."""
    host = request.headers.get("host", "")
    if host not in allowed_hosts:
        raise HTTPException(status_code=403, detail="HOST_NOT_ALLOWED")
    origin = request.headers.get("origin")
    if origin is not None and origin not in {f"http://{host}", f"https://{host}"}:
        raise HTTPException(status_code=403, detail="ORIGIN_NOT_ALLOWED")


def set_session_cookie(response: Any, store: SessionStore, session: Session) -> None:
    response.set_cookie(store.cookie_name, session.session_id, httponly=True,
                        samesite="strict", secure=False, path="/",
                        max_age=SESSION_TTL_MINUTES * 60)
