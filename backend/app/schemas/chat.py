"""Pydantic Schemas für Chat/RAG."""

from datetime import datetime

from enum import Enum

from pydantic import BaseModel


class ChatMode(str, Enum):
    rag = "rag"
    chat = "chat"


class ChatRequest(BaseModel):
    question: str
    conversation_id: int | None = None
    collection_ids: list[int] | None = None  # Override für ausgewählte Collections
    mode: ChatMode = ChatMode.rag


class ChatResponse(BaseModel):
    answer: str
    conversation_id: int
    sources: list["SourceChunk"]


class SourceChunk(BaseModel):
    chunk_id: int
    document_name: str
    collection_name: str
    content_preview: str
    page_number: int | None
    similarity_score: float


class ConversationResponse(BaseModel):
    id: int
    title: str | None
    created_at: datetime
    message_count: int = 0

    model_config = {"from_attributes": True}


class RagChunk(BaseModel):
    document_name: str
    collection_name: str
    page_number: int | None
    content: str
    similarity_score: float


class MessageResponse(BaseModel):
    id: int
    role: str
    content: str
    sources: list[SourceChunk] = []
    enriched_query: str | None = None
    rag_chunks: list[RagChunk] = []
    created_at: datetime

    model_config = {"from_attributes": True}


class SelectedCollectionsUpdate(BaseModel):
    collection_ids: list[int]


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
