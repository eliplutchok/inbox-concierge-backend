import logging

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user
from app.constants import DEFAULT_CATEGORIES
from app.database import get_db
from app.models.category import Category
from app.models.classification import Classification
from app.models.email_thread import EmailThread
from app.models.user import User
from app.schemas.category import CategoriesBulkUpdate, CategoryResponse
from app.services.classifier import (
    build_category_dicts,
    build_emails_for_llm,
    classify_emails,
    persist_classifications,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/categories", tags=["categories"])


async def _reclassify_all(user_id: str):
    """Background task: reclassify all threads. Deletes old classifications only
    after new ones are computed, so the user never sees an empty state."""
    from app.database import async_session

    try:
        async with async_session() as db:
            user_result = await db.execute(select(User).where(User.id == user_id))
            user = user_result.scalar_one_or_none()
            if not user or not user.access_token:
                return

            cat_result = await db.execute(
                select(Category).where(Category.user_id == user_id).order_by(Category.name)
            )
            categories = build_category_dicts(cat_result.scalars().all())

            if not categories:
                await db.execute(
                    delete(Classification).where(
                        Classification.email_thread_id.in_(
                            select(EmailThread.id).where(EmailThread.user_id == user_id)
                        )
                    )
                )
                await db.commit()
                return

            threads_result = await db.execute(
                select(EmailThread).where(EmailThread.user_id == user_id)
            )
            threads = threads_result.scalars().all()

            if not threads:
                return

            emails_for_llm = build_emails_for_llm(threads)

            classification_map = await classify_emails(
                emails_for_llm, categories, user.prompt_notes
            )

            await db.execute(
                delete(Classification).where(
                    Classification.email_thread_id.in_(
                        select(EmailThread.id).where(EmailThread.user_id == user_id)
                    )
                )
            )

            persist_classifications(db, threads, classification_map, categories)

            await db.commit()
            logger.info("Reclassified %d threads for user %s", len(threads), user_id)

    except Exception:
        logger.exception("Reclassification failed for user %s", user_id)


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

    result = await db.execute(select(Category).where(Category.user_id == user.id))
    existing = {str(c.id): c for c in result.scalars().all()}

    incoming_ids = {str(c.id) for c in body.categories if c.id}
    has_changes = False

    for cat_id, cat in existing.items():
        if cat_id not in incoming_ids:
            await db.delete(cat)
            has_changes = True

    for cat_data in body.categories:
        if cat_data.id and str(cat_data.id) in existing:
            cat = existing[str(cat_data.id)]
            if cat.name != cat_data.name or cat.description != cat_data.description:
                cat.name = cat_data.name
                cat.description = cat_data.description
                has_changes = True
        else:
            db.add(
                Category(
                    user_id=user.id,
                    name=cat_data.name,
                    description=cat_data.description,
                )
            )
            has_changes = True

    await db.commit()

    if has_changes:
        background_tasks.add_task(_reclassify_all, str(user.id))

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
    await db.execute(delete(Category).where(Category.user_id == user.id))

    for cat in DEFAULT_CATEGORIES:
        db.add(Category(user_id=user.id, name=cat["name"], description=cat["description"]))

    await db.commit()

    background_tasks.add_task(_reclassify_all, str(user.id))

    result = await db.execute(
        select(Category).where(Category.user_id == user.id).order_by(Category.name)
    )
    return result.scalars().all()
