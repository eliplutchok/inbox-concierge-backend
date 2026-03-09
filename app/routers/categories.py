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

router = APIRouter(prefix="/api/categories", tags=["categories"])


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

    await db.flush()

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
