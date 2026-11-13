"""Local-only Claude signal bridge for the MT5 EA. Fail closed on every error path.

  POST /v1/signal        submit one closed-bar snapshot -> 200 final | 202 pending
  GET  /v1/signal/{id}   poll -> 200 pending | final
  GET  /health

The EA never waits for retries: it submits once and polls from OnTimer. Retries, backoff
and the circuit breaker run in a background task here.
"""
from __future__ import annotations

import asyncio
import hashlib
import secrets
from contextlib import asynccontextmanager
from typing import Optional, Sequence

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse

from .audit import AuditLog
from .config import Settings, load_settings
from .models import REQUEST_ID_RE, SignalRequest, SignalResponse, hold
from .providers import AnthropicProvider, Provider
from .service import Decider
from .store import DedupStore

MAX_BODY_BYTES = 16 * 1024
LOOPBACK_CLIENTS = ("127.0.0.1", "::1")


def create_app(settings: Optional[Settings] = None, provider: Optional[Provider] = None, *,
               decider_kwargs: Optional[dict] = None,
               allowed_clients: Sequence[str] = LOOPBACK_CLIENTS,
               allowed_hosts: Optional[Sequence[str]] = None) -> FastAPI:
    s = settings or load_settings()
    if allowed_hosts is None:
        allowed_hosts = tuple(f"{h}:{s.port}" for h in ("127.0.0.1", "localhost", "[::1]"))
    if provider is None and s.ai_enabled and s.has_key:
        provider = AnthropicProvider(s.api_key, s.request_timeout, s.effort, s.max_tokens)
    store = DedupStore(s.db_path)
    audit = AuditLog(s.audit_path, secrets=(s.api_key, s.bridge_token))
    decider = Decider(s, provider, store, audit, **(decider_kwargs or {}))
    tasks: set[asyncio.Task] = set()

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        # A request left pending by a previous process can never be answered usefully:
        # the bar is stale. Decide HOLD; never re-call the AI for it.
        for rid in store.pending_ids():
            store.finish(rid, hold(rid, 0, "bridge restarted before decision", "restart").model_dump_json())
        store.purge_older_than(s.retention_days * 86400)
        audit.write("startup", ai_enabled=s.ai_enabled, voting=s.voting_enabled,
                    model_ids=list(s.active_models), host=s.host, port=s.port)
        yield
        for t in list(tasks):
            t.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        for rid in store.pending_ids():
            store.finish(rid, hold(rid, 0, "bridge shut down before decision", "restart").model_dump_json())

    app = FastAPI(title="MT5 Claude Signal Bridge", lifespan=lifespan,
                  docs_url=None, redoc_url=None, openapi_url=None)
    app.state.decider = decider
    app.state.store = store
    app.state.settings = s

    @app.middleware("http")
    async def limit_body(request: Request, call_next):
        # Runs before the body is read/parsed. POST without a sane Content-Length is refused.
        if request.method == "POST":
            length = request.headers.get("content-length", "")
            if not length.isdigit() or int(length) > MAX_BODY_BYTES:
                return JSONResponse({"detail": "Payload too large"}, 413)
        return await call_next(request)

    async def guard(request: Request) -> None:
        client = request.client.host if request.client else ""
        if client not in allowed_clients:
            raise HTTPException(403, "Forbidden")
        if request.headers.get("host", "") not in allowed_hosts:   # DNS-rebinding defence
            raise HTTPException(403, "Forbidden")
        if "origin" in request.headers:                             # browsers are never a client
            raise HTTPException(403, "Forbidden")
        supplied = (request.headers.get("x-bridge-token") or "").encode("utf-8", "ignore")
        expected = s.bridge_token.encode("utf-8")
        if not expected or not secrets.compare_digest(supplied, expected):
            raise HTTPException(401, "Unauthorized")

    def _stored(rid: str, status: str, body: Optional[str]) -> JSONResponse:
        if status == "final" and body:
            return JSONResponse(SignalResponse.model_validate_json(body).model_dump(), 200)
        return JSONResponse(hold(rid, 0, "pending", "pending", status="pending").model_dump(), 202)

    @app.post("/v1/signal", dependencies=[Depends(guard)])
    async def submit(req: SignalRequest):
        payload_hash = hashlib.sha256(req.model_dump_json().encode()).hexdigest()
        state, status, body = store.begin(req.request_id, payload_hash)
        if state == "conflict":
            raise HTTPException(409, "request_id reused with a different payload")
        if state == "exists":
            return _stored(req.request_id, status, body)
        early = decider.precheck(req)
        if early is not None:
            decider.finalize(req, early, [], 0)
            return JSONResponse(early.model_dump(), 200)

        task = asyncio.create_task(decider.decide(req))
        tasks.add(task)
        task.add_done_callback(tasks.discard)
        return JSONResponse(hold(req.request_id, req.bar_time, "pending", "pending",
                                 status="pending").model_dump(), 202)

    @app.get("/v1/signal/{request_id}", dependencies=[Depends(guard)])
    async def poll(request_id: str):
        if not REQUEST_ID_RE.fullmatch(request_id):
            raise HTTPException(400, "bad request_id")
        row = store.get(request_id)
        if row is None:
            raise HTTPException(404, "unknown request_id")
        resp = _stored(request_id, row[0], row[1])
        if row[0] != "final":
            resp.status_code = 200
        return resp

    @app.get("/health", dependencies=[Depends(guard)])
    async def health():
        return {"status": "ok", "ai_enabled": s.ai_enabled, "voting": s.voting_enabled,
                "models": list(s.active_models), "circuit": decider.breaker.state,
                "provider_configured": provider is not None}

    return app
