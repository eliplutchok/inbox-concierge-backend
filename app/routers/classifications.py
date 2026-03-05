import asyncio

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.auth import get_current_user
from app.database import get_db
from app.models.category import Category
from app.models.classification import Classification
from app.models.email_thread import EmailThread
from app.models.user import User
from app.schemas.classification import ClassificationUpdate
from app.services.feedback import learn_from_feedback

router = APIRouter(prefix="/api/classifications", tags=["classifications"])


@router.patch("/{classification_id}")
async def update_classification(
    classification_id: str,
    body: ClassificationUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    # Fetch classification with its email thread
    result = await db.execute(
        select(Classification)
        .where(Classification.id == classification_id)
        .options(selectinload(Classification.email_thread))
    )
    classification = result.scalar_one_or_none()
    if not classification:
        raise HTTPException(status_code=404, detail="Classification not found")

    # Verify ownership
    if classification.email_thread.user_id != user.id:
        raise HTTPException(status_code=403, detail="Not authorized")

    # Get old category name
    old_cat_result = await db.execute(
        select(Category).where(Category.id == classification.category_id)
    )
    old_category = old_cat_result.scalar_one_or_none()
    old_category_name = old_category.name if old_category else "Unknown"

    # Get new category name
    new_cat_result = await db.execute(
        select(Category).where(Category.id == body.category_id, Category.user_id == user.id)
    )
    new_category = new_cat_result.scalar_one_or_none()
    if not new_category:
        raise HTTPException(status_code=400, detail="Invalid category")

    # Update classification
    classification.category_id = body.category_id
    classification.is_user_corrected = True
    await db.commit()

    # Fire-and-forget feedback learning
    email_data = {
        "subject": classification.email_thread.subject,
        "sender": classification.email_thread.sender,
        "snippet": classification.email_thread.snippet,
    }

    asyncio.create_task(
        _run_feedback(str(user.id), email_data, old_category_name, new_category.name)
    )

    return {"status": "ok"}


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
    except Exception:
        pass  # Fire-and-forget: don't crash if feedback fails
