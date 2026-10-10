"""Echo app activities.

Activities do the side-effecting work. They run on the ``echo`` task
queue. The model call is an activity because it is non-deterministic.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from openai import AsyncOpenAI
from temporalio import activity

from examples.echo.config import EchoConfig

logger = logging.getLogger(__name__)


@dataclass
class RephraseInput:
    """Input for the rephrase activity."""

    text: str


@dataclass
class RephraseOutput:
    """Output from the rephrase activity."""

    original: str
    rephrased: str


def create_activities(config: EchoConfig) -> list:
    """Create echo activities bound to config."""

    client = AsyncOpenAI(base_url=config.llm_base_url, api_key=config.llm_api_key)

    @activity.defn(name="echo_rephrase")
    async def rephrase(input: RephraseInput) -> RephraseOutput:
        """Ask the model to rephrase the input text."""
        logger.info("rephrase: calling model for %d chars", len(input.text))

        response = await client.chat.completions.create(
            model=config.llm_model,
            messages=[
                {
                    "role": "system",
                    "content": "Rephrase the user's message in a different way. Keep the same meaning. Reply with only the rephrased text.",
                },
                {"role": "user", "content": input.text},
            ],
            max_tokens=256,
        )

        rephrased = response.choices[0].message.content or input.text
        logger.info("rephrase: done, %d chars", len(rephrased))
        return RephraseOutput(original=input.text, rephrased=rephrased)

    return [rephrase]
