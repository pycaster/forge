"""Echo app workflows.

Two workflows that demonstrate the platform:

1. ChatWorkflow — receives text, rephrases it with the model, and
   sends the reply. No approval needed (read-only).

2. ProposalWorkflow — rephrases the text, sends a proposal with
   approve/reject buttons, waits for a signal or timer, and acts
   on the decision. Demonstrates the full approval loop.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import timedelta

from temporalio import workflow

# Activity imports must use string names for determinism.
# The actual implementations run in the worker process.
with workflow.unsafe.imports_passed_through():
    from examples.echo.activities import RephraseInput, RephraseOutput
    from gateway.activities import SendApprovalRequestInput, SendMessageInput
    from gateway.router import ApprovalSignal, FollowUpSignal

logger = logging.getLogger(__name__)


@dataclass
class ChatWorkflowInput:
    """Input for the ChatWorkflow. Matches gateway.router.ChatWorkflowInput."""

    chat_id: int
    user_id: int
    username: str | None
    text: str


# ── ChatWorkflow ─────────────────────────────────────────────────


@workflow.defn(name="ChatWorkflow")
class ChatWorkflow:
    """Rephrase a message and send the reply, then wait for follow-ups.

    The workflow stays alive after the initial reply. Follow-up messages
    arrive as signals. The workflow processes each one and sends a reply.
    After a period of inactivity the workflow completes.
    """

    IDLE_TIMEOUT_SECONDS = 300

    def __init__(self) -> None:
        self._follow_up: FollowUpSignal | None = None

    @workflow.signal(name="follow_up")
    async def on_follow_up(self, signal: FollowUpSignal) -> None:
        """Receive a follow-up message from the gateway."""
        self._follow_up = signal

    @workflow.run
    async def run(self, input: ChatWorkflowInput) -> str:
        # Step 1: rephrase the initial message.
        result = await workflow.execute_activity(
            "echo_rephrase",
            RephraseInput(text=input.text),
            task_queue="echo",
            result_type=RephraseOutput,
            start_to_close_timeout=timedelta(seconds=30),
        )

        reply = f"<b>Echo:</b> {result.rephrased}"
        await workflow.execute_activity(
            "send_message",
            SendMessageInput(chat_id=input.chat_id, text=reply),
            task_queue="gateway",
            start_to_close_timeout=timedelta(seconds=15),
        )

        # Step 2: wait for follow-up messages until idle timeout.
        while True:
            self._follow_up = None
            try:
                await workflow.wait_condition(
                    lambda: self._follow_up is not None,
                    timeout=timedelta(seconds=self.IDLE_TIMEOUT_SECONDS),
                )
            except TimeoutError:
                # No follow-up within the timeout. End the conversation.
                return result.rephrased

            # Process the follow-up.
            follow_up = self._follow_up
            assert follow_up is not None

            result = await workflow.execute_activity(
                "echo_rephrase",
                RephraseInput(text=follow_up.text),
                task_queue="echo",
                result_type=RephraseOutput,
                start_to_close_timeout=timedelta(seconds=30),
            )

            reply = f"<b>Echo:</b> {result.rephrased}"
            await workflow.execute_activity(
                "send_message",
                SendMessageInput(chat_id=input.chat_id, text=reply),
                task_queue="gateway",
                start_to_close_timeout=timedelta(seconds=15),
            )


# ── ProposalWorkflow ─────────────────────────────────────────────


@workflow.defn(name="ProposalWorkflow")
class ProposalWorkflow:
    """Rephrase text, propose the change, and wait for approval.

    Demonstrates the three terminal branches:
    - Approved: apply and confirm.
    - Rejected: acknowledge with no side effect.
    - Expired: timer fires, fail-closed, no side effect.
    """

    def __init__(self) -> None:
        self._approval: ApprovalSignal | None = None

    @workflow.signal(name="approval")
    async def on_approval(self, signal: ApprovalSignal) -> None:
        """Receive the approval decision from the Gateway."""
        self._approval = signal

    @workflow.run
    async def run(self, input: ChatWorkflowInput) -> str:
        # Step 1: rephrase with the model.
        result = await workflow.execute_activity(
            "echo_rephrase",
            RephraseInput(text=input.text),
            task_queue="echo",
            result_type=RephraseOutput,
            start_to_close_timeout=timedelta(seconds=30),
        )

        # Step 2: send an approval request through the Gateway.
        proposal_id = f"echo-{workflow.info().workflow_id}"
        await workflow.execute_activity(
            "send_approval_request",
            SendApprovalRequestInput(
                chat_id=input.chat_id,
                workflow_id=workflow.info().workflow_id,
                proposal_id=proposal_id,
                title="Echo proposal",
                diff=f"Original: {result.original}\nRephrased: {result.rephrased}",
                rationale="The model rephrased your message. Approve to confirm.",
                expire_label="5 minutes",
            ),
            task_queue="gateway",
            start_to_close_timeout=timedelta(seconds=15),
        )

        # Step 3: wait for approval signal or timeout.
        # This is the durable wait. It survives restarts.
        try:
            await workflow.wait_condition(
                lambda: self._approval is not None,
                timeout=timedelta(seconds=300),
            )
        except TimeoutError:
            # Timer won. Fail-closed. No side effect.
            await workflow.execute_activity(
                "send_message",
                SendMessageInput(
                    chat_id=input.chat_id,
                    text="Proposal expired. No changes made.",
                ),
                task_queue="gateway",
                start_to_close_timeout=timedelta(seconds=15),
            )
            return "expired"

        # Step 4: act on the decision.
        assert self._approval is not None
        if self._approval.decision == "approve":
            # In a real app, this is where the side effect happens.
            await workflow.execute_activity(
                "send_message",
                SendMessageInput(
                    chat_id=input.chat_id,
                    text=f"Approved. Applied: {result.rephrased}",
                ),
                task_queue="gateway",
                start_to_close_timeout=timedelta(seconds=15),
            )
            return "approved"
        else:
            await workflow.execute_activity(
                "send_message",
                SendMessageInput(
                    chat_id=input.chat_id,
                    text="Rejected. No changes made.",
                ),
                task_queue="gateway",
                start_to_close_timeout=timedelta(seconds=15),
            )
            return "rejected"
