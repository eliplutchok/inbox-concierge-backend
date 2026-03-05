from uuid import UUID

from pydantic import BaseModel


class CategoryBase(BaseModel):
    name: str
    description: str | None = None


class CategoryResponse(CategoryBase):
    id: UUID

    model_config = {"from_attributes": True}


class CategoryUpdate(BaseModel):
    """Used in bulk update — may include existing categories (with id) or new ones (without)."""
    id: UUID | None = None
    name: str
    description: str | None = None


class CategoriesBulkUpdate(BaseModel):
    categories: list[CategoryUpdate]
