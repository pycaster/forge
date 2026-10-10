import asyncio
from unittest.mock import AsyncMock, MagicMock

from telegram import Update
from telegram.ext import CallbackQueryHandler, MessageHandler

from gateway.config import GatewayConfig
from gateway.telegram import create_telegram_app


def make_app():
    router = MagicMock()
    router.start_chat_workflow = AsyncMock(return_value='test-run')
    router.signal_approval = AsyncMock()
    config = GatewayConfig(_env_file=None, channel='telegram',
                           default_app={"task_queue": "test", "workflow_type": "TestWorkflow"},
                           telegram_bot_token='123:TEST', telegram_allowed_users=[42])
    return create_telegram_app(config, router), router


def test_authorized_message_routes_and_unauthorized_message_does_not():
    app, router = make_app()
    handler = next(h for h in app.handlers[0] if isinstance(h, MessageHandler))
    for uid in [42, 99]:
        update = Update.de_json({'update_id': uid, 'message': {'message_id': 1, 'date': 1,
            'chat': {'id': uid, 'type': 'private'}, 'from': {'id': uid, 'is_bot': False,
            'first_name': 'Test'}, 'text': 'deployment test'}}, app.bot)
        asyncio.run(handler.callback(update, MagicMock()))
    router.start_chat_workflow.assert_awaited_once_with(chat_id=42, user_id=42,
        username=None, text='deployment test')


def test_callbacks_validate_sender_and_decision_before_signaling():
    app, router = make_app()
    handler = next(h for h in app.handlers[0] if isinstance(h, CallbackQueryHandler))
    for uid, data in [(99, 'test-run|a'), (42, 'invalid'), (42, 'test-run|x'), (42, 'test-run|a')]:
        query = MagicMock(data=data, message=None)
        query.answer = AsyncMock()
        update = MagicMock(callback_query=query, effective_user=MagicMock(id=uid))
        asyncio.run(handler.callback(update, MagicMock()))
    router.signal_approval.assert_awaited_once()
    assert router.signal_approval.call_args.kwargs['decision'] == 'approve'
    assert router.signal_approval.call_args.kwargs['workflow_id'] == 'test-run'


def test_unsupported_proposal_gets_clear_reply():
    from telegram.ext import CommandHandler

    from gateway.router import UnsupportedProposalError

    app, router = make_app()
    router.start_proposal_workflow = AsyncMock(side_effect=UnsupportedProposalError())
    handler = next(h for h in app.handlers[0] if isinstance(h, CommandHandler) and 'propose' in h.commands)
    update = MagicMock(effective_user=MagicMock(id=42), effective_chat=MagicMock(id=42))
    update.message.reply_text = AsyncMock()
    context = MagicMock(args=['reports', 'hello'])
    asyncio.run(handler.callback(update, context))
    assert 'does not support proposals' in update.message.reply_text.call_args.args[0]
