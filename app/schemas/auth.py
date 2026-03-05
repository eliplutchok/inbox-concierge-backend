from uuid import UUID

from pydantic import BaseModel


class UserResponse(BaseModel):
    id: UUID
    email: str
    name: str | None

    model_config = {"from_attributes": True}
