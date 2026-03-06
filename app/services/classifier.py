import asyncio
import logging
from typing import Any, Sequence

from openai import AsyncOpenAI
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.classification import Classification

logger = logging.getLogger(__name__)

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

    result = (response.choices[0].message.content or "").strip()

    for name in category_names:
        if result.lower() == name.lower():
            return name

    logger.warning("LLM returned unexpected category '%s', falling back to first", result)
    return category_names[0] if category_names else result


async def classify_emails(
    emails: list[dict],
    categories: list[dict],
    user_notes: str | None,
    max_concurrent: int = 20,
) -> dict[str, str]:
    """Classify multiple emails concurrently. Returns mapping of gmail_thread_id -> category_name."""
    semaphore = asyncio.Semaphore(max_concurrent)

    async def _classify_with_limit(email: dict) -> tuple[str, str | None]:
        async with semaphore:
            try:
                category = await classify_email(email, categories, user_notes)
                return email["gmail_thread_id"], category
            except Exception:
                logger.exception("Failed to classify email %s", email.get("gmail_thread_id"))
                return email["gmail_thread_id"], None

    tasks = [_classify_with_limit(e) for e in emails]
    results = await asyncio.gather(*tasks)
    return {tid: cat for tid, cat in results if cat is not None}


def build_category_dicts(categories: Sequence[Any]) -> list[dict]:
    """Convert ORM Category objects to dicts for classify_emails."""
    return [
        {"name": c.name, "description": c.description, "id": str(c.id)}
        for c in categories
    ]


def build_emails_for_llm(threads: Sequence[Any]) -> list[dict]:
    """Convert ORM EmailThread objects to dicts for classify_emails."""
    return [
        {
            "gmail_thread_id": t.gmail_thread_id,
            "subject": t.subject,
            "sender": t.sender,
            "snippet": t.snippet,
            "date": str(t.date) if t.date else None,
        }
        for t in threads
    ]


def persist_classifications(
    db: AsyncSession,
    threads: Sequence[Any],
    classification_map: dict[str, str],
    categories: list[dict],
) -> int:
    """Create Classification records from a classification_map. Returns count created."""
    cat_name_to_id = {c["name"]: c["id"] for c in categories}
    count = 0
    for thread in threads:
        cat_name = classification_map.get(thread.gmail_thread_id)
        cat_id = cat_name_to_id.get(cat_name)
        if cat_id:
            db.add(Classification(email_thread_id=thread.id, category_id=cat_id))
            count += 1
    return count
