"""Pydantic Schemas für Dokumente."""

from datetime import datetime

from pydantic import BaseModel


class DocumentResponse(BaseModel):
    id: int
    collection_id: int
    original_name: str
    file_type: str
    file_size_bytes: int
    context_description: str | None
    processing_status: str
    processing_error: str | None
    chunk_count: int
    created_at: datetime

    model_config = {"from_attributes": True}


class DocumentContextUpdate(BaseModel):
    context_description: str | None = None
    glossary: dict[str, str] = {}


class DocumentStatusResponse(BaseModel):
    id: int
    processing_status: str
    processing_error: str | None
    chunk_count: int
