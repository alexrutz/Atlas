"""ORM model: Groups and user-group membership (iam schema)."""

from datetime import datetime, timezone

from sqlalchemy import String, DateTime, ForeignKey, Integer
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class UserGroup(Base):
    __tablename__ = "user_groups"
    __table_args__ = {"schema": "iam"}

    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("iam.users.id", ondelete="CASCADE"), primary_key=True)
    group_id: Mapped[int] = mapped_column(Integer, ForeignKey("iam.groups.id", ondelete="CASCADE"), primary_key=True)
    joined_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class Group(Base):
    __tablename__ = "groups"
    __table_args__ = {"schema": "iam"}

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    description: Mapped[str | None] = mapped_column(nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    # Relationships
    members = relationship("User", secondary="iam.user_groups", back_populates="groups")
    collection_access = relationship("GroupCollectionAccess", back_populates="group")
