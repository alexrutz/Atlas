"""ORM model: Collections and access control (content schema)."""

from datetime import datetime, timezone

from sqlalchemy import String, Boolean, DateTime, ForeignKey, Integer, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class Collection(Base):
    __tablename__ = "collections"
    __table_args__ = {"schema": "content"}

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200), unique=True, nullable=False)
    description: Mapped[str | None] = mapped_column(nullable=True)
    context_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[int | None] = mapped_column(Integer, ForeignKey("iam.users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    # Relationships
    documents = relationship("Document", back_populates="collection", cascade="all, delete-orphan")
    group_access = relationship("GroupCollectionAccess", back_populates="collection", cascade="all, delete-orphan")


class GroupCollectionAccess(Base):
    __tablename__ = "group_collection_access"
    __table_args__ = {"schema": "content"}

    group_id: Mapped[int] = mapped_column(Integer, ForeignKey("iam.groups.id", ondelete="CASCADE"), primary_key=True)
    collection_id: Mapped[int] = mapped_column(Integer, ForeignKey("content.collections.id", ondelete="CASCADE"), primary_key=True)
    can_read: Mapped[bool] = mapped_column(Boolean, default=True)
    can_write: Mapped[bool] = mapped_column(Boolean, default=False)
    granted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    granted_by: Mapped[int | None] = mapped_column(Integer, ForeignKey("iam.users.id"), nullable=True)

    # Relationships
    group = relationship("Group", back_populates="collection_access")
    collection = relationship("Collection", back_populates="group_access")
