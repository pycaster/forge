import asyncio
import json
from unittest.mock import AsyncMock, MagicMock

import pytest
from pydantic import ValidationError

from gateway.config import GatewayConfig
from gateway.router import Router, UnsupportedProposalError


def config(**kwargs):
    kwargs.setdefault('default_app', {'task_queue': 'default', 'workflow_type': 'DefaultWorkflow'})
    kwargs.setdefault('channel', 'http')
    return GatewayConfig(_env_file=None, **kwargs)


def request(router, proposal=False, text='reports roster'):
    method = router.start_proposal_workflow if proposal else router.start_chat_workflow
    return asyncio.run(method(chat_id=42, user_id=42, username=None, text=text))


def test_explicit_type_and_queue_are_sent_with_original_input():
    client = MagicMock(start_workflow=AsyncMock())
    router = Router(client, config(app_routes={'reports': {'task_queue': 'reports-worker', 'workflow_type': 'ReportSummary'}}))
    request(router, text='REPORTS roster')
    args = client.start_workflow.call_args
    assert args.args[0] == 'ReportSummary'
    assert args.kwargs['task_queue'] == 'reports-worker'
    assert args.args[1].text == 'REPORTS roster'
    assert args.args[1].user_id == 42


def test_explicit_default_and_custom_proposals():
    client = MagicMock(start_workflow=AsyncMock())
    router = Router(client, config(default_app={'task_queue': 'app', 'workflow_type': 'AppChat', 'proposal_workflow_type': 'AppProposal'}))
    request(router)
    assert client.start_workflow.call_args.args[0] == 'AppChat'
    request(router, proposal=True)
    assert client.start_workflow.call_args.args[0] == 'AppProposal'


def test_unsupported_proposal_does_not_start_workflow():
    client = MagicMock(start_workflow=AsyncMock())
    router = Router(client, config(default_app={'task_queue': 'app', 'workflow_type': 'Summary'}))
    with pytest.raises(UnsupportedProposalError):
        request(router, proposal=True)
    client.start_workflow.assert_not_called()


@pytest.mark.parametrize('route', [
    'echo', '', ' ', {'task_queue': 'app'}, {'task_queue': '', 'workflow_type': 'Summary'},
    {'task_queue': 'app', 'workflow_type': ' '},
    {'task_queue': 'app', 'workflow_type': 'Summary', 'proposal_workflow_type': ''},
    {'task_queue': 'app', 'workflow_type': 'Summary', 'typo': 'oops'},
])
def test_invalid_routes_fail_at_startup(route):
    with pytest.raises(ValidationError):
        config(app_routes={'app': route})


def test_environment_accepts_explicit_default(monkeypatch):
    route = {'task_queue': 'app', 'workflow_type': 'Summary'}
    monkeypatch.setenv('APP_ROUTES', json.dumps({'app': route}))
    monkeypatch.setenv('DEFAULT_APP', json.dumps(route))
    settings = GatewayConfig(_env_file=None, channel='http')
    router = Router(MagicMock(), settings)
    assert router.resolve_route('app hello').workflow_type == 'Summary'
    assert router.resolve_route('other').task_queue == 'app'


def test_default_queue_string_is_rejected():
    with pytest.raises(ValidationError):
        config(default_app='echo')


# ── Follow-up signal ─────────────────────────────────────────────


def test_follow_up_signal_sends_to_correct_workflow():
    handle = MagicMock(signal=AsyncMock())
    client = MagicMock(get_workflow_handle=MagicMock(return_value=handle))
    router = Router(client, config())
    asyncio.run(router.signal_follow_up(
        workflow_id='chat-test-42-1234',
        text='What about payments?',
        user_id=42,
    ))
    client.get_workflow_handle.assert_called_once_with('chat-test-42-1234')
    handle.signal.assert_awaited_once()
    signal_name = handle.signal.call_args.args[0]
    signal_payload = handle.signal.call_args.args[1]
    assert signal_name == 'follow_up'
    assert signal_payload.text == 'What about payments?'
    assert signal_payload.user_id == 42


def test_follow_up_signal_includes_timestamp():
    handle = MagicMock(signal=AsyncMock())
    client = MagicMock(get_workflow_handle=MagicMock(return_value=handle))
    router = Router(client, config())
    asyncio.run(router.signal_follow_up(
        workflow_id='wf-1',
        text='hello',
        user_id=1,
    ))
    signal_payload = handle.signal.call_args.args[1]
    assert isinstance(signal_payload.timestamp, float)
    assert signal_payload.timestamp > 0
