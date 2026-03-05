import asyncio

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user
from app.config import settings
from app.constants import DEFAULT_CATEGORIES
from app.database import get_db
from app.models.category import Category
from app.models.classification import Classification
from app.models.email_thread import EmailThread
from app.models.user import User
from app.schemas.category import CategoriesBulkUpdate, CategoryResponse
from app.services.classifier import classify_emails

router = APIRouter(prefix="/api/categories", tags=["categories"])


async def _reclassify_all(user_id: str, db_url: str):
    """Background task: delete all classifications and reclassify everything."""
    from app.database import async_session

    async with async_session() as db:
        user_result = await db.execute(select(User).where(User.id == user_id))
        user = user_result.scalar_one_or_none()
        if not user or not user.access_token:
            return

        from app.auth import decrypt_token

        # Delete existing classifications
        threads_result = await db.execute(
            select(EmailThread).where(EmailThread.user_id == user_id)
        )
        thread_ids = [t.id for t in threads_result.scalars().all()]
        if thread_ids:
            await db.execute(
                delete(Classification).where(Classification.email_thread_id.in_(thread_ids))
            )

        # Fetch categories
        cat_result = await db.execute(
            select(Category).where(Category.user_id == user_id).order_by(Category.name)
        )
        categories = [{"name": c.name, "description": c.description, "id": str(c.id)}
                       for c in cat_result.scalars().all()]

        if not categories:
            await db.commit()
            return

        # Fetch all threads
        threads_result = await db.execute(
            select(EmailThread).where(EmailThread.user_id == user_id)
        )
        threads = threads_result.scalars().all()

        emails_for_llm = [
            {
                "gmail_thread_id": t.gmail_thread_id,
                "subject": t.subject,
                "sender": t.sender,
                "snippet": t.snippet,
                "date": str(t.date) if t.date else None,
            }
            for t in threads
        ]

        classification_map = await classify_emails(emails_for_llm, categories, user.prompt_notes)

        cat_name_to_id = {c["name"]: c["id"] for c in categories}
        for thread in threads:
            cat_name = classification_map.get(thread.gmail_thread_id)
            cat_id = cat_name_to_id.get(cat_name)
            if cat_id:
                db.add(Classification(
                    email_thread_id=thread.id,
                    category_id=cat_id,
                ))

        await db.commit()


@router.get("", response_model=list[CategoryResponse])
async def list_categories(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Category).where(Category.user_id == user.id).order_by(Category.name)
    )
    return result.scalars().all()


@router.put("", response_model=list[CategoryResponse])
async def bulk_update_categories(
    body: CategoriesBulkUpdate,
    background_tasks: BackgroundTasks,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if not body.categories:
        raise HTTPException(status_code=400, detail="At least one category is required")

    # Fetch existing categories
    result = await db.execute(
        select(Category).where(Category.user_id == user.id)
    )
    existing = {str(c.id): c for c in result.scalars().all()}

    # Determine changes
    incoming_ids = {str(c.id) for c in body.categories if c.id}
    has_changes = False

    # Delete categories not in the incoming list
    for cat_id, cat in existing.items():
        if cat_id not in incoming_ids:
            await db.delete(cat)
            has_changes = True

    # Update existing / create new
    for cat_data in body.categories:
        if cat_data.id and str(cat_data.id) in existing:
            cat = existing[str(cat_data.id)]
            if cat.name != cat_data.name or cat.description != cat_data.description:
                cat.name = cat_data.name
                cat.description = cat_data.description
                has_changes = True
        else:
            db.add(Category(
                user_id=user.id,
                name=cat_data.name,
                description=cat_data.description,
            ))
            has_changes = True

    await db.commit()

    if has_changes:
        background_tasks.add_task(_reclassify_all, str(user.id), settings.database_url)

    result = await db.execute(
        select(Category).where(Category.user_id == user.id).order_by(Category.name)
    )
    return result.scalars().all()


@router.post("/reset", response_model=list[CategoryResponse])
async def reset_categories(
    background_tasks: BackgroundTasks,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    # Delete all existing categories (cascades to classifications)
    await db.execute(delete(Category).where(Category.user_id == user.id))

    # Re-seed defaults
    for cat in DEFAULT_CATEGORIES:
        db.add(Category(user_id=user.id, name=cat["name"], description=cat["description"]))

    await db.commit()

    background_tasks.add_task(_reclassify_all, str(user.id), settings.database_url)

    result = await db.execute(
        select(Category).where(Category.user_id == user.id).order_by(Category.name)
    )
    return result.scalars().all()
