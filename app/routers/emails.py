import asyncio
import logging
from time import time

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import decrypt_token, encrypt_token, get_current_user
from app.database import get_db
from app.models.category import Category
from app.models.email_thread import EmailThread
from app.models.user import User
from app.schemas.email import EmailCategoryUpdate, EmailsResponse, EmailThreadResponse
from app.services.classifier import (
    apply_classifications,
    build_category_dicts,
    build_emails_for_llm,
    classify_emails,
)
from app.services.feedback import learn_from_feedback
from app.services.gmail import build_gmail_link, fetch_threads

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/emails", tags=["emails"])


@router.get("", response_model=EmailsResponse)
async def get_emails(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if not user.access_token or not user.refresh_token:
        raise HTTPException(status_code=400, detail="Gmail not connected")

    access_token = decrypt_token(user.access_token)
    refresh_token = decrypt_token(user.refresh_token)

    try:
        start_time = time()
        gmail_threads, new_token, new_expiry = await asyncio.to_thread(
            fetch_threads, access_token, refresh_token
        )
        logger.info("Fetched %d threads in %.1fs", len(gmail_threads), time() - start_time)
    except Exception:
        logger.exception("Failed to fetch Gmail threads")
        raise HTTPException(
            status_code=502, detail="Failed to fetch emails from Gmail. Please try re-authenticating."
        )

    if new_token:
        user.access_token = encrypt_token(new_token)
        if new_expiry:
            user.token_expiry = new_expiry
        await db.commit()

    result = await db.execute(
        select(EmailThread).where(EmailThread.user_id == user.id)
    )
    existing_threads = {t.gmail_thread_id: t for t in result.scalars().all()}

    unclassified = []
    all_db_threads = []

    for gt in gmail_threads:
        thread_id = gt["gmail_thread_id"]
        if thread_id in existing_threads:
            db_thread = existing_threads[thread_id]
        else:
            db_thread = EmailThread(
                user_id=user.id,
                gmail_thread_id=thread_id,
                gmail_message_id=gt.get("gmail_message_id"),
                subject=gt.get("subject"),
                sender=gt.get("sender"),
                snippet=gt.get("snippet"),
                date=gt.get("date"),
            )
            db.add(db_thread)

        all_db_threads.append(db_thread)

        if db_thread.category_id is None:
            unclassified.append(db_thread)

    if unclassified:
        await db.flush()

    classified_count = 0
    if unclassified:
        cat_result = await db.execute(
            select(Category).where(Category.user_id == user.id).order_by(Category.name)
        )
        categories = build_category_dicts(cat_result.scalars().all())

        if not categories:
            raise HTTPException(status_code=400, detail="No categories configured")

        emails_for_llm = build_emails_for_llm(unclassified)

        try:
            classification_map = await classify_emails(emails_for_llm, categories, user.prompt_notes)
        except Exception:
            logger.exception("Classification failed")
            classification_map = {}

        classified_count = apply_classifications(unclassified, classification_map, categories)

    await db.commit()

    cat_result = await db.execute(select(Category).where(Category.user_id == user.id))
    cat_id_to_name = {str(c.id): c.name for c in cat_result.scalars().all()}

    email_responses = [
        EmailThreadResponse(
            id=thread.id,
            gmail_thread_id=thread.gmail_thread_id,
            subject=thread.subject,
            sender=thread.sender,
            snippet=thread.snippet,
            date=thread.date,
            gmail_link=build_gmail_link(thread.gmail_thread_id),
            category_id=thread.category_id,
            category_name=cat_id_to_name.get(str(thread.category_id)) if thread.category_id else None,
            is_user_corrected=thread.is_user_corrected,
            classified_at=thread.classified_at,
        )
        for thread in all_db_threads
    ]

    return EmailsResponse(
        emails=email_responses,
        classified_count=classified_count,
        total_count=len(email_responses),
    )


async def _run_feedback(user_id: str, email_data: dict, old_cat: str, new_cat: str):
    """Run feedback learning and update user's prompt notes."""
    from app.database import async_session

    try:
        async with async_session() as db:
            result = await db.execute(select(User).where(User.id == user_id))
            user = result.scalar_one_or_none()
            if not user:
                return

            updated_notes = await learn_from_feedback(
                email_data, old_cat, new_cat, user.prompt_notes
            )
            user.prompt_notes = updated_notes
            await db.commit()
            logger.info("Updated prompt notes for user %s", user_id)
    except Exception:
        logger.exception("Feedback learning failed for user %s", user_id)


@router.patch("/{email_id}/category")
async def update_email_category(
    email_id: str,
    body: EmailCategoryUpdate,
    background_tasks: BackgroundTasks,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(EmailThread).where(EmailThread.id == email_id, EmailThread.user_id == user.id)
    )
    thread = result.scalar_one_or_none()
    if not thread:
        raise HTTPException(status_code=404, detail="Email not found")

    old_cat_result = await db.execute(
        select(Category).where(Category.id == thread.category_id)
    )
    old_category = old_cat_result.scalar_one_or_none()
    old_category_name = old_category.name if old_category else "Unknown"

    new_cat_result = await db.execute(
        select(Category).where(Category.id == body.category_id, Category.user_id == user.id)
    )
    new_category = new_cat_result.scalar_one_or_none()
    if not new_category:
        raise HTTPException(status_code=400, detail="Invalid category")

    thread.category_id = body.category_id
    thread.is_user_corrected = True
    await db.commit()

    email_data = {
        "subject": thread.subject,
        "sender": thread.sender,
        "snippet": thread.snippet,
    }

    background_tasks.add_task(
        _run_feedback, str(user.id), email_data, old_category_name, new_category.name
    )

    return {"status": "ok"}
