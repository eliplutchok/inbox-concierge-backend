import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base


class Classification(Base):
    __tablename__ = "classifications"
    __table_args__ = (UniqueConstraint("email_thread_id"),)

    email_thread_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("email_threads.id", ondelete="CASCADE"), nullable=False
    )
    category_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("categories.id", ondelete="CASCADE"), nullable=False
    )
    is_user_corrected: Mapped[bool] = mapped_column(Boolean, default=False)
    classified_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    email_thread = relationship("EmailThread", back_populates="classification")
    category = relationship("Category", back_populates="classifications")
