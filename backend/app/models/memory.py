import hashlib
import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import TYPE_CHECKING
from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Float,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base, UTCDateTime

if TYPE_CHECKING:
    from app.models.chat import Conversation


def utc_now() -> datetime:
    """Return timezone-aware current UTC datetime."""
    return datetime.now(timezone.utc)


def compute_content_hash(content: str) -> str:
    """
    Generate deterministic SHA-256 hash of normalized text.
    Strips leading/trailing whitespace, converts to lowercase, and collapses internal spaces.
    """
    normalized = " ".join(content.strip().lower().split())
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


class MemoryStatus(str, Enum):
    SUGGESTED = "suggested"  # Proposed by AI extraction; awaiting explicit user approval
    APPROVED = "approved"    # Explicitly approved by user; active for context retrieval
    REJECTED = "rejected"    # Explicitly rejected by user; preserved to prevent duplicate suggestions


class MemoryCategory(str, Enum):
    PREFERENCE = "preference"      # E.g., user preferences
    FACT = "fact"                  # E.g., user environment or hardware facts
    PROJECT = "project"            # E.g., project details and architecture
    INSTRUCTION = "instruction"    # E.g., durable standing directives
    PERSONAL = "personal"          # E.g., user personal information


class Memory(Base):
    __tablename__ = "memories"

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid.uuid4())
    )
    owner_id: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        default="default_user"
    )
    content: Mapped[str] = mapped_column(
        Text,
        nullable=False
    )
    content_hash: Mapped[str] = mapped_column(
        String(64),
        nullable=False
    )
    category: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        default=MemoryCategory.FACT.value
    )
    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default=MemoryStatus.SUGGESTED.value
    )
    importance: Mapped[float] = mapped_column(
        Float,
        nullable=False,
        default=0.5
    )
    is_global: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False
    )
    source_conversation_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("conversations.id", ondelete="SET NULL"),
        nullable=True,
        index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime,
        default=utc_now
    )
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime,
        default=utc_now,
        onupdate=utc_now
    )

    # Optional reference to conversation.
    # When source conversation is deleted, ON DELETE SET NULL ensures memory is preserved.
    conversation: Mapped["Conversation | None"] = relationship(
        "Conversation",
        backref="memories",
        foreign_keys=[source_conversation_id]
    )

    __table_args__ = (
        # Enforce unique content per owner to prevent duplicate/nagging memories
        UniqueConstraint("owner_id", "content_hash", name="uq_memories_owner_content_hash"),
        # Enforce that is_global=True is strictly reserved for category='instruction'
        CheckConstraint("is_global = 0 OR category = 'instruction'", name="ck_memories_global_only_for_instruction"),
        # Composite index for status and category filtering scoped by owner
        Index("idx_memories_owner_status_category", "owner_id", "status", "category"),
        # Composite index for ordering by recency scoped by owner and status
        Index("idx_memories_owner_status_updated", "owner_id", "status", "updated_at"),
    )
