"""Echo app configuration."""

from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings


class EchoConfig(BaseSettings):
    """Echo worker settings loaded from the environment."""

    model_config = {"env_prefix": "", "env_file": ".env", "env_file_encoding": "utf-8", "extra": "ignore"}

    # Temporal
    temporal_address: str = Field(default="localhost:7233")
    temporal_namespace: str = Field(default="agent")
    task_queue: str = Field(default="echo")

    # Model
    llm_base_url: str = Field(
        default="http://localhost:8000/v1",
        description="OpenAI-compatible model endpoint.",
    )
    llm_api_key: str = Field(
        default="not-needed",
        description="API key for the model endpoint.",
    )
    llm_model: str = Field(
        default="qwen35-4b",
        description="Model name served at the endpoint.",
    )

    # Approval timeout
    approval_timeout_seconds: int = Field(
        default=300,
        description="Seconds to wait for approval before expiring.",
    )
