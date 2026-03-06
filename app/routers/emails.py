import asyncio
import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.auth import decrypt_token, encrypt_token, get_current_user
from app.database import get_db
from app.models.category import Category
from app.models.classification import Classification
from app.models.email_thread import EmailThread
from app.models.user import User
from app.schemas.email import EmailsResponse, EmailThreadResponse
from app.services.classifier import classify_emails
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
        gmail_threads, new_token, new_expiry = await asyncio.to_thread(
            fetch_threads, access_token, refresh_token
        )
    except Exception:
        logger.exception("Failed to fetch Gmail threads")
        raise HTTPException(
            status_code=502, detail="Failed to fetch emails from Gmail. Please try re-authenticating."
        )

    # Persist refreshed token if Google auto-refreshed it
    if new_token:
        user.access_token = encrypt_token(new_token)
        if new_expiry:
            user.token_expiry = new_expiry
        await db.commit()

    # Load existing threads from DB
    result = await db.execute(
        select(EmailThread)
        .where(EmailThread.user_id == user.id)
        .options(selectinload(EmailThread.classification))
    )
    existing_threads = {t.gmail_thread_id: t for t in result.scalars().all()}

    # Upsert thread metadata and identify unclassified threads
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

        if db_thread.classification is None:
            unclassified.append(db_thread)

    # Batch flush all new threads at once
    if unclassified:
        await db.flush()

    # Classify unclassified threads
    classified_count = 0
    if unclassified:
        cat_result = await db.execute(
            select(Category).where(Category.user_id == user.id).order_by(Category.name)
        )
        categories = [
            {"name": c.name, "description": c.description, "id": str(c.id)}
            for c in cat_result.scalars().all()
        ]

        if not categories:
            raise HTTPException(status_code=400, detail="No categories configured")

        emails_for_llm = [
            {
                "gmail_thread_id": t.gmail_thread_id,
                "subject": t.subject,
                "sender": t.sender,
                "snippet": t.snippet,
                "date": str(t.date) if t.date else None,
            }
            for t in unclassified
        ]

        try:
            classification_map = await classify_emails(emails_for_llm, categories, user.prompt_notes)
        except Exception:
            logger.exception("Classification failed")
            classification_map = {}

        cat_name_to_id = {c["name"]: c["id"] for c in categories}
        for thread in unclassified:
            cat_name = classification_map.get(thread.gmail_thread_id)
            cat_id = cat_name_to_id.get(cat_name)
            if cat_id:
                db.add(
                    Classification(
                        email_thread_id=thread.id,
                        category_id=cat_id,
                    )
                )
                classified_count += 1

        await db.commit()

        for thread in unclassified:
            await db.refresh(thread, ["classification"])

    # Build response
    cat_result = await db.execute(select(Category).where(Category.user_id == user.id))
    cat_id_to_name = {str(c.id): c.name for c in cat_result.scalars().all()}

    email_responses = []
    for thread in all_db_threads:
        classification = thread.classification
        email_responses.append(
            EmailThreadResponse(
                id=thread.id,
                gmail_thread_id=thread.gmail_thread_id,
                subject=thread.subject,
                sender=thread.sender,
                snippet=thread.snippet,
                date=thread.date,
                gmail_link=build_gmail_link(thread.gmail_thread_id),
                category_id=classification.category_id if classification else None,
                category_name=(
                    cat_id_to_name.get(str(classification.category_id))
                    if classification
                    else None
                ),
                is_user_corrected=classification.is_user_corrected if classification else False,
                classification_id=classification.id if classification else None,
            )
        )

    return EmailsResponse(
        emails=email_responses,
        classified_count=classified_count,
        total_count=len(email_responses),
    )
