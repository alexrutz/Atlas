"""
Pydantic schemas - Request/response models for the API.

These define the shape of data going in and out of API endpoints.
Pydantic validates the data automatically (e.g. missing fields, wrong types).
"""

from datetime import datetime

from pydantic import BaseModel


# =============================================================================
# Auth
# =============================================================================

class LoginRequest(BaseModel):
    username: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    user: "UserBrief"


class UserBrief(BaseModel):
    id: int
    username: str
    full_name: str
    is_admin: bool

    model_config = {"from_attributes": True}


# =============================================================================
# Chat / RAG
# =============================================================================

class ChatRequest(BaseModel):
    question: str
    conversation_id: int | None = None
    collection_ids: list[int] | None = None
    enable_thinking: bool = False
    enable_enrichment_thinking: bool = False
    enable_enrichment: bool = True
    rag_mode: bool = True


class ChatResponse(BaseModel):
    answer: str
    conversation_id: int
    sources: list["SourceChunk"]


class SourceChunk(BaseModel):
    chunk_id: int
    document_id: int | None = None
    document_name: str
    collection_name: str
    content_preview: str
    page_number: int | None
    similarity_score: float


class RagChunk(BaseModel):
    document_id: int | None = None
    document_name: str
    collection_name: str
    page_number: int | None
    content: str
    similarity_score: float


class DocumentDeliveryResponse(BaseModel):
    document_id: int
    document_name: str
    collection_name: str
    file_type: str
    page_count: int
    reason: str = ""


class SelectedCollectionsUpdate(BaseModel):
    collection_ids: list[int]


# =============================================================================
# Conversations
# =============================================================================

class ConversationResponse(BaseModel):
    id: int
    title: str | None
    created_at: datetime
    message_count: int = 0

    model_config = {"from_attributes": True}


class MessageResponse(BaseModel):
    id: int
    role: str
    content: str
    sources: list[SourceChunk] = []
    enriched_query: str | None = None
    rag_chunks: list[RagChunk] = []
    thinking: str | None = None
    document_delivery: DocumentDeliveryResponse | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


# =============================================================================
# Users
# =============================================================================

class UserCreate(BaseModel):
    username: str
    email: str
    password: str
    full_name: str
    is_admin: bool = False


class UserUpdate(BaseModel):
    email: str | None = None
    full_name: str | None = None
    is_active: bool | None = None
    is_admin: bool | None = None


class UserResponse(BaseModel):
    id: int
    username: str
    email: str
    full_name: str
    is_active: bool
    is_admin: bool
    created_at: datetime

    model_config = {"from_attributes": True}


class UserWithGroups(UserResponse):
    groups: list["GroupBrief"] = []


class GroupBrief(BaseModel):
    id: int
    name: str

    model_config = {"from_attributes": True}


# =============================================================================
# Groups
# =============================================================================

class GroupCreate(BaseModel):
    name: str
    description: str | None = None


class GroupUpdate(BaseModel):
    name: str | None = None
    description: str | None = None


class GroupResponse(BaseModel):
    id: int
    name: str
    description: str | None
    created_at: datetime

    model_config = {"from_attributes": True}


class GroupWithMembers(GroupResponse):
    members: list["MemberBrief"] = []


class MemberBrief(BaseModel):
    id: int
    username: str
    full_name: str

    model_config = {"from_attributes": True}


class MemberAssignment(BaseModel):
    user_ids: list[int]


# =============================================================================
# Collections
# =============================================================================

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


# =============================================================================
# Documents
# =============================================================================

class DocumentResponse(BaseModel):
    id: int
    collection_id: int
    original_name: str
    file_type: str
    file_size_bytes: int
    processing_status: str
    processing_error: str | None
    chunk_count: int
    metadata_: dict | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


class DocumentStatusResponse(BaseModel):
    id: int
    processing_status: str
    processing_error: str | None
    chunk_count: int
    metadata_: dict | None = None

    model_config = {"from_attributes": True}
