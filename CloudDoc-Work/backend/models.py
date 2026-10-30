"""Pydantic request and response schemas for CloudDoc AI."""
from __future__ import annotations

import uuid
from typing import Optional
from pydantic import BaseModel, Field, field_validator

from config import MAX_QUESTION_CHARS


class DocumentMeta(BaseModel):
    id: str
    filename: str
    size_bytes: int
    page_count: int
    chunk_count: int
    uploaded_at: str
    status: str = "ready"
    ocr_applied: bool = False


class ChatRequest(BaseModel):
    question: str
    document_id: Optional[str] = None

    @field_validator("question")
    @classmethod
    def _check_question(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("question must not be empty")
        if len(value) > MAX_QUESTION_CHARS:
            raise ValueError(
                f"question must be at most {MAX_QUESTION_CHARS} characters"
            )
        return value

    @field_validator("document_id")
    @classmethod
    def _check_document_id(cls, value: Optional[str]) -> Optional[str]:
        if value is None or not value.strip():
            return None
        try:
            return str(uuid.UUID(value.strip()))
        except ValueError:
            raise ValueError("document_id must be a UUID") from None


class DebugSearchRequest(ChatRequest):
    """Same shape as a chat request: {question, document_id}."""


class Source(BaseModel):
    document_id: str
    filename: str
    page: int
    text: str
    score: float
    chunk_id: Optional[str] = None


class ChatResponse(BaseModel):
    answer: str
    sources: list[Source]
    provider: str = "retrieval"
    mode: str = "retrieval_only"
    model: Optional[str] = None


class OperationRequest(BaseModel):
    operation: str
    document_ids: list[str] = Field(..., min_length=1)
    query: Optional[str] = None

    @field_validator("operation")
    @classmethod
    def _check_op(cls, value: str) -> str:
        valid_ops = {"summarize", "key_points", "deadlines", "people", "costs", "compare"}
        value = value.lower().strip()
        if value not in valid_ops:
            raise ValueError(f"operation must be one of {sorted(valid_ops)}")
        return value

    @field_validator("document_ids")
    @classmethod
    def _check_doc_ids(cls, ids: list[str]) -> list[str]:
        cleaned = []
        for raw_id in ids:
            cleaned_id = raw_id.strip()
            try:
                cleaned.append(str(uuid.UUID(cleaned_id)))
            except ValueError:
                raise ValueError(f"Invalid UUID: {raw_id}") from None
        if not cleaned:
            raise ValueError("document_ids must contain at least one valid UUID")
        return cleaned


class OperationResponse(BaseModel):
    operation: str
    title: str
    result: str
    sources: list[Source]
    mode: str


class ProviderStatus(BaseModel):
    provider: str
    ollama_url: str
    ollama_model: str
    ollama_available: bool
    ocr_available: bool
    details: str
