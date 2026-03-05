import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base


class EmailThread(Base):
    __tablename__ = "email_threads"
    __table_args__ = (UniqueConstraint("user_id", "gmail_thread_id"),)

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    gmail_thread_id: Mapped[str] = mapped_column(String, nullable=False)
    gmail_message_id: Mapped[str | None] = mapped_column(String, nullable=True)
    subject: Mapped[str | None] = mapped_column(String, nullable=True)
    sender: Mapped[str | None] = mapped_column(String, nullable=True)
    snippet: Mapped[str | None] = mapped_column(Text, nullable=True)
    date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    user = relationship("User", back_populates="email_threads")
    classification = relationship(
        "Classification", back_populates="email_thread", uselist=False, cascade="all, delete-orphan"
    )
