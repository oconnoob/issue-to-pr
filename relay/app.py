"""Run with: uvicorn relay.app:create_app --factory --workers 1."""

import asyncio
from contextlib import asynccontextmanager, suppress
import logging

from fastapi import FastAPI, HTTPException, Request
import httpx

from .config import Settings
from .delivery import Inbox, Worker
from .github import GitHub, Skip

MAX_BODY = 1024 * 1024
log = logging.getLogger("relay")


def create_app(settings=None, client=None, run_worker=True):
    settings = settings or Settings.from_env()

    @asynccontextmanager
    async def lifespan(app):
        logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
        # HTTP client URL logging can expose trigger URLs. Log decisions ourselves.
        logging.getLogger("httpx").setLevel(logging.WARNING)
        async with httpx.AsyncClient(timeout=10, follow_redirects=False) as default_client:
            transport = client if client is not None else default_client
            inbox = Inbox(settings.database)
            # Add a new source by implementing its handler and registering it here.
            sources = {"github": GitHub(settings, transport)}
            worker = Worker(settings, inbox, sources, transport)
            app.state.inbox, app.state.worker = inbox, worker
            app.state.sources = sources
            task = asyncio.create_task(worker.run()) if run_worker else None
            app.state.task = task
            try:
                yield
            finally:
                if task:
                    task.cancel()
                    with suppress(asyncio.CancelledError):
                        await task
                inbox.close()

    app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)

    @app.get("/healthz")
    async def health():
        if app.state.task and app.state.task.done():
            raise HTTPException(503, "Worker stopped; inspect service logs")
        try:
            app.state.inbox.health()
        except Exception:
            raise HTTPException(503, "Database unavailable") from None
        return {"status": "ok"}

    @app.post("/webhooks/{source}", status_code=202)
    async def webhook(source: str, request: Request):
        handler = app.state.sources.get(source)
        if handler is None:
            raise HTTPException(404, "Unknown source")
        body = bytearray()
        async for chunk in request.stream():
            body.extend(chunk)
            if len(body) > MAX_BODY:
                log.warning("source=%s decision=rejected reason=body_too_large", source)
                raise HTTPException(413, "Body exceeds 1 MiB")
        try:
            handler.verify(bytes(body), request.headers)
            delivery = handler.delivery_id(request.headers)
            candidate = handler.prepare(bytes(body), request.headers)
        except Skip as skip:
            log.info("source=%s delivery=%s decision=skipped reason=%s", source, delivery, skip)
            return {"status": "skipped", "reason": str(skip)}
        except HTTPException as error:
            log.warning("source=%s decision=rejected reason=%s", source, error.detail)
            raise
        # Persist before acknowledging; a restart keeps the queue and dedup records.
        try:
            inserted = app.state.inbox.enqueue(source, delivery, candidate)
        except Exception:
            log.error("source=%s decision=rejected reason=persistence_unavailable", source)
            raise HTTPException(503, "Delivery was not acknowledged; retry later") from None
        decision = "queued" if inserted else "duplicate"
        log.info("source=%s delivery=%s decision=%s", source, delivery, decision)
        return {"status": decision}

    return app
