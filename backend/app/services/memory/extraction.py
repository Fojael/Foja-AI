import asyncio
import hashlib
import json
import logging
import re
from typing import Any, Dict, List, Optional, Set
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.models.chat import Message
from app.models.memory import (
    Memory,
    MemoryCategory,
    MemoryStatus,
    compute_content_hash,
)
from app.services.ai.ollama import generate_chat_response

logger = logging.getLogger("foja.memory.extraction")

# Supported valid categories matching MemoryCategory enum
VALID_CATEGORIES: Set[str] = {c.value for c in MemoryCategory}

# Category normalization mapping
CATEGORY_NORMALIZATION: Dict[str, str] = {
    "preference": "preference",
    "fact": "fact",
    "project": "project",
    "instruction": "instruction",
    "personal": "personal",
    "context": "fact",  # Contextual facts map to fact
}

# Regex patterns for detecting sensitive data, credentials, and PII
SENSITIVE_PATTERNS = [
    # 1. API Keys & Access Tokens
    # OpenAI & Anthropic API keys (sk-..., sk-proj-..., sk-ant-...)
    re.compile(r"\bsk-(?:proj-|ant-)?[a-zA-Z0-9_-]{20,}\b", re.IGNORECASE),
    # GitHub Tokens (ghp, gho, ghu, ghs, ghr, github_pat)
    re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9_]{20,}|github_pat_[A-Za-z0-9_]{20,})\b", re.IGNORECASE),
    # AWS Access Key ID
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    # Google Cloud / Firebase API Keys
    re.compile(r"\bAIza[0-9A-Za-z-_]{30,45}\b"),
    # Generic Bearer Tokens
    re.compile(r"\bbearer\s+[a-zA-Z0-9_\-\.]{20,}\b", re.IGNORECASE),
    # JWT Tokens (eyJ...)
    re.compile(r"\beyJ[a-zA-Z0-9_-]{10,}\.eyJ[a-zA-Z0-9_-]{10,}\.[a-zA-Z0-9_-]{4,}\b"),

    # 2. Passwords, Credentials & Private Keys
    re.compile(r"-----BEGIN (?:[A-Z]+ )?PRIVATE KEY-----", re.IGNORECASE),
    re.compile(r"\b(?:password|passwd|pwd|secret|api[_-]?key|auth[_-]?token)\s*[:=]\s*\S+", re.IGNORECASE),

    # 3. Payment & Banking Credentials
    # Credit Card Numbers
    re.compile(r"\b(?:\d{4}[ -]?){3}\d{4}\b|\b\d{15,16}\b"),
    # International Bank Account Number (IBAN)
    re.compile(r"\b[A-Z]{2}\d{2}[A-Z0-9]{11,30}\b"),
    # Contextual Bank Account / Routing
    re.compile(r"\b(?:bank\s*account|account\s*no|acct\s*no|routing\s*no)\b.{0,15}\b[A-Z0-9-]{8,24}\b", re.IGNORECASE),
    # Card Security Codes (CVV/CVC/CID)
    re.compile(r"\b(?:card\s+)?(?:cvv2?|cvc2?|cid|security\s*code|card\s*code)\b(?:\s*(?:is|:|=)\s*|\s+)\d{3,4}\b", re.IGNORECASE),

    # 4. Bangladesh Mobile Phone Numbers (+8801[3-9]..., 01[3-9]...)
    re.compile(r"\b(?:\+?880\s*|00880\s*|0)1[3-9]\d{2}[-\s]?\d{6}\b"),

    # 5. Bangladesh National Identity Numbers (NID)
    re.compile(r"\b(?:nid|national\s*(?:id|identity))\b.{0,20}\b\d{10,17}\b", re.IGNORECASE),
    re.compile(r"\b(?:19\d{2}|20[0-2]\d)\d{13}\b"),

    # 6. Passport Numbers (Bangladesh Machine-Readable Passports and contextual passports)
    re.compile(r"\bpassport\b.{0,25}\b[A-Za-z0-9]{6,12}\b", re.IGNORECASE),
    re.compile(r"\b[A-Z]{1,2}\d{7}\b"),

    # 7. Email Addresses
    re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"),

    # 8. US Social Security Numbers
    re.compile(r"\b\d{3}-\d{2}-\d{4}\b"),
]

EXTRACTION_SYSTEM_PROMPT = (
    "You extract durable user memories from conversation transcripts.\n\n"
    "Rules:\n"
    "1. ONLY extract information stated by USER. NEVER extract from ASSISTANT lines.\n"
    "2. Ignore assistant-only statements, casual chat, and temporary questions (calculations, weather).\n"
    "3. Never extract passwords, API keys, credentials, card numbers, or security codes.\n"
    "4. If no durable user facts exist, return {\"memories\": []}.\n"
    "5. Respond ONLY with valid JSON with key \"memories\".\n\n"
    "Format:\n"
    "{\"memories\": [{\"content\": \"User prefers Python for backend development.\", \"category\": \"preference\", \"importance\": 0.8}]}\n\n"
    "Categories: \"preference\", \"project\", \"instruction\", \"fact\", \"personal\".\n\n"
    "Examples:\n"
    "- Dialogue:\n"
    "USER: I prefer Python for backend development.\n"
    "ASSISTANT: Python is a great choice.\n"
    "JSON:\n"
    "{\"memories\": [{\"content\": \"User prefers Python for backend development.\", \"category\": \"preference\", \"importance\": 0.8}]}\n\n"
    "- Dialogue:\n"
    "USER: What is 25 multiplied by 4?\n"
    "ASSISTANT: 25 multiplied by 4 is 100.\n"
    "JSON:\n"
    "{\"memories\": []}\n\n"
    "- Dialogue:\n"
    "USER: Which database should I pick?\n"
    "ASSISTANT: I recommend PostgreSQL for relational data.\n"
    "JSON:\n"
    "{\"memories\": []}"
)


class CandidateMemoryItem(BaseModel):
    """Schema representing an extracted candidate memory item."""
    content: str = Field(..., description="Declarative memory content.")
    category: str = Field(default="fact", description="Category classification.")
    importance: float = Field(default=0.5, ge=0.0, le=1.0, description="Importance score between 0.0 and 1.0.")

    @field_validator("content")
    @classmethod
    def validate_content(cls, v: str) -> str:
        cleaned = " ".join(v.strip().split())
        if not cleaned:
            raise ValueError("Candidate memory content must not be blank.")
        if len(cleaned) > settings.MEMORY_EXTRACTION_MAX_CONTENT_LENGTH:
            raise ValueError(
                f"Candidate memory content exceeds maximum length of {settings.MEMORY_EXTRACTION_MAX_CONTENT_LENGTH} characters."
            )
        return cleaned

    @field_validator("category")
    @classmethod
    def validate_category(cls, v: str) -> str:
        norm = v.strip().lower()
        if norm in CATEGORY_NORMALIZATION:
            return CATEGORY_NORMALIZATION[norm]
        if norm in VALID_CATEGORIES:
            return norm
        return MemoryCategory.FACT.value

    @field_validator("importance")
    @classmethod
    def validate_importance(cls, v: float) -> float:
        if v < 0.0:
            return 0.0
        if v > 1.0:
            return 1.0
        return round(float(v), 2)


def contains_sensitive_data(text: str) -> bool:
    """
    Check if the text contains any prohibited sensitive data patterns
    (API keys, tokens, passwords, credit cards, SSNs, private keys).
    """
    for pattern in SENSITIVE_PATTERNS:
        if pattern.search(text):
            return True
    return False


def parse_extraction_response(raw_text: str) -> List[CandidateMemoryItem]:
    """
    Parse and validate raw LLM text into a list of verified CandidateMemoryItem objects.
    Safely handles markdown wrapping, wrapper objects (e.g. {"memories": [...]}),
    single objects, malformed JSON, and invalid items without throwing exceptions.
    Enforces intra-batch deduplication, sensitive data filtering, and max candidates cap.
    """
    if not raw_text or not raw_text.strip():
        return []

    text = raw_text.strip()

    # If wrapped in markdown code fence, strip code block markers
    code_block_match = re.search(r"```(?:json)?\s*(.*?)\s*```", text, re.DOTALL | re.IGNORECASE)
    if code_block_match:
        text = code_block_match.group(1).strip()
    else:
        # Check for start of array '[' or object '{'
        first_bracket = text.find("[")
        first_brace = text.find("{")
        if first_bracket != -1 and (first_brace == -1 or first_bracket < first_brace):
            end_bracket = text.rfind("]")
            if end_bracket > first_bracket:
                text = text[first_bracket:end_bracket + 1].strip()
        elif first_brace != -1:
            end_brace = text.rfind("}")
            if end_brace > first_brace:
                text = text[first_brace:end_brace + 1].strip()

    try:
        data = json.loads(text)
    except (json.JSONDecodeError, ValueError) as err:
        logger.debug("Failed to decode JSON from extraction response: %s", err)
        return []

    items = []
    if isinstance(data, list):
        items = data
    elif isinstance(data, dict):
        found_list = None
        for key in ("memories", "candidates", "facts", "items", "data"):
            if key in data and isinstance(data[key], list):
                found_list = data[key]
                break
        if found_list is not None:
            items = found_list
        elif "content" in data:
            items = [data]
        else:
            return []
    else:
        return []

    candidates: List[CandidateMemoryItem] = []
    seen_hashes: Set[str] = set()

    for item in items:
        if not isinstance(item, dict):
            continue

        try:
            candidate = CandidateMemoryItem(**item)
        except Exception as val_err:
            logger.debug("Discarding invalid candidate item: %s", val_err)
            continue

        # Check for sensitive data
        if contains_sensitive_data(candidate.content):
            logger.warning("Discarded candidate memory containing detected sensitive credential/PII pattern.")
            continue

        # Intra-batch deduplication
        c_hash = compute_content_hash(candidate.content)
        if c_hash in seen_hashes:
            continue
        seen_hashes.add(c_hash)

        candidates.append(candidate)

        # Enforce maximum candidate extraction cap
        if len(candidates) >= settings.MEMORY_EXTRACTION_MAX_CANDIDATES:
            break

    return candidates


async def extract_candidates_from_conversation(
    conversation_id: str,
    db: AsyncSession,
    model: Optional[str] = None,
) -> List[CandidateMemoryItem]:
    """
    Load recent conversation history, invoke Ollama extraction pipeline,
    and return validated candidate memory items.
    """
    stmt = (
        select(Message)
        .where(Message.conversation_id == conversation_id)
        .order_by(Message.created_at.asc())
    )
    result = await db.execute(stmt)
    messages = result.scalars().all()

    if not messages:
        return []

    # Check that there is at least one user message
    user_msgs = [m for m in messages if m.role == "user"]
    if not user_msgs:
        return []

    # Limit to the most recent messages configured
    if len(messages) > settings.MEMORY_EXTRACTION_MAX_MESSAGES:
        messages = messages[-settings.MEMORY_EXTRACTION_MAX_MESSAGES:]

    # Format transcript for extraction prompt
    transcript_lines = []
    for msg in messages:
        role_label = msg.role.upper()
        transcript_lines.append(f"{role_label}: {msg.content}")

    transcript = "\n".join(transcript_lines)

    user_prompt = (
        f"Analyze the following conversation transcript and extract durable user memories:\n\n"
        f"{transcript}\n\n"
        f"JSON:"
    )

    messages_payload = [
        {"role": "user", "content": user_prompt}
    ]

    try:
        raw_reply = await generate_chat_response(
            messages=messages_payload,
            model=model or settings.DEFAULT_OLLAMA_MODEL,
            system_prompt=EXTRACTION_SYSTEM_PROMPT,
            format="json",
        )
    except Exception as err:
        logger.warning("Ollama invocation failed during memory extraction: %s", err)
        return []

    return parse_extraction_response(raw_reply)


async def save_extracted_candidates(
    candidates: List[CandidateMemoryItem],
    conversation_id: str,
    owner_id: str,
    db: AsyncSession,
) -> List[Memory]:
    """
    Persist candidates with status='suggested' into the database.
    Performs duplicate suppression against existing memories (approved, suggested, or rejected).
    """
    if not candidates:
        return []

    saved_memories: List[Memory] = []
    seen_in_batch: Set[str] = set()

    for candidate in candidates:
        content_hash = compute_content_hash(candidate.content)
        if content_hash in seen_in_batch:
            continue
        seen_in_batch.add(content_hash)

        # Query database to check if this hash already exists for this owner
        stmt = select(Memory.id).where(
            Memory.owner_id == owner_id,
            Memory.content_hash == content_hash,
        )
        existing = (await db.execute(stmt)).scalar_one_or_none()

        if existing is not None:
            # Memory already exists (approved, suggested, or previously rejected)
            logger.debug(
                "Suppressed duplicate memory candidate with hash '%s' for owner '%s'.",
                content_hash,
                owner_id,
            )
            continue

        memory = Memory(
            owner_id=owner_id,
            content=candidate.content,
            content_hash=content_hash,
            category=candidate.category,
            status=MemoryStatus.SUGGESTED.value,
            importance=candidate.importance,
            is_global=False,
            source_conversation_id=conversation_id,
        )
        db.add(memory)
        saved_memories.append(memory)

        if len(saved_memories) >= settings.MEMORY_EXTRACTION_MAX_CANDIDATES:
            break

    if not saved_memories:
        return []

    try:
        await db.commit()
        for mem in saved_memories:
            await db.refresh(mem)
        logger.info(
            "Saved %d suggested memory candidate(s) for conversation '%s' (owner: '%s').",
            len(saved_memories),
            conversation_id,
            owner_id,
        )
        return saved_memories
    except IntegrityError as err:
        await db.rollback()
        logger.warning(
            "IntegrityError while persisting extracted memory candidates: %s. Rolled back.",
            err,
        )
        return []
    except Exception as err:
        await db.rollback()
        logger.warning(
            "Unexpected error while saving extracted memory candidates: %s. Rolled back.",
            err,
        )
        return []


async def _run_extraction_pipeline(
    conversation_id: str,
    owner_id: str,
    db: AsyncSession,
    model: Optional[str] = None,
) -> List[Memory]:
    """Internal helper running the full extraction and persistence sequence."""
    candidates = await extract_candidates_from_conversation(
        conversation_id=conversation_id,
        db=db,
        model=model,
    )
    if not candidates:
        return []

    return await save_extracted_candidates(
        candidates=candidates,
        conversation_id=conversation_id,
        owner_id=owner_id,
        db=db,
    )


async def run_memory_extraction_task(
    conversation_id: str,
    owner_id: str = "default_user",
    db: Optional[AsyncSession] = None,
    model: Optional[str] = None,
) -> List[Memory]:
    """
    Background task entry point for automatic memory extraction.
    Creates and manages an independent AsyncSessionLocal session if db is not provided.
    Catches all exceptions to ensure background execution never affects chat or crashes.
    """
    if not settings.MEMORY_EXTRACTION_ENABLED:
        logger.debug("Automatic memory extraction is disabled.")
        return []

    try:
        if db is not None:
            return await _run_extraction_pipeline(conversation_id, owner_id, db, model=model)
        else:
            async with AsyncSessionLocal() as session:
                return await _run_extraction_pipeline(conversation_id, owner_id, session, model=model)
    except Exception as err:
        logger.warning(
            "Unhandled exception in automatic memory extraction task for conversation '%s': %s",
            conversation_id,
            err,
            exc_info=True,
        )
        return []


class MemoryExtractionTaskManager:
    """
    Application-level lifecycle manager for background memory extraction tasks.
    Maintains strong references to active tasks to prevent garbage collection,
    deduplicates per-conversation runs, and drains in-flight tasks during graceful shutdown.
    """
    def __init__(self) -> None:
        self._active_tasks: Dict[str, asyncio.Task] = {}
        self._is_shutting_down: bool = False

    def startup(self) -> None:
        """
        Initialize or reset manager state on application startup.
        Ensures manager is ready to accept and track extraction tasks.
        """
        self._is_shutting_down = False

    @property
    def is_shutting_down(self) -> bool:
        return self._is_shutting_down

    def get_active_tasks(self) -> Dict[str, asyncio.Task]:
        return dict(self._active_tasks)

    def schedule(
        self,
        conversation_id: str,
        owner_id: str = "default_user",
        model: Optional[str] = None,
    ) -> Optional[asyncio.Task]:
        """
        Schedule an extraction task for a conversation.
        Returns the Task, or None if extraction is disabled, shutting down,
        or already in progress for this conversation.
        """
        if not settings.MEMORY_EXTRACTION_ENABLED:
            logger.debug("Automatic memory extraction is disabled.")
            return None

        if self._is_shutting_down:
            logger.warning(
                "Application is shutting down. Rejected extraction task for conversation '%s'.",
                conversation_id,
            )
            return None

        existing = self._active_tasks.get(conversation_id)
        if existing and not existing.done():
            logger.info(
                "Extraction task already in progress for conversation '%s'; skipping duplicate.",
                conversation_id,
            )
            return existing

        task_name = f"memory-extraction-{conversation_id}"
        coro = run_memory_extraction_task(
            conversation_id=conversation_id,
            owner_id=owner_id,
            model=model,
        )
        task = asyncio.create_task(coro, name=task_name)
        self._active_tasks[conversation_id] = task

        def _on_task_done(t: asyncio.Task) -> None:
            self._active_tasks.pop(conversation_id, None)
            if t.cancelled():
                logger.info("Extraction task for conversation '%s' was cancelled.", conversation_id)
            elif t.exception():
                logger.error(
                    "Extraction task for conversation '%s' failed unexpectedly: %s",
                    conversation_id,
                    t.exception(),
                    exc_info=t.exception(),
                )
            else:
                logger.debug("Extraction task for conversation '%s' completed successfully.", conversation_id)

        task.add_done_callback(_on_task_done)
        logger.debug(
            "Registered active extraction task for conversation '%s' (active count: %d).",
            conversation_id,
            len(self._active_tasks),
        )
        return task

    async def shutdown(self, timeout: Optional[float] = None) -> Dict[str, int]:
        """
        Gracefully drain active extraction tasks up to timeout.
        Cancels remaining tasks and awaits cleanup before returning.
        """
        self._is_shutting_down = True
        drain_timeout = timeout if timeout is not None else settings.MEMORY_EXTRACTION_SHUTDOWN_TIMEOUT_SECONDS

        pending = [t for t in self._active_tasks.values() if not t.done()]
        if not pending:
            logger.info("No active memory extraction tasks to drain on shutdown.")
            return {"completed": 0, "cancelled": 0, "timed_out": 0}

        logger.info(
            "Initiating graceful shutdown for %d active extraction task(s) (timeout=%.1fs)...",
            len(pending),
            drain_timeout,
        )

        done, still_pending = await asyncio.wait(pending, timeout=drain_timeout)
        completed_count = len(done)
        timed_out_count = len(still_pending)
        cancelled_count = 0

        if still_pending:
            logger.warning(
                "%d extraction task(s) did not finish within %.1fs timeout; cancelling...",
                timed_out_count,
                drain_timeout,
            )
            for t in still_pending:
                t.cancel()

            # Await cancelled tasks to allow async with session handlers to clean up
            await asyncio.gather(*still_pending, return_exceptions=True)
            cancelled_count = timed_out_count
            logger.info("All timed-out extraction tasks have been cancelled and cleaned up.")

        self._active_tasks.clear()
        logger.info(
            "Extraction task shutdown complete: %d completed, %d cancelled.",
            completed_count,
            cancelled_count,
        )
        return {
            "completed": completed_count,
            "cancelled": cancelled_count,
            "timed_out": timed_out_count,
        }

    def reset_for_tests(self) -> None:
        """Reset manager state between test cases."""
        self._active_tasks.clear()
        self._is_shutting_down = False


# Module-level singleton
extraction_task_manager = MemoryExtractionTaskManager()


def startup_extraction_tasks() -> None:
    """Helper to initialize extraction task manager on application startup."""
    extraction_task_manager.startup()


def schedule_extraction_task(
    conversation_id: str,
    owner_id: str = "default_user",
    model: Optional[str] = None,
) -> Optional[asyncio.Task]:
    """Helper to schedule an extraction task via the lifecycle manager."""
    return extraction_task_manager.schedule(conversation_id, owner_id=owner_id, model=model)


async def shutdown_extraction_tasks(timeout: Optional[float] = None) -> Dict[str, int]:
    """Helper to drain extraction tasks via the lifecycle manager."""
    return await extraction_task_manager.shutdown(timeout=timeout)

