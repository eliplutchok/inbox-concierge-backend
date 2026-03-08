import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user
from app.constants import DEFAULT_CATEGORIES
from app.database import get_db
from app.models.category import Category
from app.models.email_thread import EmailThread
from app.models.user import User
from app.schemas.category import CategoriesBulkUpdate, CategoryResponse, NotesResponse, NotesUpdate
from app.services.classifier import (
    apply_classifications,
    build_category_dicts,
    build_emails_for_llm,
    classify_emails,
)
from app.services.feedback import adapt_notes_for_categories

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/categories", tags=["categories"])


async def reclassify_all(user_id: str, db: AsyncSession):
    """Reclassify all threads for a user with their current categories and notes.
    Caller is responsible for committing beforehand so category/note changes are visible."""
    user_result = await db.execute(select(User).where(User.id == user_id))
    user = user_result.scalar_one_or_none()
    if not user or not user.access_token:
        return

    cat_result = await db.execute(
        select(Category).where(Category.user_id == user_id).order_by(Category.name)
    )
    categories = build_category_dicts(cat_result.scalars().all())

    if user.prompt_notes:
        updated_notes = await adapt_notes_for_categories(
            user.prompt_notes, categories
        )
        user.prompt_notes = updated_notes

    threads_result = await db.execute(
        select(EmailThread)
        .where(EmailThread.user_id == user_id)
        .order_by(EmailThread.date.desc())
        .limit(200)
    )
    threads = threads_result.scalars().all()

    if not threads:
        await db.commit()
        return

    if not categories:
        await db.execute(
            update(EmailThread)
            .where(EmailThread.user_id == user_id)
            .values(category_id=None, is_user_corrected=False, classified_at=None)
        )
        await db.commit()
        return

    emails_for_llm = build_emails_for_llm(threads)

    classification_map = await classify_emails(
        emails_for_llm, categories, user.prompt_notes
    )

    for thread in threads:
        thread.category_id = None
        thread.is_user_corrected = False

    apply_classifications(threads, classification_map, categories)

    await db.commit()
    logger.info("Reclassified %d threads for user %s", len(threads), user_id)


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
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if not body.categories:
        raise HTTPException(status_code=400, detail="At least one category is required")

    result = await db.execute(select(Category).where(Category.user_id == user.id))
    existing = {str(c.id): c for c in result.scalars().all()}

    incoming_ids = {str(c.id) for c in body.categories if c.id}

    for cat_id, cat in existing.items():
        if cat_id not in incoming_ids:
            await db.delete(cat)

    for cat_data in body.categories:
        if cat_data.id and str(cat_data.id) in existing:
            cat = existing[str(cat_data.id)]
            cat.name = cat_data.name
            cat.description = cat_data.description
        else:
            db.add(
                Category(
                    user_id=user.id,
                    name=cat_data.name,
                    description=cat_data.description,
                )
            )

    await db.commit()

    result = await db.execute(
        select(Category).where(Category.user_id == user.id).order_by(Category.name)
    )
    return result.scalars().all()


@router.get("/notes", response_model=NotesResponse)
async def get_notes(user: User = Depends(get_current_user)):
    return NotesResponse(notes=user.prompt_notes)


@router.put("/notes", response_model=NotesResponse)
async def update_notes(
    body: NotesUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    user.prompt_notes = body.notes
    await db.commit()
    return NotesResponse(notes=user.prompt_notes)


@router.post("/reset", response_model=list[CategoryResponse])
async def reset_categories(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await db.execute(
        update(EmailThread)
        .where(EmailThread.user_id == user.id)
        .values(category_id=None, is_user_corrected=False, classified_at=None)
    )

    await db.execute(delete(Category).where(Category.user_id == user.id))

    for cat in DEFAULT_CATEGORIES:
        db.add(Category(user_id=user.id, name=cat["name"], description=cat["description"]))

    await db.commit()

    result = await db.execute(
        select(Category).where(Category.user_id == user.id).order_by(Category.name)
    )
    return result.scalars().all()
