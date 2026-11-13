"""
Foja AI Memory Services Package
"""

from app.services.memory.retrieval import (
    RetrievedMemory,
    RetrievalResult,
    retrieve_relevant_memories,
    format_user_message_with_memories,
)
from app.services.memory.extraction import (
    CandidateMemoryItem,
    contains_sensitive_data,
    parse_extraction_response,
    extract_candidates_from_conversation,
    save_extracted_candidates,
    run_memory_extraction_task,
    MemoryExtractionTaskManager,
    extraction_task_manager,
    schedule_extraction_task,
    startup_extraction_tasks,
    shutdown_extraction_tasks,
)

__all__ = [
    "RetrievedMemory",
    "RetrievalResult",
    "retrieve_relevant_memories",
    "format_user_message_with_memories",
    "CandidateMemoryItem",
    "contains_sensitive_data",
    "parse_extraction_response",
    "extract_candidates_from_conversation",
    "save_extracted_candidates",
    "run_memory_extraction_task",
    "MemoryExtractionTaskManager",
    "extraction_task_manager",
    "schedule_extraction_task",
    "startup_extraction_tasks",
    "shutdown_extraction_tasks",
]

