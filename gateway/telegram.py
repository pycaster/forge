"""Telegram channel adapter.

Long-polls for messages and callback button taps. Routes messages to
app workflows through the Router. Validates approval callbacks and
sends Signals through the Router.

No business logic. No model calls. No app data.
"""

from __future__ import annotations

import logging
import time

from telegram import Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from gateway.config import GatewayConfig
from gateway.router import Router, UnsupportedProposalError

logger = logging.getLogger(__name__)


def _is_allowed(user_id: int, config: GatewayConfig) -> bool:
    """Check if a user is explicitly authorized."""
    return user_id in config.telegram_allowed_users


def create_telegram_app(config: GatewayConfig, router: Router) -> Application:
    """Build the python-telegram-bot Application with handlers.

    The Application manages its own long-poll loop. The caller starts it
    with ``app.run_polling()`` or uses ``app.initialize/start/updater.start_polling``
    for manual lifecycle control.
    """

    app = Application.builder().token(config.telegram_bot_token).build()

    # ── /start command ───────────────────────────────────────────

    async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle the /start command. Greet the user."""
        if not update.effective_user or not update.message:
            return
        if not _is_allowed(update.effective_user.id, config):
            logger.warning("start: denied user %s", update.effective_user.id)
            return

        await update.message.reply_text(
            "Agent platform gateway. Send a message to start a workflow."
        )

    # ── /propose command ────────────────────────────────────────

    async def propose_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /propose <text>. Starts the configured proposal workflow, if supported."""
        if not update.effective_user or not update.message:
            return
        if not _is_allowed(update.effective_user.id, config):
            logger.warning("propose: denied user %s", update.effective_user.id)
            return

        text = " ".join(context.args) if context.args else ""
        if not text:
            await update.message.reply_text("Usage: /propose <text>")
            return

        chat_id = update.effective_chat.id  # type: ignore[union-attr]
        user_id = update.effective_user.id
        username = update.effective_user.username

        try:
            workflow_id = await router.start_proposal_workflow(
                chat_id=chat_id,
                user_id=user_id,
                username=username,
                text=text,
            )
            logger.info("propose: started workflow %s for user %s", workflow_id, user_id)
        except UnsupportedProposalError:
            await update.message.reply_text("This app does not support proposals. Send a normal message instead.")
        except Exception:
            logger.exception("propose: failed to start workflow for user %s", user_id)
            await update.message.reply_text("Something went wrong. Try again.")

    # ── Text messages ────────────────────────────────────────────

    async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Route a text message to the correct app workflow."""
        if not update.effective_user or not update.message or not update.message.text:
            return

        user_id = update.effective_user.id
        if not _is_allowed(user_id, config):
            logger.warning("message: denied user %s", user_id)
            return

        text = update.message.text
        chat_id = update.effective_chat.id  # type: ignore[union-attr]
        username = update.effective_user.username

        try:
            workflow_id = await router.start_chat_workflow(
                chat_id=chat_id,
                user_id=user_id,
                username=username,
                text=text,
            )
            logger.info("message: started workflow %s for user %s", workflow_id, user_id)
        except Exception:
            logger.exception("message: failed to start workflow for user %s", user_id)
            await update.message.reply_text("Something went wrong. Try again.")

    # ── Approval button callbacks ────────────────────────────────

    async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle an approval button tap.

        callback_data format: ``workflow_id|decision``
        """
        query = update.callback_query
        if not query or not query.data or not update.effective_user:
            return

        user_id = update.effective_user.id
        if not _is_allowed(user_id, config):
            logger.warning("callback: denied user %s", user_id)
            await query.answer("Not authorized.")
            return

        parts = query.data.split("|")
        if len(parts) != 2:
            logger.warning("callback: invalid callback_data: %s", query.data)
            await query.answer("Invalid callback.")
            return

        workflow_id, decision_code = parts
        decision = {"a": "approve", "r": "reject"}.get(decision_code)
        if not decision:
            logger.warning("callback: unknown decision code: %s", decision_code)
            await query.answer("Invalid decision.")
            return

        try:
            await router.signal_approval(
                workflow_id=workflow_id,
                decision=decision,
                user_id=user_id,
                timestamp=time.time(),
            )

            label = "Approved" if decision == "approve" else "Rejected"
            await query.answer(label)

            # Update the message to show the decision and remove buttons.
            if query.message:
                await query.message.edit_text(
                    f"{query.message.text}\n\n<b>{label}</b> by {update.effective_user.first_name}",
                    parse_mode="HTML",
                )

            logger.info(
                "callback: %s workflow=%s user=%s",
                decision,
                workflow_id,
                user_id,
            )
        except Exception:
            logger.exception("callback: failed to signal workflow %s", workflow_id)
            await query.answer("Failed to process. Try again.")

    # ── Register handlers ────────────────────────────────────────

    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("propose", propose_command))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_handler(CallbackQueryHandler(handle_callback))

    return app
