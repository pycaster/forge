"""Gateway configuration.

All settings come from environment variables or a .env file.
No interactive setup. No hidden defaults.
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, PositiveInt, field_validator
from pydantic_settings import BaseSettings


class Channel(str, Enum):
    """Supported channel adapters."""

    http = "http"
    telegram = "telegram"


class AppRoute(BaseModel):
    """An app entry point. Omitted proposal_workflow_type disables proposals."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    task_queue: str = Field(min_length=1)
    workflow_type: str = Field(min_length=1)
    proposal_workflow_type: str | None = Field(default=None, min_length=1)


class GatewayConfig(BaseSettings):
    """Gateway settings loaded from the environment."""

    model_config = {"env_prefix": "", "env_file": ".env", "env_file_encoding": "utf-8", "extra": "ignore"}

    # Channel
    channel: Channel = Field(
        default=Channel.http,
        description="Channel adapter: 'http' or 'telegram'.",
    )

    # Temporal
    temporal_address: str = Field(
        default="localhost:7233",
        description="Temporal frontend gRPC address.",
    )
    temporal_namespace: str = Field(
        default="agent",
        description="Temporal namespace for all platform workflows.",
    )
    gateway_task_queue: str = Field(
        default="gateway",
        description="Task queue name for Gateway activities.",
    )

    # HTTP channel
    gateway_port: int = Field(
        default=8080,
        description="Port for the HTTP channel adapter.",
    )

    # Telegram channel (only required when channel=telegram)
    telegram_bot_token: str = Field(
        default="",
        description="Bot token from BotFather. Required when channel=telegram.",
    )
    telegram_allowed_users: list[PositiveInt] = Field(
        default_factory=list,
        description="Telegram user IDs allowed to interact. Required when channel=telegram.",
    )

    # LLM (used by the intent classifier)
    llm_base_url: str = Field(
        default="",
        description="OpenAI-compatible base URL for intent classification.",
    )
    llm_api_key: str = Field(
        default="",
        description="API key for the LLM endpoint.",
    )
    llm_model: str = Field(
        default="",
        description="Model name for intent classification.",
    )

    default_app: AppRoute = Field(
        default_factory=lambda: AppRoute(task_queue="echo", workflow_type="ChatWorkflow", proposal_workflow_type="ProposalWorkflow"),
        description="Default workflow route for unmatched text.",
    )
    app_routes: dict[str, AppRoute] = Field(
        default_factory=dict, description="Text prefix to explicit workflow route.")

    @field_validator("app_routes")
    @classmethod
    def validate_routes(cls, routes):
        seen = set()
        for prefix in routes:
            if not prefix.strip() or prefix.lower() in seen:
                raise ValueError("Route prefixes must be nonempty and unique ignoring case")
            seen.add(prefix.lower())
        return routes

    @field_validator("telegram_bot_token")
    @classmethod
    def validate_telegram_token(cls, v, info):
        if info.data.get("channel") == Channel.telegram and not v:
            raise ValueError("telegram_bot_token is required when channel=telegram")
        return v

    @field_validator("telegram_allowed_users")
    @classmethod
    def validate_telegram_users(cls, v, info):
        if info.data.get("channel") == Channel.telegram and not v:
            raise ValueError("telegram_allowed_users must be nonempty when channel=telegram")
        return v
