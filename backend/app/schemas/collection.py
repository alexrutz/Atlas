"""Pydantic Schemas für Collections."""

from datetime import datetime

from pydantic import BaseModel


class CollectionCreate(BaseModel):
    name: str
    description: str | None = None
    context_text: str | None = None


class CollectionUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    context_text: str | None = None


class CollectionResponse(BaseModel):
    id: int
    name: str
    description: str | None
    context_text: str | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


class CollectionWithAccess(CollectionResponse):
    can_read: bool = False
    can_write: bool = False
    document_count: int = 0


class AccessGrant(BaseModel):
    group_id: int
    can_read: bool = True
    can_write: bool = False


class AccessInfo(BaseModel):
    group_id: int
    group_name: str
    can_read: bool
    can_write: bool

    model_config = {"from_attributes": True}


class GlossaryEntryCreate(BaseModel):
    term: str
    definition: str
    abbreviation: str | None = None


class GlossaryEntryResponse(BaseModel):
    id: int
    term: str
    definition: str
    abbreviation: str | None
    created_at: datetime

    model_config = {"from_attributes": True}
