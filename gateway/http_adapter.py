"""HTTP channel adapter.

Provides a REST API for chat, follow-up, approval, and rejection.
Workers send responses back through gateway activities. The adapter
bridges synchronous HTTP requests to asynchronous Temporal workflows
using an in-memory response store.

No business logic. No model calls. No app data.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from datetime import timedelta

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from temporalio import activity
from temporalio.client import Client
from temporalio.worker import Worker

from gateway.config import GatewayConfig
from gateway.router import Router

logger = logging.getLogger(__name__)

# Default timeout for waiting on a workflow response.
RESPONSE_TIMEOUT_SECONDS = 120


# ── Response store ───────────────────────────────────────────────


class ResponseStore:
    """In-memory store that bridges workflow activities to HTTP handlers.

    When the HTTP adapter starts a workflow or sends a signal, it creates
    a Future keyed by a request ID. The gateway activity resolves the
    Future with the workflow's response. The HTTP handler awaits the
    Future and returns the result.
    """

    def __init__(self) -> None:
        self._pending: dict[str, asyncio.Future[str]] = {}

    def create(self, request_id: str) -> asyncio.Future[str]:
        """Create a pending response slot. Returns the Future to await."""
        loop = asyncio.get_running_loop()
        future: asyncio.Future[str] = loop.create_future()
        self._pending[request_id] = future
        return future

    def resolve(self, request_id: str, text: str) -> bool:
        """Resolve a pending response. Returns True if a waiter existed."""
        future = self._pending.pop(request_id, None)
        if future is None or future.done():
            return False
        future.set_result(text)
        return True

    def cancel(self, request_id: str) -> None:
        """Cancel and remove a pending response."""
        future = self._pending.pop(request_id, None)
        if future is not None and not future.done():
            future.cancel()


# Singleton store shared between the HTTP handlers and activities.
_response_store = ResponseStore()


# ── HTTP-compatible activities ───────────────────────────────────


@dataclass
class SendMessageInput:
    """Same contract as gateway.activities.SendMessageInput."""

    chat_id: int
    text: str
    parse_mode: str | None = "HTML"


@dataclass
class SendApprovalRequestInput:
    """Same contract as gateway.activities.SendApprovalRequestInput."""

    chat_id: int
    workflow_id: str
    proposal_id: str
    title: str
    diff: str
    rationale: str | None = None
    expire_label: str | None = None


@dataclass
class SendAlertInput:
    """Same contract as gateway.activities.SendAlertInput."""

    chat_id: int
    text: str
    parse_mode: str | None = "HTML"


def create_http_activities() -> list:
    """Create gateway activities that deliver responses via the store.

    Activities resolve the pending Future so the HTTP handler can return
    the workflow's response to the caller.
    """

    @activity.defn(name="send_message")
    async def send_message(input: SendMessageInput) -> None:
        """Store the response for the waiting HTTP handler."""
        info = activity.info()
        request_id = info.workflow_id
        logger.info(
            "http send_message workflow=%s len=%d",
            request_id,
            len(input.text),
        )
        _response_store.resolve(request_id, input.text)

    @activity.defn(name="send_approval_request")
    async def send_approval_request(input: SendApprovalRequestInput) -> None:
        """Store the proposal for the waiting HTTP handler."""
        parts = [input.title, "", input.diff]
        if input.rationale:
            parts.extend(["", input.rationale])
        if input.expire_label:
            parts.extend(["", f"Expires: {input.expire_label}"])
        text = "\n".join(parts)

        info = activity.info()
        request_id = info.workflow_id
        logger.info(
            "http send_approval_request workflow=%s proposal=%s",
            request_id,
            input.proposal_id,
        )
        _response_store.resolve(request_id, text)

    @activity.defn(name="send_alert")
    async def send_alert(input: SendAlertInput) -> None:
        """Store the alert for the waiting HTTP handler."""
        info = activity.info()
        request_id = info.workflow_id
        logger.info("http send_alert workflow=%s len=%d", request_id, len(input.text))
        _response_store.resolve(request_id, input.text)

    return [send_message, send_approval_request, send_alert]


# ── Request / response models ───────────────────────────────────


class ChatRequest(BaseModel):
    """POST /chat request body."""

    text: str
    user_id: str
    workflow_id: str | None = None


class ChatResponse(BaseModel):
    """POST /chat response body."""

    workflow_id: str
    response: str


class ApprovalRequest(BaseModel):
    """POST /approve and /reject request body."""

    user_id: str = "anonymous"


# ── FastAPI application ─────────────────────────────────────────


def create_http_app(config: GatewayConfig, router: Router) -> FastAPI:
    """Build the FastAPI application with chat and approval endpoints."""

    app = FastAPI(title="Forge Gateway", version="0.1.0")

    @app.get("/health")
    async def health() -> dict:
        return {"status": "ok"}

    @app.post("/chat", response_model=ChatResponse)
    async def chat(req: ChatRequest) -> ChatResponse:
        """Start a new conversation or send a follow-up.

        Without workflow_id: classify intent, start a new Temporal
        workflow, wait for the response.
        With workflow_id: signal the existing workflow with the
        follow-up message, wait for the response.
        """
        if req.workflow_id:
            return await _handle_follow_up(req, router)
        return await _handle_new_chat(req, router)

    @app.post("/approve/{workflow_id}", response_model=ChatResponse)
    async def approve(workflow_id: str, req: ApprovalRequest) -> ChatResponse:
        """Send an approval signal to a waiting workflow."""
        return await _handle_approval(workflow_id, "approve", req, router)

    @app.post("/reject/{workflow_id}", response_model=ChatResponse)
    async def reject(workflow_id: str, req: ApprovalRequest) -> ChatResponse:
        """Send a rejection signal to a waiting workflow."""
        return await _handle_approval(workflow_id, "reject", req, router)

    return app


# ── Handler implementations ─────────────────────────────────────


async def _handle_new_chat(req: ChatRequest, router: Router) -> ChatResponse:
    """Start a new workflow and wait for the first response."""
    user_id = _parse_user_id(req.user_id)
    chat_id = int(time.time() * 1000)

    workflow_id = await router.start_chat_workflow(
        chat_id=chat_id,
        user_id=user_id,
        username=req.user_id,
        text=req.text,
    )

    response_text = await _await_response(workflow_id)
    return ChatResponse(workflow_id=workflow_id, response=response_text)


async def _handle_follow_up(req: ChatRequest, router: Router) -> ChatResponse:
    """Signal an existing workflow with a follow-up message."""
    workflow_id = req.workflow_id
    assert workflow_id is not None

    user_id = _parse_user_id(req.user_id)

    # Create a response slot before signaling so the activity can
    # resolve it even if the workflow processes the signal immediately.
    future = _response_store.create(workflow_id)

    try:
        await router.signal_follow_up(
            workflow_id=workflow_id,
            text=req.text,
            user_id=user_id,
        )
    except Exception as e:
        _response_store.cancel(workflow_id)
        raise HTTPException(
            status_code=404,
            detail=f"Workflow {workflow_id} not found or already completed",
        ) from e

    response_text = await _await_response_future(workflow_id, future)
    return ChatResponse(workflow_id=workflow_id, response=response_text)


async def _handle_approval(
    workflow_id: str,
    decision: str,
    req: ApprovalRequest,
    router: Router,
) -> ChatResponse:
    """Signal approval or rejection and wait for the confirmation."""
    user_id = _parse_user_id(req.user_id)

    future = _response_store.create(workflow_id)

    try:
        await router.signal_approval(
            workflow_id=workflow_id,
            decision=decision,
            user_id=user_id,
            timestamp=time.time(),
        )
    except Exception as e:
        _response_store.cancel(workflow_id)
        raise HTTPException(
            status_code=404,
            detail=f"Workflow {workflow_id} not found or already completed",
        ) from e

    response_text = await _await_response_future(workflow_id, future)
    return ChatResponse(workflow_id=workflow_id, response=response_text)


# ── Helpers ──────────────────────────────────────────────────────


async def _await_response(workflow_id: str) -> str:
    """Create a response slot and wait for the workflow to fill it."""
    future = _response_store.create(workflow_id)
    return await _await_response_future(workflow_id, future)


async def _await_response_future(
    workflow_id: str, future: asyncio.Future[str]
) -> str:
    """Wait for a workflow response with timeout."""
    try:
        return await asyncio.wait_for(future, timeout=RESPONSE_TIMEOUT_SECONDS)
    except TimeoutError:
        _response_store.cancel(workflow_id)
        raise HTTPException(
            status_code=504,
            detail=f"Workflow {workflow_id} did not respond within {RESPONSE_TIMEOUT_SECONDS}s",
        )


def _parse_user_id(raw: str) -> int:
    """Convert a user ID string to int. Use a hash for non-numeric IDs."""
    try:
        return int(raw)
    except ValueError:
        return abs(hash(raw)) % (10**9)


# ── Standalone runner ────────────────────────────────────────────


async def run_http_gateway(config: GatewayConfig, stop: asyncio.Event) -> None:
    """Start the HTTP adapter with its Temporal activity worker.

    Called from __main__.py when channel=http.
    """
    import uvicorn

    logger.info(
        "Connecting to Temporal at %s namespace=%s",
        config.temporal_address,
        config.temporal_namespace,
    )
    temporal_client = await Client.connect(
        config.temporal_address,
        namespace=config.temporal_namespace,
    )

    router = Router(client=temporal_client, config=config)
    activities = create_http_activities()
    app = create_http_app(config=config, router=router)

    uvi_config = uvicorn.Config(
        app,
        host="0.0.0.0",
        port=config.gateway_port,
        log_level="info",
    )
    server = uvicorn.Server(uvi_config)

    async with Worker(
        temporal_client,
        task_queue=config.gateway_task_queue,
        activities=activities,
        graceful_shutdown_timeout=timedelta(seconds=40),
    ):
        logger.info("Temporal worker started on queue=%s", config.gateway_task_queue)
        logger.info("HTTP adapter listening on port %d", config.gateway_port)

        # Run uvicorn until the stop event fires.
        serve_task = asyncio.create_task(server.serve())
        stop_task = asyncio.create_task(stop.wait())

        done, _ = await asyncio.wait(
            [serve_task, stop_task],
            return_when=asyncio.FIRST_COMPLETED,
        )

        if stop_task in done:
            server.should_exit = True
            await serve_task
        else:
            stop.set()
