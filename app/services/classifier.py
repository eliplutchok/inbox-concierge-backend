import asyncio
import logging
from datetime import datetime, timezone
from typing import Any, Sequence

from openai import AsyncOpenAI

from app.config import settings

logger = logging.getLogger(__name__)

client = AsyncOpenAI(api_key=settings.openai_api_key)

INSTRUCTIONS = (
    "You are an email classification assistant for Inbox Concierge, an app that "
    "organizes a user's Gmail inbox into custom categories.\n\n"
    "You will receive:\n"
    "1. The user's categories with descriptions\n"
    "2. Preference notes learned from the user's past corrections (if any)\n"
    "3. An email's metadata (subject, sender, preview, date)\n\n"
    "Your job is to classify the email into exactly one of the provided categories. "
    "The preference notes reflect patterns the user cares about — always respect them "
    "over general intuition when they apply.\n\n"
    "Respond with ONLY the category name, nothing else."
)


def _build_input(
    email: dict,
    categories: list[dict],
    user_notes: str | None,
) -> str:
    cats_section = "\n".join(
        f"- {c['name']}: {c.get('description') or 'No description'}"
        for c in categories
    )

    notes_section = user_notes or "No preference notes yet."

    return (
        f"## Categories\n{cats_section}\n\n"
        f"## User Preference Notes\n"
        f"These notes were learned from the user's past corrections. "
        f"They indicate how this specific user wants their emails sorted:\n"
        f"{notes_section}\n\n"
        f"## Email to Classify\n"
        f"Subject: {email.get('subject', '(no subject)')}\n"
        f"From: {email.get('sender', 'unknown')}\n"
        f"Preview: {email.get('snippet', '')}\n"
        f"Date: {email.get('date', 'unknown')}\n\n"
        f"Which category does this email belong to?"
    )


async def classify_email(
    email: dict,
    categories: list[dict],
    user_notes: str | None,
) -> str:
    """Classify a single email into one of the given categories. Returns the category name."""
    category_names = [c["name"] for c in categories]

    response = await client.responses.create(
        model="gpt-4.1-mini",
        instructions=INSTRUCTIONS,
        input=_build_input(email, categories, user_notes),
        temperature=0,
        max_output_tokens=50,
        store=False,
    )

    result = (response.output_text or "").strip()

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


def apply_classifications(
    threads: Sequence[Any],
    classification_map: dict[str, str],
    categories: list[dict],
) -> int:
    """Set category_id on threads from a classification_map. Returns count classified."""
    cat_name_to_id = {c["name"]: c["id"] for c in categories}
    now = datetime.now(timezone.utc)
    count = 0
    for thread in threads:
        cat_name = classification_map.get(thread.gmail_thread_id)
        cat_id = cat_name_to_id.get(cat_name)
        if cat_id:
            thread.category_id = cat_id
            thread.classified_at = now
            count += 1
    return count
