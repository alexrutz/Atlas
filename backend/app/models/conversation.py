"""ORM models: Conversations and messages (chat schema)."""

from datetime import datetime, timezone

from sqlalchemy import String, Integer, DateTime, ForeignKey, Text, ARRAY
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class Conversation(Base):
    __tablename__ = "conversations"
    __table_args__ = {"schema": "chat"}

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("iam.users.id", ondelete="CASCADE"), nullable=False)
    title: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    # Relationships
    user = relationship("User", back_populates="conversations")
    messages = relationship("Message", back_populates="conversation", cascade="all, delete-orphan", order_by="Message.created_at")


class Message(Base):
    __tablename__ = "messages"
    __table_args__ = {"schema": "chat"}

    id: Mapped[int] = mapped_column(primary_key=True)
    conversation_id: Mapped[int] = mapped_column(Integer, ForeignKey("chat.conversations.id", ondelete="CASCADE"), nullable=False)
    role: Mapped[str] = mapped_column(String(20), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    used_collections = mapped_column(ARRAY(Integer), default=list)
    source_chunks = mapped_column(ARRAY(Integer), default=list)
    metadata_: Mapped[dict] = mapped_column("metadata", JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    # Relationships
    conversation = relationship("Conversation", back_populates="messages")


class UserSelectedCollection(Base):
    __tablename__ = "user_selected_collections"
    __table_args__ = {"schema": "chat"}

    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("iam.users.id", ondelete="CASCADE"), primary_key=True)
    collection_id: Mapped[int] = mapped_column(Integer, ForeignKey("content.collections.id", ondelete="CASCADE"), primary_key=True)
