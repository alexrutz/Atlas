"""Pydantic Schemas für Dokumente."""

from datetime import datetime

from pydantic import BaseModel


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
