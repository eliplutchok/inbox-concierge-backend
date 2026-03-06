import logging

from openai import AsyncOpenAI

from app.config import settings

logger = logging.getLogger(__name__)

client = AsyncOpenAI(api_key=settings.openai_api_key)

INSTRUCTIONS = (
    "You refine email classification preferences for a specific user. "
    "When the user corrects a classification, you analyze the correction and produce "
    "an updated set of preference notes that will help future classifications.\n\n"
    "Guidelines:\n"
    "- Return the COMPLETE updated notes — your output replaces the previous notes entirely\n"
    "- Each note should be a concise bullet point describing a classification preference\n"
    "- Consolidate related or redundant rules into single bullets\n"
    "- Focus on patterns (sender domains, subject keywords, content themes) not individual emails\n"
    "- Remove notes that contradict the latest correction\n"
    "- Return ONLY the bullet list, no preamble or explanation"
)


async def learn_from_feedback(
    email: dict,
    old_category: str,
    new_category: str,
    current_notes: str | None,
) -> str:
    """Generate updated user preference notes based on a classification correction."""
    user_input = (
        f'The user moved an email from "{old_category}" to "{new_category}".\n\n'
        f"Email details:\n"
        f"- Subject: {email.get('subject', '(no subject)')}\n"
        f"- From: {email.get('sender', 'unknown')}\n"
        f"- Preview: {email.get('snippet', '')}\n\n"
        f"Current preference notes:\n"
        f"{current_notes or 'None yet — this is the first correction.'}\n\n"
        f"Produce the complete updated preference notes incorporating this correction. "
        f"Consolidate where possible but keep all meaningful rules."
    )

    response = await client.responses.create(
        model="gpt-4o",
        instructions=INSTRUCTIONS,
        input=user_input,
        temperature=0.3,
        max_output_tokens=1000,
        store=False,
    )

    result = (response.output_text or "").strip()
    logger.info("Updated preference notes (%d chars)", len(result))
    return result
