"""Gateway Temporal activities.

These activities run on the ``gateway`` task queue. Any app workflow can
call them to send messages through the channel. The app worker never
touches the channel directly.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup
from temporalio import activity

logger = logging.getLogger(__name__)


# ── Activity inputs ──────────────────────────────────────────────


@dataclass
class SendMessageInput:
    """Input for the send_message activity."""

    chat_id: int
    text: str
    parse_mode: str | None = "HTML"


@dataclass
class SendApprovalRequestInput:
    """Input for the send_approval_request activity."""

    chat_id: int
    workflow_id: str
    proposal_id: str
    title: str
    diff: str
    rationale: str | None = None
    expire_label: str | None = None


@dataclass
class SendAlertInput:
    """Input for the send_alert activity."""

    chat_id: int
    text: str
    parse_mode: str | None = "HTML"


# ── Activity implementations ────────────────────────────────────


def create_activities(bot: Bot) -> list:
    """Create activity functions bound to a Bot instance.

    Returns a list of functions to register with the Temporal worker.
    """

    @activity.defn(name="send_message")
    async def send_message(input: SendMessageInput) -> None:
        """Send a text message to a chat."""
        logger.info("send_message chat_id=%s len=%d", input.chat_id, len(input.text))
        await bot.send_message(
            chat_id=input.chat_id,
            text=input.text,
            parse_mode=input.parse_mode,
        )

    @activity.defn(name="send_approval_request")
    async def send_approval_request(input: SendApprovalRequestInput) -> None:
        """Send a proposal with approve and reject buttons."""
        parts = [f"<b>{input.title}</b>", "", f"<pre>{input.diff}</pre>"]
        if input.rationale:
            parts.extend(["", input.rationale])
        if input.expire_label:
            parts.extend(["", f"Expires: {input.expire_label}"])
        text = "\n".join(parts)

        # callback_data: workflow_id|decision
        # Telegram limits callback_data to 64 bytes. The proposal ID is
        # not needed in the callback — the workflow ID is sufficient to
        # route the signal. The proposal ID is only for display.
        approve_data = f"{input.workflow_id}|a"
        reject_data = f"{input.workflow_id}|r"

        keyboard = InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton("Approve", callback_data=approve_data),
                    InlineKeyboardButton("Reject", callback_data=reject_data),
                ]
            ]
        )

        logger.info(
            "send_approval_request chat_id=%s workflow=%s proposal=%s",
            input.chat_id,
            input.workflow_id,
            input.proposal_id,
        )
        await bot.send_message(
            chat_id=input.chat_id,
            text=text,
            parse_mode="HTML",
            reply_markup=keyboard,
        )

    @activity.defn(name="send_alert")
    async def send_alert(input: SendAlertInput) -> None:
        """Send an alert message to a chat."""
        logger.info("send_alert chat_id=%s len=%d", input.chat_id, len(input.text))
        await bot.send_message(
            chat_id=input.chat_id,
            text=input.text,
            parse_mode=input.parse_mode,
        )

    return [send_message, send_approval_request, send_alert]
