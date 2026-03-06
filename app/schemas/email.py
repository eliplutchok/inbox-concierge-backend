from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


class EmailThreadResponse(BaseModel):
    id: UUID
    gmail_thread_id: str
    subject: str | None
    sender: str | None
    snippet: str | None
    date: datetime | None
    gmail_link: str
    category_id: UUID | None
    category_name: str | None
    is_user_corrected: bool

    model_config = {"from_attributes": True}


class EmailsResponse(BaseModel):
    emails: list[EmailThreadResponse]
    classified_count: int
    total_count: int


class EmailCategoryUpdate(BaseModel):
    category_id: UUID
