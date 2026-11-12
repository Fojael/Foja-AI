from datetime import datetime, timezone
import uuid
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import get_current_owner_id
from app.core.database import get_db
from app.models.memory import (
    Memory,
    MemoryCategory,
    MemoryStatus,
    compute_content_hash,
)
from app.schemas.memory import (
    BulkDeleteResponse,
    DeleteResponse,
    MemoryCreate,
    MemoryListResponse,
    MemoryRead,
    MemoryUpdate,
)

router = APIRouter(prefix="/api/memories", tags=["Memory Management"])


def validate_uuid(id_str: str) -> None:
    """Validate that id_str is a syntactically valid UUID, raising 404 if invalid."""
    try:
        uuid.UUID(id_str)
    except (ValueError, TypeError, AttributeError):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Memory '{id_str}' not found."
        )


# ==============================================================================
# 1. Listing and Creation
# ==============================================================================

@router.get(
    "",
    response_model=MemoryListResponse,
    summary="List memories with optional filters",
    status_code=status.HTTP_200_OK,
)
async def list_memories(
    status_filter: Optional[MemoryStatus] = Query(
        default=None,
        alias="status",
        description="Filter by memory status ('suggested', 'approved', 'rejected')."
    ),
    category_filter: Optional[MemoryCategory] = Query(
        default=None,
        alias="category",
        description="Filter by memory category."
    ),
    is_global_filter: Optional[bool] = Query(
        default=None,
        alias="is_global",
        description="Filter by global instruction flag."
    ),
    min_importance: Optional[float] = Query(
        default=None,
        ge=0.0,
        le=1.0,
        description="Filter memories with importance >= min_importance."
    ),
    max_importance: Optional[float] = Query(
        default=None,
        ge=0.0,
        le=1.0,
        description="Filter memories with importance <= max_importance."
    ),
    limit: int = Query(
        default=50,
        ge=1,
        le=100,
        description="Maximum number of records to return."
    ),
    offset: int = Query(
        default=0,
        ge=0,
        description="Number of records to skip for pagination."
    ),
    owner_id: str = Depends(get_current_owner_id),
    db: AsyncSession = Depends(get_db),
):
    """
    Retrieve paginated memories scoped strictly to the current owner.
    Supports filtering by status, category, is_global, and importance ranges.
    """
    conditions = [Memory.owner_id == owner_id]

    if status_filter is not None:
        conditions.append(Memory.status == status_filter.value)
    if category_filter is not None:
        conditions.append(Memory.category == category_filter.value)
    if is_global_filter is not None:
        conditions.append(Memory.is_global == is_global_filter)
    if min_importance is not None:
        conditions.append(Memory.importance >= min_importance)
    if max_importance is not None:
        conditions.append(Memory.importance <= max_importance)

    # 1. Query total matching count without loading full entity objects
    count_stmt = select(func.count(Memory.id)).where(*conditions)
    total_count = (await db.execute(count_stmt)).scalar() or 0

    # 2. Query paginated slice ordered deterministically by newest updated first
    items_stmt = (
        select(Memory)
        .where(*conditions)
        .order_by(Memory.updated_at.desc(), Memory.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    result = await db.execute(items_stmt)
    memories = result.scalars().all()

    return MemoryListResponse(
        items=memories,
        total=total_count,
        limit=limit,
        offset=offset
    )


@router.post(
    "",
    response_model=MemoryRead,
    status_code=status.HTTP_201_CREATED,
    summary="Create a manually entered, approved memory",
)
async def create_memory(
    payload: MemoryCreate,
    owner_id: str = Depends(get_current_owner_id),
    db: AsyncSession = Depends(get_db),
):
    """
    Create a new manual memory for the current owner.
    Business rules:
    - Automatically assigned 'approved' status (explicit user submission).
    - Checks for content duplicates via SHA-256 content_hash and rejects with HTTP 409 Conflict.
    - Global instructions are restricted to category='instruction'.
    """
    content_hash = compute_content_hash(payload.content)

    # Check for existing duplicate memory for this owner
    existing = await db.execute(
        select(Memory).where(
            Memory.owner_id == owner_id,
            Memory.content_hash == content_hash,
        )
    )
    if existing.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A memory with identical content already exists."
        )

    memory = Memory(
        owner_id=owner_id,
        content=payload.content,
        content_hash=content_hash,
        category=payload.category.value,
        status=MemoryStatus.APPROVED.value,
        importance=payload.importance,
        is_global=payload.is_global,
    )

    db.add(memory)
    try:
        await db.commit()
        await db.refresh(memory)
    except IntegrityError as err:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A memory with identical content already exists."
        ) from err

    return memory


# ==============================================================================
# 2. Static Bulk Deletion Endpoints (MUST precede /{memory_id} routes)
# ==============================================================================

@router.delete(
    "/approved",
    response_model=BulkDeleteResponse,
    summary="Delete all approved memories for current owner",
    status_code=status.HTTP_200_OK,
)
async def clear_approved_memories(
    owner_id: str = Depends(get_current_owner_id),
    db: AsyncSession = Depends(get_db),
):
    """
    Purges all memories belonging to the current owner that have 'approved' status.
    Suggestions and rejected records remain preserved.
    """
    stmt = (
        delete(Memory)
        .where(
            Memory.owner_id == owner_id,
            Memory.status == MemoryStatus.APPROVED.value,
        )
    )
    res = await db.execute(stmt)
    await db.commit()
    deleted = res.rowcount or 0

    return BulkDeleteResponse(
        success=True,
        deleted_count=deleted,
        message=f"Successfully deleted {deleted} approved memory record(s)."
    )


@router.delete(
    "/all",
    response_model=BulkDeleteResponse,
    summary="Delete all memories for current owner",
    status_code=status.HTTP_200_OK,
)
async def clear_all_memories(
    owner_id: str = Depends(get_current_owner_id),
    db: AsyncSession = Depends(get_db),
):
    """
    Completely purges all memories belonging to the current owner
    (including approved, suggested, and rejected records).
    """
    stmt = delete(Memory).where(Memory.owner_id == owner_id)
    res = await db.execute(stmt)
    await db.commit()
    deleted = res.rowcount or 0

    return BulkDeleteResponse(
        success=True,
        deleted_count=deleted,
        message=f"Successfully deleted {deleted} memory record(s)."
    )


# ==============================================================================
# 3. Dynamic Single-Memory Operations
# ==============================================================================

@router.get(
    "/{memory_id}",
    response_model=MemoryRead,
    summary="Retrieve one memory by ID",
    status_code=status.HTTP_200_OK,
)
async def get_memory(
    memory_id: str,
    owner_id: str = Depends(get_current_owner_id),
    db: AsyncSession = Depends(get_db),
):
    """
    Retrieve details for a single memory record.
    Returns HTTP 404 if the memory does not exist or belongs to another owner.
    """
    validate_uuid(memory_id)

    res = await db.execute(
        select(Memory).where(
            Memory.id == memory_id,
            Memory.owner_id == owner_id,
        )
    )
    memory = res.scalar_one_or_none()
    if not memory:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Memory '{memory_id}' not found."
        )

    return memory


@router.patch(
    "/{memory_id}",
    response_model=MemoryRead,
    summary="Update permitted memory fields",
    status_code=status.HTTP_200_OK,
)
async def update_memory(
    memory_id: str,
    payload: MemoryUpdate,
    owner_id: str = Depends(get_current_owner_id),
    db: AsyncSession = Depends(get_db),
):
    """
    Update permitted fields on an existing memory.
    Business rules:
    - Validates that the combined final state respects the constraint
      (is_global=True is permitted ONLY for category='instruction').
    - Recalculates content_hash and prevents duplicate collisions with HTTP 409.
    - Updates updated_at timestamp to current UTC time.
    - Owner and ID cannot be changed.
    """
    validate_uuid(memory_id)

    res = await db.execute(
        select(Memory).where(
            Memory.id == memory_id,
            Memory.owner_id == owner_id,
        )
    )
    memory = res.scalar_one_or_none()
    if not memory:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Memory '{memory_id}' not found."
        )

    # 1. Validate combined state rule for category and is_global
    final_category = payload.category.value if payload.category is not None else memory.category
    final_is_global = payload.is_global if payload.is_global is not None else memory.is_global

    if final_is_global and final_category != MemoryCategory.INSTRUCTION.value:
        raise HTTPException(
            status_code=422,
            detail="Global memories ('is_global=True') are only permitted for category='instruction'."
        )

    # 2. Check content modification and hash conflict
    if payload.content is not None:
        new_hash = compute_content_hash(payload.content)
        if new_hash != memory.content_hash:
            conflict = await db.execute(
                select(Memory).where(
                    Memory.owner_id == owner_id,
                    Memory.content_hash == new_hash,
                    Memory.id != memory_id,
                )
            )
            if conflict.scalar_one_or_none():
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="A memory with identical content already exists."
                )
            memory.content = payload.content
            memory.content_hash = new_hash

    # 3. Apply field updates
    if payload.category is not None:
        memory.category = payload.category.value
    if payload.importance is not None:
        memory.importance = payload.importance
    if payload.is_global is not None:
        memory.is_global = payload.is_global

    memory.updated_at = datetime.now(timezone.utc)

    try:
        await db.commit()
        await db.refresh(memory)
    except IntegrityError as err:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A memory with identical content already exists."
        ) from err

    return memory


@router.post(
    "/{memory_id}/approve",
    response_model=MemoryRead,
    summary="Approve a memory",
    status_code=status.HTTP_200_OK,
)
async def approve_memory(
    memory_id: str,
    owner_id: str = Depends(get_current_owner_id),
    db: AsyncSession = Depends(get_db),
):
    """
    Transition a memory to 'approved' status.
    Returns HTTP 400 if the memory is already approved.
    """
    validate_uuid(memory_id)

    res = await db.execute(
        select(Memory).where(
            Memory.id == memory_id,
            Memory.owner_id == owner_id,
        )
    )
    memory = res.scalar_one_or_none()
    if not memory:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Memory '{memory_id}' not found."
        )

    if memory.status == MemoryStatus.APPROVED.value:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Memory is already approved."
        )

    memory.status = MemoryStatus.APPROVED.value
    memory.updated_at = datetime.now(timezone.utc)

    await db.commit()
    await db.refresh(memory)
    return memory


@router.post(
    "/{memory_id}/reject",
    response_model=MemoryRead,
    summary="Reject a memory",
    status_code=status.HTTP_200_OK,
)
async def reject_memory(
    memory_id: str,
    owner_id: str = Depends(get_current_owner_id),
    db: AsyncSession = Depends(get_db),
):
    """
    Transition a memory to 'rejected' status.
    Returns HTTP 400 if the memory is already rejected.
    """
    validate_uuid(memory_id)

    res = await db.execute(
        select(Memory).where(
            Memory.id == memory_id,
            Memory.owner_id == owner_id,
        )
    )
    memory = res.scalar_one_or_none()
    if not memory:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Memory '{memory_id}' not found."
        )

    if memory.status == MemoryStatus.REJECTED.value:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Memory is already rejected."
        )

    memory.status = MemoryStatus.REJECTED.value
    memory.updated_at = datetime.now(timezone.utc)

    await db.commit()
    await db.refresh(memory)
    return memory


@router.delete(
    "/{memory_id}",
    response_model=DeleteResponse,
    summary="Delete one memory by ID",
    status_code=status.HTTP_200_OK,
)
async def delete_memory(
    memory_id: str,
    owner_id: str = Depends(get_current_owner_id),
    db: AsyncSession = Depends(get_db),
):
    """
    Permanently delete a single memory record belonging to the current owner.
    Returns HTTP 404 if not found.
    """
    validate_uuid(memory_id)

    res = await db.execute(
        select(Memory).where(
            Memory.id == memory_id,
            Memory.owner_id == owner_id,
        )
    )
    memory = res.scalar_one_or_none()
    if not memory:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Memory '{memory_id}' not found."
        )

    await db.delete(memory)
    await db.commit()

    return DeleteResponse(
        success=True,
        id=memory_id,
        message="Memory deleted successfully."
    )
