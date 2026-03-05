from uuid import UUID

from pydantic import BaseModel


class ClassificationUpdate(BaseModel):
    category_id: UUID
