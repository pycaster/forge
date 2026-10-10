"""Message routing and Temporal client operations.

The router maps incoming messages to app task queues, starts workflows,
and sends approval signals. It holds the Temporal client connection.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass

from temporalio.client import Client

from gateway.config import AppRoute, GatewayConfig

logger = logging.getLogger(__name__)


# ── Signal contracts ─────────────────────────────────────────────

APPROVAL_SIGNAL_NAME = "approval"
FOLLOW_UP_SIGNAL_NAME = "follow_up"


@dataclass
class ApprovalSignal:
    """Payload sent as a Temporal Signal when the user taps approve or reject."""

    decision: str  # "approve" or "reject"
    user_id: int
    timestamp: float


@dataclass
class FollowUpSignal:
    """Payload sent when the user sends a follow-up message to a running workflow."""

    text: str
    user_id: int
    timestamp: float


# ── Chat workflow contract ───────────────────────────────────────

class UnsupportedProposalError(ValueError):
    """The selected app does not have a proposal entry point."""


@dataclass
class ChatWorkflowInput:
    """Input passed when the Gateway starts a chat workflow."""

    chat_id: int
    user_id: int
    username: str | None
    text: str


# ── Router ───────────────────────────────────────────────────────


class Router:
    """Routes messages to apps and dispatches approval signals."""

    def __init__(self, client: Client, config: GatewayConfig) -> None:
        self._client = client
        self._config = config

    def resolve_route(self, text: str) -> AppRoute:
        """Select the first matching prefix, or the configured default route."""
        for prefix, route in self._config.app_routes.items():
            if text.lower().startswith(prefix.lower()):
                return route
        return self._config.default_app

    async def start_chat_workflow(
        self,
        *,
        chat_id: int,
        user_id: int,
        username: str | None,
        text: str,
    ) -> str:
        """Start the configured chat workflow on the app task queue.

        Returns the workflow ID.
        """
        route = self.resolve_route(text)
        task_queue = route.task_queue

        # Unique per message. Includes a timestamp so retries after a
        # failed workflow don't collide with the old run.
        ts = int(time.time() * 1000)
        workflow_id = f"chat-{task_queue}-{chat_id}-{ts}"

        input = ChatWorkflowInput(
            chat_id=chat_id,
            user_id=user_id,
            username=username,
            text=text,
        )

        logger.info(
            "start_chat_workflow queue=%s workflow_id=%s user=%s",
            task_queue,
            workflow_id,
            user_id,
        )

        await self._client.start_workflow(
            route.workflow_type,
            input,
            id=workflow_id,
            task_queue=task_queue,
        )
        return workflow_id

    async def start_proposal_workflow(
        self,
        *,
        chat_id: int,
        user_id: int,
        username: str | None,
        text: str,
    ) -> str:
        """Start the configured proposal workflow, if supported.

        Returns the workflow ID.
        """
        route = self.resolve_route(text)
        task_queue = route.task_queue
        if route.proposal_workflow_type is None:
            raise UnsupportedProposalError("This app does not support proposals.")
        ts = int(time.time() * 1000)
        workflow_id = f"proposal-{task_queue}-{chat_id}-{ts}"

        input = ChatWorkflowInput(
            chat_id=chat_id,
            user_id=user_id,
            username=username,
            text=text,
        )

        logger.info(
            "start_proposal_workflow queue=%s workflow_id=%s user=%s",
            task_queue,
            workflow_id,
            user_id,
        )

        await self._client.start_workflow(
            route.proposal_workflow_type,
            input,
            id=workflow_id,
            task_queue=task_queue,
        )
        return workflow_id

    async def signal_follow_up(
        self,
        *,
        workflow_id: str,
        text: str,
        user_id: int,
    ) -> None:
        """Send a follow-up message Signal to a running workflow.

        The workflow keeps its existing state and processes the follow-up
        using context from previous steps.
        """
        signal = FollowUpSignal(
            text=text,
            user_id=user_id,
            timestamp=time.time(),
        )

        logger.info(
            "signal_follow_up workflow_id=%s user=%s",
            workflow_id,
            user_id,
        )

        handle = self._client.get_workflow_handle(workflow_id)
        await handle.signal(FOLLOW_UP_SIGNAL_NAME, signal)

    async def signal_approval(
        self,
        *,
        workflow_id: str,
        decision: str,
        user_id: int,
        timestamp: float,
    ) -> None:
        """Send an approval Signal to a waiting workflow.

        The caller must validate the user before calling this.
        """
        signal = ApprovalSignal(
            decision=decision,
            user_id=user_id,
            timestamp=timestamp,
        )

        logger.info(
            "signal_approval workflow_id=%s decision=%s user=%s",
            workflow_id,
            decision,
            user_id,
        )

        handle = self._client.get_workflow_handle(workflow_id)
        await handle.signal(APPROVAL_SIGNAL_NAME, signal)
