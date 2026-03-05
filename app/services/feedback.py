from openai import AsyncOpenAI

from app.config import settings

client = AsyncOpenAI(api_key=settings.openai_api_key)

SYSTEM_PROMPT = (
    "You help refine email classification rules for a specific user. Based on a "
    "correction the user made, update their preference notes to improve future "
    "classifications. Keep notes concise (max 10 bullet points). Return ONLY the "
    "updated notes as a bullet list."
)


async def learn_from_feedback(
    email: dict,
    old_category: str,
    new_category: str,
    current_notes: str | None,
) -> str:
    """Generate updated user preference notes based on a classification correction."""
    user_message = (
        f'The user moved an email from "{old_category}" to "{new_category}".\n\n'
        f"Email details:\n"
        f"- Subject: {email.get('subject', '(no subject)')}\n"
        f"- From: {email.get('sender', 'unknown')}\n"
        f"- Preview: {email.get('snippet', '')}\n\n"
        f"Current user preference notes:\n"
        f"{current_notes or 'None yet.'}\n\n"
        f"Based on this correction, generate updated preference notes that would help "
        f"classify similar emails correctly in the future. Consolidate related rules. "
        f"If notes exceed 10 bullets, merge or remove the least important ones."
    )

    response = await client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_message},
        ],
        temperature=0.3,
        max_tokens=500,
    )

    return response.choices[0].message.content.strip()
