import asyncio

from openai import AsyncOpenAI

from app.config import settings

client = AsyncOpenAI(api_key=settings.openai_api_key)

SYSTEM_PROMPT = (
    "You are an email classification assistant. You will be given an email thread's "
    "metadata and must classify it into exactly one of the provided categories. "
    "Respond with ONLY the category name, nothing else."
)


def _build_user_message(
    email: dict,
    categories: list[dict],
    user_notes: str | None,
) -> str:
    cats_section = "\n".join(
        f"- {c['name']}: {c.get('description') or 'No description'}"
        for c in categories
    )

    notes_section = user_notes or "No specific preferences yet."

    return (
        f"## Categories\n{cats_section}\n\n"
        f"## User Preferences\n{notes_section}\n\n"
        f"## Email\n"
        f"Subject: {email.get('subject', '(no subject)')}\n"
        f"From: {email.get('sender', 'unknown')}\n"
        f"Preview: {email.get('snippet', '')}\n"
        f"Date: {email.get('date', 'unknown')}\n\n"
        f"Classify this email into one of the categories above."
    )


async def classify_email(
    email: dict,
    categories: list[dict],
    user_notes: str | None,
) -> str:
    """Classify a single email into one of the given categories. Returns the category name."""
    category_names = [c["name"] for c in categories]
    user_message = _build_user_message(email, categories, user_notes)

    response = await client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_message},
        ],
        temperature=0,
        max_tokens=50,
    )

    result = response.choices[0].message.content.strip()

    # Validate the response is one of the category names (case-insensitive match)
    for name in category_names:
        if result.lower() == name.lower():
            return name

    # Fallback: return the first category if LLM gives an unexpected response
    return category_names[0] if category_names else result


async def classify_emails(
    emails: list[dict],
    categories: list[dict],
    user_notes: str | None,
    max_concurrent: int = 20,
) -> dict[str, str]:
    """Classify multiple emails concurrently. Returns mapping of gmail_thread_id -> category_name."""
    semaphore = asyncio.Semaphore(max_concurrent)

    async def _classify_with_limit(email: dict) -> tuple[str, str]:
        async with semaphore:
            category = await classify_email(email, categories, user_notes)
            return email["gmail_thread_id"], category

    tasks = [_classify_with_limit(e) for e in emails]
    results = await asyncio.gather(*tasks)
    return dict(results)
