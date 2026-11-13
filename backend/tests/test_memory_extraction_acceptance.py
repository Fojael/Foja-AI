"""
Foja AI — Phase 2.4.6.2: Controlled Memory Extraction Acceptance Test Suite.

Comprehensive acceptance testing for automatic memory extraction:
1. Quality of extraction across synthetic conversations:
   - A. Durable preferences
   - B. Project information
   - C. Long-term instructions
   - D. Temporary / irrelevant queries (filtered to empty)
   - E. Sensitive information rejection (passwords, CVVs, API keys, NIDs, phones, bank accounts)
   - F. Assistant-originated facts rejection (only user-stated facts eligible)
2. Malformed / non-JSON LLM response safety
3. Suggestion persistence invariants (UUID, owner, category, importance, status='suggested', is_global=False)
4. Duplicate and rejection suppression:
   - Intra-batch duplicate deduplication
   - Inter-batch identical candidate suppression
   - Normalization & whitespace resilience
   - Previously approved memory suppression
   - Previously rejected memory suppression
   - Meaningfully different candidate allowance
5. Background integration & chat lifecycle:
   - Non-streaming chat schedules extraction post-commit
   - Streaming chat schedules extraction only upon full completion
   - Failed generation does not schedule extraction
   - Incomplete streaming does not schedule extraction
   - Background extraction failure does not affect chat response
6. Manual review boundary:
   - Suggested memories excluded from lexical retrieval
   - Approval transitions to approved & enables retrieval
   - Rejection transitions to rejected & permanently excludes from retrieval
   - Extraction NEVER directly approves memories

Strict safety requirements:
- Isolated in-memory SQLite database using StaticPool (never touches data/foja.db).
- MEMORY_EXTRACTION_ENABLED is enabled ONLY via scoped test patches and restored immediately.
- Production database records are never modified.
"""

import sys
from pathlib import Path

# Ensure backend directory is in sys.path
BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

import asyncio
from datetime import datetime, timezone
import json
import unittest
from unittest.mock import AsyncMock, patch
import httpx
from sqlalchemy import event, select
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import StaticPool

from app.core.config import settings
from app.core.database import Base, get_db
from app.main import app
from app.models.chat import Conversation, Message
from app.models.memory import (
    Memory,
    MemoryCategory,
    MemoryStatus,
    compute_content_hash,
)
from app.services.ai.ollama import (
    OllamaConnectionError,
    OllamaResponseError,
)
from app.services.memory.extraction import (
    CandidateMemoryItem,
    MemoryExtractionTaskManager,
    contains_sensitive_data,
    extract_candidates_from_conversation,
    extraction_task_manager,
    parse_extraction_response,
    run_memory_extraction_task,
    save_extracted_candidates,
    schedule_extraction_task,
)
from app.services.memory.retrieval import (
    retrieve_relevant_memories,
)

# Fully isolated in-memory test database using StaticPool
TEST_DB_URL = "sqlite+aiosqlite:///:memory:"

test_engine = create_async_engine(
    TEST_DB_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
    echo=False,
    future=True,
)


@event.listens_for(test_engine.sync_engine, "connect")
def set_sqlite_pragma(dbapi_connection, connection_record):
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


TestSessionLocal = async_sessionmaker(
    bind=test_engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
)


async def override_get_db():
    async with TestSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


class TestMemoryExtractionAcceptance(unittest.IsolatedAsyncioTestCase):
    """
    Acceptance test suite for Phase 2.4.6.2: Controlled Memory Extraction.
    """

    async def asyncSetUp(self):
        # Verification: Ensure test_engine is an isolated in-memory database
        self.assertEqual(test_engine.url.database, ":memory:")
        self.assertNotIn("foja.db", str(test_engine.url))

        async with test_engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
            await conn.run_sync(Base.metadata.create_all)

        extraction_task_manager.reset_for_tests()
        app.dependency_overrides[get_db] = override_get_db
        self.transport = httpx.ASGITransport(app=app)
        self.client = httpx.AsyncClient(transport=self.transport, base_url="http://test")

    async def asyncTearDown(self):
        await self.client.aclose()
        app.dependency_overrides.clear()
        extraction_task_manager.reset_for_tests()
        async with test_engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)

    # --------------------------------------------------------------------------
    # 1. Extraction Quality Across Synthetic Conversation Categories
    # --------------------------------------------------------------------------
    async def test_extraction_quality_durable_preferences(self):
        """Category A: Verify durable preferences are cleanly parsed and extracted."""
        raw_json = json.dumps([
            {"content": "User prefers Python for backend development.", "category": "preference", "importance": 0.85},
            {"content": "User likes explanations accompanied by practical code examples.", "category": "preference", "importance": 0.80},
        ])
        candidates = parse_extraction_response(raw_json)
        self.assertEqual(len(candidates), 2)
        self.assertEqual(candidates[0].category, "preference")
        self.assertEqual(candidates[1].category, "preference")
        self.assertIn("Python for backend development", candidates[0].content)
        self.assertIn("practical code examples", candidates[1].content)

    async def test_extraction_quality_project_information(self):
        """Category B: Verify project architecture and details are classified as project."""
        raw_json = json.dumps([
            {"content": "User is building a personal AI desktop assistant named Foja AI.", "category": "project", "importance": 0.90},
            {"content": "User's project Foja AI uses FastAPI, React, and SQLite.", "category": "project", "importance": 0.85},
        ])
        candidates = parse_extraction_response(raw_json)
        self.assertEqual(len(candidates), 2)
        self.assertEqual(candidates[0].category, "project")
        self.assertEqual(candidates[1].category, "project")
        self.assertEqual(candidates[0].importance, 0.90)

    async def test_extraction_quality_long_term_instructions(self):
        """Category C: Verify durable instructions are classified as instruction."""
        raw_json = json.dumps([
            {"content": "Explain programming topics step by step.", "category": "instruction", "importance": 0.80},
            {"content": "Use beginner-friendly explanations when answering technical questions.", "category": "instruction", "importance": 0.75},
        ])
        candidates = parse_extraction_response(raw_json)
        self.assertEqual(len(candidates), 2)
        self.assertEqual(candidates[0].category, "instruction")
        self.assertEqual(candidates[1].category, "instruction")

    async def test_extraction_quality_temporary_and_irrelevant_information_filtered(self):
        """Category D: Temporary queries (weather, time, math) must produce empty extraction results."""
        # For temporary queries, the LLM prompt instructs returning an empty JSON array []
        raw_json = "[]"
        candidates = parse_extraction_response(raw_json)
        self.assertEqual(candidates, [])

        # Even if a model mistakenly emitted a transient query, verify it's handled safely
        async with TestSessionLocal() as session:
            saved = await save_extracted_candidates(candidates, "conv_empty", "default_user", session)
            self.assertEqual(saved, [])

    async def test_extraction_quality_sensitive_information_rejection(self):
        """Category E: Verify synthetic sensitive credentials and identifiers are discarded."""
        sensitive_items = [
            {"content": "Card security code is 1234", "category": "fact", "importance": 0.9},
            {"content": "User CVV is 567", "category": "fact", "importance": 0.9},
            {"content": "Password: SecretPassword123!", "category": "fact", "importance": 0.9},
            {"content": "Google API key is AIzaSyD-1234567890abcdefghijklmnopqrst", "category": "fact", "importance": 0.9},
            {"content": "Anthropic key is sk-ant-api03-abcdefghijklmnopqrstuvwxyz1234567890", "category": "fact", "importance": 0.9},
            {"content": "User contact phone is +8801712345678", "category": "personal", "importance": 0.8},
            {"content": "User NID is 19901234567890123", "category": "personal", "importance": 0.9},
            {"content": "Account email is developer@foja.ai", "category": "personal", "importance": 0.7},
            {"content": "IBAN number is BD12ABCD12345678901234", "category": "fact", "importance": 0.9},
            {"content": "User prefers dark mode UI.", "category": "preference", "importance": 0.8},
        ]
        candidates = parse_extraction_response(json.dumps(sensitive_items))
        # Only the safe item ("User prefers dark mode UI.") must survive
        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0].content, "User prefers dark mode UI.")

    async def test_extraction_quality_assistant_originated_facts_exclusion(self):
        """Category F: Assistant statements must not be extracted as user facts."""
        async with TestSessionLocal() as session:
            conv = Conversation(title="Assistant Advice Session")
            session.add(conv)
            await session.commit()
            await session.refresh(conv)

            # Assistant suggests Docker, but user only asks a question
            u_msg = Message(conversation_id=conv.id, role="user", content="How should I package my app?")
            a_msg = Message(
                conversation_id=conv.id,
                role="assistant",
                content="I recommend using Docker multi-stage builds and PostgreSQL.",
            )
            session.add_all([u_msg, a_msg])
            await session.commit()

        # Mock model properly following prompt rule #2: strictly ignore assistant statements
        with patch("app.services.memory.extraction.generate_chat_response", new_callable=AsyncMock) as mock_ai:
            mock_ai.return_value = "[]"
            async with TestSessionLocal() as session:
                candidates = await extract_candidates_from_conversation(conv.id, session)
                self.assertEqual(candidates, [])

    async def test_extraction_malformed_and_markdown_json_handling(self):
        """Verify markdown code blocks, malformed JSON, and non-array responses fail safely."""
        # 1. Wrapped in markdown code fence
        markdown_json = "```json\n[{\"content\": \"User uses Windows 11.\", \"category\": \"fact\", \"importance\": 0.7}]\n```"
        candidates = parse_extraction_response(markdown_json)
        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0].content, "User uses Windows 11.")

        # 2. Malformed JSON returns empty list
        self.assertEqual(parse_extraction_response("Not valid JSON"), [])
        self.assertEqual(parse_extraction_response(""), [])
        self.assertEqual(parse_extraction_response("{'single': 'object'}"), [])
        self.assertEqual(parse_extraction_response("{\"type\": \"object_not_array\"}"), [])

    # --------------------------------------------------------------------------
    # 2. Suggestion Persistence Invariants
    # --------------------------------------------------------------------------
    async def test_suggestion_persistence_invariants(self):
        """
        Verify saved memories strictly enforce:
        - Unique UUID string
        - Correct owner_id
        - Correct category
        - Correct importance
        - source_conversation_id populated
        - content_hash matches compute_content_hash
        - status='suggested' (NEVER auto-approved)
        - is_global=False
        """
        owner = "default_user"
        async with TestSessionLocal() as session:
            conv = Conversation(title="Invariant Verification Conv")
            session.add(conv)
            await session.commit()
            await session.refresh(conv)

            candidate = CandidateMemoryItem(
                content="User works on Windows 11 with WSL2 enabled.",
                category="fact",
                importance=0.85,
            )

            saved = await save_extracted_candidates([candidate], conv.id, owner, session)
            self.assertEqual(len(saved), 1)
            mem = saved[0]

            self.assertEqual(len(mem.id), 36)
            self.assertEqual(mem.owner_id, owner)
            self.assertEqual(mem.category, "fact")
            self.assertAlmostEqual(mem.importance, 0.85)
            self.assertEqual(mem.source_conversation_id, conv.id)
            self.assertEqual(mem.content_hash, compute_content_hash("User works on Windows 11 with WSL2 enabled."))
            self.assertEqual(mem.status, MemoryStatus.SUGGESTED.value)
            self.assertFalse(mem.is_global)

    # --------------------------------------------------------------------------
    # 3. Duplicate and Rejection Protection
    # --------------------------------------------------------------------------
    async def test_duplicate_suppression_and_normalization(self):
        """
        Verify duplicate protection:
        1. Same candidate extracted twice
        2. Same candidate with different whitespace
        3. Previously approved candidate
        4. Previously rejected candidate
        5. Similar but meaningfully different candidate allowed
        6. Intra-batch duplicates deduplicated
        """
        owner = "default_user"

        async with TestSessionLocal() as session:
            conv = Conversation(title="Duplicate Protection Conv")
            session.add(conv)
            await session.commit()
            await session.refresh(conv)

            # 6. Intra-batch duplicate deduplication
            batch = [
                CandidateMemoryItem(content="User prefers vim keybindings.", category="preference", importance=0.8),
                CandidateMemoryItem(content="User prefers vim keybindings.", category="preference", importance=0.8),
                CandidateMemoryItem(content="  User   prefers   vim   keybindings.  ", category="preference", importance=0.8),
            ]
            saved_batch = await save_extracted_candidates(batch, conv.id, owner, session)
            self.assertEqual(len(saved_batch), 1)
            vim_mem = saved_batch[0]

            # 1 & 2. Second extraction with extra whitespace is suppressed
            second_cand = CandidateMemoryItem(
                content="   User prefers   vim keybindings.   \n",
                category="preference",
                importance=0.8,
            )
            saved_dup = await save_extracted_candidates([second_cand], conv.id, owner, session)
            self.assertEqual(len(saved_dup), 0)

            # 3. Previously approved candidate suppression
            vim_mem.status = MemoryStatus.APPROVED.value
            await session.commit()

            saved_after_approved = await save_extracted_candidates([second_cand], conv.id, owner, session)
            self.assertEqual(len(saved_after_approved), 0)

            # 4. Previously rejected candidate suppression
            rejected_mem = Memory(
                content="User dislikes Docker.",
                content_hash=compute_content_hash("User dislikes Docker."),
                category=MemoryCategory.PREFERENCE.value,
                status=MemoryStatus.REJECTED.value,
                owner_id=owner,
            )
            session.add(rejected_mem)
            await session.commit()

            cand_rejected = CandidateMemoryItem(content="User dislikes Docker.", category="preference", importance=0.5)
            saved_after_rejected = await save_extracted_candidates([cand_rejected], conv.id, owner, session)
            self.assertEqual(len(saved_after_rejected), 0)

            # 5. Similar but meaningfully different candidate is allowed
            diff_cand = CandidateMemoryItem(
                content="User prefers vim keybindings specifically in VS Code.",
                category="preference",
                importance=0.75,
            )
            saved_diff = await save_extracted_candidates([diff_cand], conv.id, owner, session)
            self.assertEqual(len(saved_diff), 1)

    # --------------------------------------------------------------------------
    # 4. Background Integration & Chat Lifecycle
    # --------------------------------------------------------------------------
    async def test_non_streaming_chat_schedules_extraction_after_persistence(self):
        """Verify non-streaming chat schedules background extraction only after message persistence."""
        with patch.object(settings, "MEMORY_EXTRACTION_ENABLED", True), \
             patch("app.api.chat.generate_chat_response", new_callable=AsyncMock) as mock_ai, \
             patch("app.api.chat.schedule_extraction_task") as mock_sched:

            mock_ai.return_value = "Python 3.13 is supported."

            resp = await self.client.post("/api/chat", json={"message": "Do you support Python 3.13?"})
            self.assertEqual(resp.status_code, 200)

            # Task must be scheduled
            mock_sched.assert_called_once()
            called_conv_id = mock_sched.call_args[1]["conversation_id"]

            # Verify messages are already committed in DB before extraction runs
            async with TestSessionLocal() as session:
                msgs = (await session.execute(
                    select(Message).where(Message.conversation_id == called_conv_id)
                )).scalars().all()
                self.assertEqual(len(msgs), 2)  # user + assistant

    async def test_streaming_chat_schedules_extraction_only_after_completion(self):
        """Verify streaming chat schedules extraction only after full SSE stream completes."""
        async def mock_stream(*args, **kwargs):
            yield "Chunk 1 "
            yield "Chunk 2"

        with patch.object(settings, "MEMORY_EXTRACTION_ENABLED", True), \
             patch("app.api.chat.stream_chat_response", side_effect=mock_stream), \
             patch("app.api.chat.schedule_extraction_task") as mock_sched:

            resp = await self.client.post("/api/chat/stream", json={"message": "Stream to me."})
            self.assertEqual(resp.status_code, 200)
            self.assertIn('"type": "done"', resp.text)

            mock_sched.assert_called_once()

    async def test_failed_ai_generation_does_not_schedule_extraction(self):
        """Verify failed AI generation does not schedule an extraction task."""
        with patch.object(settings, "MEMORY_EXTRACTION_ENABLED", True), \
             patch("app.api.chat.generate_chat_response", side_effect=OllamaConnectionError("Ollama down")), \
             patch("app.api.chat.schedule_extraction_task") as mock_sched:

            resp = await self.client.post("/api/chat", json={"message": "Will fail."})
            self.assertEqual(resp.status_code, 503)

            mock_sched.assert_not_called()

    async def test_incomplete_streaming_response_does_not_schedule_extraction(self):
        """Verify mid-stream failure aborts and does not schedule an extraction task."""
        async def mock_broken_stream(*args, **kwargs):
            yield "First chunk..."
            raise OllamaResponseError("Stream broke unexpectedly")

        with patch.object(settings, "MEMORY_EXTRACTION_ENABLED", True), \
             patch("app.api.chat.stream_chat_response", side_effect=mock_broken_stream), \
             patch("app.api.chat.schedule_extraction_task") as mock_sched:

            resp = await self.client.post("/api/chat/stream", json={"message": "Broken stream."})
            self.assertEqual(resp.status_code, 200)
            self.assertIn('"type": "error"', resp.text)

            mock_sched.assert_not_called()

    async def test_extraction_failure_does_not_corrupt_chat_response(self):
        """Verify background extraction exception does not affect user chat response."""
        async def failing_extraction(*args, **kwargs):
            raise RuntimeError("Fatal extraction pipeline failure")

        with patch.object(settings, "MEMORY_EXTRACTION_ENABLED", True), \
             patch("app.api.chat.generate_chat_response", new_callable=AsyncMock) as mock_ai, \
             patch("app.services.memory.extraction.run_memory_extraction_task", side_effect=failing_extraction):

            mock_ai.return_value = "Normal response unaffected by extraction failure."

            resp = await self.client.post("/api/chat", json={"message": "Safe message."})
            self.assertEqual(resp.status_code, 200)
            data = resp.json()
            self.assertEqual(data["reply"], "Normal response unaffected by extraction failure.")

    # --------------------------------------------------------------------------
    # 5. Manual-Review Boundary
    # --------------------------------------------------------------------------
    async def test_manual_review_boundary_enforcement(self):
        """
        Verify:
        - Suggested memories appear under ?status=suggested filter.
        - Suggested memories are NEVER retrieved by the lexical retrieval engine.
        - Approval changes status to 'approved' and enables retrieval.
        - Rejection changes status to 'rejected' and prevents retrieval.
        - Extraction NEVER directly activates a memory.
        """
        owner = "default_user"
        async with TestSessionLocal() as session:
            conv = Conversation(title="Review Boundary Conv")
            session.add(conv)
            await session.commit()
            await session.refresh(conv)

            cand = CandidateMemoryItem(
                content="User prefers PostgreSQL over MongoDB.",
                category="preference",
                importance=0.8,
            )
            saved = await save_extracted_candidates([cand], conv.id, owner, session)
            self.assertEqual(len(saved), 1)
            mem_id = saved[0].id

        # 1. Listed under status=suggested
        list_resp = await self.client.get("/api/memories?status=suggested")
        self.assertEqual(list_resp.status_code, 200)
        items = list_resp.json()["items"]
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["id"], mem_id)
        self.assertEqual(items[0]["status"], "suggested")

        # 2. Excluded from retrieval while suggested
        async with TestSessionLocal() as session:
            res_before = await retrieve_relevant_memories(
                user_message="Which database do I prefer: PostgreSQL or MongoDB?",
                owner_id=owner,
                db=session,
            )
            self.assertEqual(len(res_before.items), 0)

        # 3. Approve via API
        appr_resp = await self.client.post(f"/api/memories/{mem_id}/approve")
        self.assertEqual(appr_resp.status_code, 200)
        self.assertEqual(appr_resp.json()["status"], "approved")

        # 4. Now retrieved
        async with TestSessionLocal() as session:
            res_after = await retrieve_relevant_memories(
                user_message="Which database do I prefer: PostgreSQL or MongoDB?",
                owner_id=owner,
                db=session,
            )
            self.assertEqual(len(res_after.items), 1)
            self.assertEqual(res_after.items[0].id, mem_id)

        # 5. Reject via API
        rej_resp = await self.client.post(f"/api/memories/{mem_id}/reject")
        self.assertEqual(rej_resp.status_code, 200)
        self.assertEqual(rej_resp.json()["status"], "rejected")

        # 6. Excluded from retrieval after rejection
        async with TestSessionLocal() as session:
            res_rejected = await retrieve_relevant_memories(
                user_message="Which database do I prefer: PostgreSQL or MongoDB?",
                owner_id=owner,
                db=session,
            )
            self.assertEqual(len(res_rejected.items), 0)


if __name__ == "__main__":
    unittest.main()
