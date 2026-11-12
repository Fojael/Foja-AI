from datetime import datetime
from typing import List, Optional
from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.models.memory import MemoryCategory, MemoryStatus


class MemoryCreate(BaseModel):
    """
    Payload for creating a manual memory.
    Manually submitted memories are approved immediately.
    """
    content: str = Field(
        min_length=1,
        max_length=2000,
        description="The declarative memory content to store."
    )
    category: MemoryCategory = Field(
        default=MemoryCategory.FACT,
        description="The category classification for this memory."
    )
    importance: float = Field(
        default=0.5,
        ge=0.0,
        le=1.0,
        description="Importance score between 0.0 and 1.0."
    )
    is_global: bool = Field(
        default=False,
        description="Whether this instruction applies globally across all conversations."
    )

    @model_validator(mode="after")
    def validate_content_and_global(self):
        cleaned = self.content.strip()
        if not cleaned:
            raise ValueError("Memory content must not be blank or whitespace-only.")
        self.content = cleaned

        if self.is_global and self.category != MemoryCategory.INSTRUCTION:
            raise ValueError(
                "Global scope ('is_global=True') is only permitted for category='instruction'."
            )
        return self


class MemoryUpdate(BaseModel):
    """
    Payload for updating an existing memory record.
    All fields are optional.
    """
    content: Optional[str] = Field(
        default=None,
        min_length=1,
        max_length=2000,
        description="Updated memory content."
    )
    category: Optional[MemoryCategory] = Field(
        default=None,
        description="Updated memory category."
    )
    importance: Optional[float] = Field(
        default=None,
        ge=0.0,
        le=1.0,
        description="Updated importance score between 0.0 and 1.0."
    )
    is_global: Optional[bool] = Field(
        default=None,
        description="Updated global instruction flag."
    )

    @model_validator(mode="after")
    def validate_content(self):
        if self.content is not None:
            cleaned = self.content.strip()
            if not cleaned:
                raise ValueError("Memory content must not be blank or whitespace-only.")
            self.content = cleaned
        return self


class MemoryRead(BaseModel):
    """
    Serialized memory record representation.
    """
    id: str = Field(description="Unique UUID identifier.")
    owner_id: str = Field(description="Owner identity scope.")
    content: str = Field(description="Memory text content.")
    content_hash: str = Field(description="SHA-256 hash of normalized content.")
    category: MemoryCategory = Field(description="Memory category.")
    status: MemoryStatus = Field(description="Memory approval status.")
    importance: float = Field(description="Importance score.")
    is_global: bool = Field(description="Global instruction flag.")
    source_conversation_id: Optional[str] = Field(
        default=None,
        description="Source conversation ID if originated from a chat session."
    )
    created_at: datetime = Field(description="Creation timestamp in UTC.")
    updated_at: datetime = Field(description="Last updated timestamp in UTC.")

    model_config = ConfigDict(from_attributes=True)


class MemoryListResponse(BaseModel):
    """
    Paginated response container for memory listings.
    """
    items: List[MemoryRead] = Field(description="List of memory items for current page.")
    total: int = Field(description="Total count of records matching filters.")
    limit: int = Field(description="Page size limit applied.")
    offset: int = Field(description="Pagination offset applied.")


class DeleteResponse(BaseModel):
    """
    Response confirming deletion of a single memory.
    """
    success: bool = True
    id: str = Field(description="ID of the deleted memory.")
    message: str = Field(description="Human-readable confirmation.")


class BulkDeleteResponse(BaseModel):
    """
    Response confirming bulk deletion of memories.
    """
    success: bool = True
    deleted_count: int = Field(description="Number of memory records deleted.")
    message: str = Field(description="Human-readable confirmation.")
