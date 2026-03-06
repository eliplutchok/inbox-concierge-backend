import logging

from openai import AsyncOpenAI

from app.config import settings

logger = logging.getLogger(__name__)

client = AsyncOpenAI(api_key=settings.openai_api_key)

FEEDBACK_INSTRUCTIONS = (
    "You refine email classification preferences for a specific user of Inbox Concierge, "
    "an app that sorts Gmail into custom categories.\n\n"
    "When the user corrects a classification, you analyze WHY the email belongs in "
    "the new category and produce updated preference notes. These notes guide the "
    "classifier on every future email.\n\n"
    "Guidelines:\n"
    "- Think about what makes this email belong in the target category: the topic, "
    "content type, purpose, subject patterns, or sender domain — not just who sent it\n"
    "- Prefer thematic rules (e.g. 'Investment/brokerage account notifications → FYI') "
    "over per-sender rules (e.g. 'noreply@robinhood.com → FYI')\n"
    "- Only use sender-specific rules when the sender is genuinely the distinguishing factor\n"
    "- Consolidate related rules into broader patterns when possible\n"
    "- Remove notes that contradict the latest correction\n"
    "- Return the COMPLETE updated notes — your output replaces the previous notes entirely\n"
    "- Return ONLY the bullet list, no preamble or explanation"
)

CATEGORY_CHANGE_INSTRUCTIONS = (
    "You maintain email classification preference notes for a user of Inbox Concierge, "
    "an app that sorts Gmail into custom categories.\n\n"
    "The user has just changed their categories. Some of the existing preference notes "
    "may reference categories that no longer exist, or may no longer make sense given "
    "the new category structure. Your job is to update the notes so they remain useful.\n\n"
    "Guidelines:\n"
    "- Remove notes that reference categories that no longer exist\n"
    "- If a removed category is similar to a new one, adapt the note to reference the new category\n"
    "- Keep notes that are still relevant to the new category set\n"
    "- Do not invent new preferences — only preserve or adapt existing ones\n"
    "- Return the COMPLETE updated notes — your output replaces the previous notes entirely\n"
    "- If no notes remain relevant, return exactly: None\n"
    "- Return ONLY the bullet list (or None), no preamble or explanation"
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
        f"First, consider: what about this email's content, purpose, or topic makes "
        f'it belong in "{new_category}" rather than "{old_category}"? '
        f"Use that reasoning to write a generalizable rule.\n\n"
        f"Current preference notes:\n"
        f"{current_notes or 'None yet — this is the first correction.'}\n\n"
        f"Produce the complete updated preference notes incorporating this correction."
    )

    response = await client.responses.create(
        model="gpt-4o",
        instructions=FEEDBACK_INSTRUCTIONS,
        input=user_input,
        temperature=0.3,
        max_output_tokens=1000,
        store=False,
    )

    result = (response.output_text or "").strip()
    logger.info("Updated preference notes (%d chars)", len(result))
    return result


async def adapt_notes_for_categories(
    current_notes: str | None,
    new_categories: list[dict],
) -> str | None:
    """Update preference notes after the user changes their categories.
    Removes or adapts notes that reference categories that no longer exist.
    Returns None if no notes remain relevant."""
    if not current_notes:
        return None

    cats_list = "\n".join(
        f"- {c['name']}: {c.get('description') or 'No description'}"
        for c in new_categories
    )

    user_input = (
        f"The user's new categories are:\n{cats_list}\n\n"
        f"Current preference notes (written for the old category set):\n"
        f"{current_notes}\n\n"
        f"Update these notes to work with the new categories. Remove anything "
        f"that references categories that no longer exist. Adapt notes where a "
        f"similar category exists under a new name."
    )

    response = await client.responses.create(
        model="gpt-4o",
        instructions=CATEGORY_CHANGE_INSTRUCTIONS,
        input=user_input,
        temperature=0.2,
        max_output_tokens=1000,
        store=False,
    )

    result = (response.output_text or "").strip()

    if result.lower() in ("none", "none."):
        logger.info("All preference notes pruned after category change")
        return None

    logger.info("Adapted preference notes for new categories (%d chars)", len(result))
    return result
