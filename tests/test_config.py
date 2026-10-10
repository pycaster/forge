
import pytest
from pydantic import ValidationError

from gateway.config import GatewayConfig


@pytest.mark.parametrize('users', [[0], [-1]])
def test_invalid_allowlist_is_rejected(users):
    """Non-positive user IDs are always rejected."""
    with pytest.raises(ValidationError):
        GatewayConfig(_env_file=None, channel='telegram',
                      default_app={"task_queue": "test", "workflow_type": "TestWorkflow"},
                      telegram_bot_token='123:TEST',
                      telegram_allowed_users=users)


def test_empty_allowlist_rejected_in_telegram_mode():
    """Telegram mode requires at least one allowed user."""
    with pytest.raises(ValidationError):
        GatewayConfig(_env_file=None, channel='telegram',
                      default_app={"task_queue": "test", "workflow_type": "TestWorkflow"},
                      telegram_bot_token='123:TEST',
                      telegram_allowed_users=[])


def test_empty_allowlist_accepted_in_http_mode():
    """HTTP mode does not require telegram_allowed_users."""
    config = GatewayConfig(_env_file=None, channel='http',
                           default_app={"task_queue": "test", "workflow_type": "TestWorkflow"})
    assert config.telegram_allowed_users == []


def test_missing_token_rejected_in_telegram_mode():
    """Telegram mode requires a bot token."""
    with pytest.raises(ValidationError):
        GatewayConfig(_env_file=None, channel='telegram',
                      default_app={"task_queue": "test", "workflow_type": "TestWorkflow"},
                      telegram_bot_token='',
                      telegram_allowed_users=[42])


def test_missing_token_accepted_in_http_mode():
    """HTTP mode does not require a telegram bot token."""
    config = GatewayConfig(_env_file=None, channel='http',
                           default_app={"task_queue": "test", "workflow_type": "TestWorkflow"})
    assert config.telegram_bot_token == ''


@pytest.mark.parametrize('value', [None, '[]'])
def test_telegram_mode_rejects_empty_allowlist_from_env(monkeypatch, tmp_path, value):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv('CHANNEL', 'telegram')
    monkeypatch.setenv('TELEGRAM_BOT_TOKEN', '123:TEST')
    monkeypatch.setenv('DEFAULT_APP', '{"task_queue":"test","workflow_type":"TestWorkflow"}')
    monkeypatch.delenv('TELEGRAM_ALLOWED_USERS', raising=False)
    if value is not None:
        monkeypatch.setenv('TELEGRAM_ALLOWED_USERS', value)
    with pytest.raises(ValidationError):
        GatewayConfig(_env_file=None)
