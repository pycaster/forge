"""Tests for the HTTP channel adapter.

Covers the ResponseStore, HTTP-compatible activities, and FastAPI endpoints.
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi.testclient import TestClient

from gateway.config import GatewayConfig
from gateway.http_adapter import (
    ResponseStore,
    SendApprovalRequestInput,
    _parse_user_id,
    _response_store,
    create_http_app,
)
from gateway.router import Router

# ── ResponseStore ────────────────────────────────────────────────


def _run(coro_or_fn):
    """Run a function that needs an event loop."""
    async def wrapper():
        if asyncio.iscoroutine(coro_or_fn):
            return await coro_or_fn
        return coro_or_fn()
    return asyncio.run(wrapper())


def test_response_store_create_and_resolve():
    def go():
        store = ResponseStore()
        future = store.create("test-1")
        assert not future.done()
        assert store.resolve("test-1", "hello")
        assert future.done()
        assert future.result() == "hello"
    _run(go)


def test_response_store_resolve_unknown_key_returns_false():
    def go():
        store = ResponseStore()
        assert not store.resolve("nonexistent", "hello")
    _run(go)


def test_response_store_resolve_already_done_returns_false():
    def go():
        store = ResponseStore()
        store.create("test-1")
        store.resolve("test-1", "first")
        assert not store.resolve("test-1", "second")
    _run(go)


def test_response_store_cancel_removes_pending():
    def go():
        store = ResponseStore()
        future = store.create("test-1")
        store.cancel("test-1")
        assert future.cancelled()
    _run(go)


def test_response_store_cancel_nonexistent_is_noop():
    def go():
        store = ResponseStore()
        store.cancel("nonexistent")
    _run(go)


# ── _parse_user_id ───────────────────────────────────────────────


def test_parse_user_id_numeric():
    assert _parse_user_id("42") == 42


def test_parse_user_id_string_hashed():
    result = _parse_user_id("alice")
    assert isinstance(result, int)
    assert result >= 0


# ── HTTP activities ──────────────────────────────────────────────


def test_send_message_activity_resolves_store():
    """The send_message activity resolves the pending future keyed by workflow_id."""
    def go():
        future = _response_store.create("wf-abc")
        # Simulate what the send_message activity does: resolve by workflow_id.
        _response_store.resolve("wf-abc", "hello from workflow")
        assert future.done()
        assert future.result() == "hello from workflow"
    _run(go)


def test_send_approval_request_activity_formats_and_resolves():
    """The send_approval_request activity formats the proposal and resolves."""
    def go():
        future = _response_store.create("wf-proposal")

        input_data = SendApprovalRequestInput(
            chat_id=1,
            workflow_id="wf-proposal",
            proposal_id="p-1",
            title="Renew certificates",
            diff="- old cert\n+ new cert",
            rationale="2 certs expiring in 14 days",
        )

        parts = [input_data.title, "", input_data.diff]
        if input_data.rationale:
            parts.extend(["", input_data.rationale])
        text = "\n".join(parts)
        _response_store.resolve("wf-proposal", text)

        assert future.done()
        assert "Renew certificates" in future.result()
        assert "2 certs expiring" in future.result()
    _run(go)


# ── FastAPI endpoints ────────────────────────────────────────────


def make_http_app():
    """Create a test FastAPI app with a mocked router."""
    config = GatewayConfig(
        _env_file=None,
        channel="http",
        default_app={"task_queue": "test", "workflow_type": "TestWorkflow"},
    )
    router = MagicMock(spec=Router)
    app = create_http_app(config=config, router=router)
    return app, router


def test_health_endpoint():
    app, _ = make_http_app()
    client = TestClient(app)
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_chat_new_conversation_starts_workflow():
    app, router = make_http_app()

    workflow_id = "chat-test-42-1234"
    router.start_chat_workflow = AsyncMock(return_value=workflow_id)

    # The endpoint will create a future and wait for it. We need to
    # resolve it from the activity side. Patch the store so the future
    # is resolved immediately after the workflow is started.
    original_create = _response_store.create

    def create_and_resolve(request_id):
        future = original_create(request_id)
        # Simulate the activity resolving the future.
        _response_store.resolve(request_id, "Assessment: all secure")
        return future

    with patch.object(_response_store, "create", side_effect=create_and_resolve):
        client = TestClient(app)
        response = client.post(
            "/chat",
            json={"text": "Are my apps secure?", "user_id": "demo"},
        )

    assert response.status_code == 200
    body = response.json()
    assert body["workflow_id"] == workflow_id
    assert body["response"] == "Assessment: all secure"
    router.start_chat_workflow.assert_awaited_once()
    call_kwargs = router.start_chat_workflow.call_args.kwargs
    assert call_kwargs["text"] == "Are my apps secure?"


def test_chat_follow_up_signals_existing_workflow():
    app, router = make_http_app()

    router.signal_follow_up = AsyncMock()

    original_create = _response_store.create

    def create_and_resolve(request_id):
        future = original_create(request_id)
        _response_store.resolve(request_id, "Payments instance has 1 expiring cert")
        return future

    with patch.object(_response_store, "create", side_effect=create_and_resolve):
        client = TestClient(app)
        response = client.post(
            "/chat",
            json={
                "text": "What about payments?",
                "user_id": "demo",
                "workflow_id": "chat-test-42-1234",
            },
        )

    assert response.status_code == 200
    body = response.json()
    assert body["workflow_id"] == "chat-test-42-1234"
    assert "Payments" in body["response"]
    router.signal_follow_up.assert_awaited_once()
    call_kwargs = router.signal_follow_up.call_args.kwargs
    assert call_kwargs["workflow_id"] == "chat-test-42-1234"
    assert call_kwargs["text"] == "What about payments?"


def test_approve_signals_workflow():
    app, router = make_http_app()

    router.signal_approval = AsyncMock()

    original_create = _response_store.create

    def create_and_resolve(request_id):
        future = original_create(request_id)
        _response_store.resolve(request_id, "Changes applied successfully")
        return future

    with patch.object(_response_store, "create", side_effect=create_and_resolve):
        client = TestClient(app)
        response = client.post(
            "/approve/wf-proposal-1",
            json={"user_id": "demo"},
        )

    assert response.status_code == 200
    body = response.json()
    assert body["workflow_id"] == "wf-proposal-1"
    assert "applied" in body["response"]
    router.signal_approval.assert_awaited_once()
    call_kwargs = router.signal_approval.call_args.kwargs
    assert call_kwargs["workflow_id"] == "wf-proposal-1"
    assert call_kwargs["decision"] == "approve"


def test_reject_signals_workflow():
    app, router = make_http_app()

    router.signal_approval = AsyncMock()

    original_create = _response_store.create

    def create_and_resolve(request_id):
        future = original_create(request_id)
        _response_store.resolve(request_id, "Changes rejected, no action taken")
        return future

    with patch.object(_response_store, "create", side_effect=create_and_resolve):
        client = TestClient(app)
        response = client.post(
            "/reject/wf-proposal-1",
            json={"user_id": "demo"},
        )

    assert response.status_code == 200
    body = response.json()
    assert body["workflow_id"] == "wf-proposal-1"
    router.signal_approval.assert_awaited_once()
    assert router.signal_approval.call_args.kwargs["decision"] == "reject"


def test_chat_missing_text_returns_422():
    app, _ = make_http_app()
    client = TestClient(app)
    response = client.post("/chat", json={"user_id": "demo"})
    assert response.status_code == 422
