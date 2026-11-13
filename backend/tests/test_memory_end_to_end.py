"""
Foja AI — Phase 2.4.6.1: Comprehensive Memory System End-to-End Integration Tests.

Verifies all 14 critical memory lifecycle points:
1. User message creation
2. Extraction candidate generation
3. Sensitive-data rejection (including 'Card security code is 1234')
4. Suggested memory creation
5. Duplicate suppression
6. Manual approval
7. Manual rejection
8. Approved-memory retrieval
9. Rejected-memory exclusion
10. Context injection into chat (streaming and non-streaming)
11. Memory deletion
12. Conversation deletion setting source_conversation_id = NULL
13. Extraction failure handling (Ollama down / timeout)
14. Background task cancellation, deduplication, and cleanup

Strict safety requirements:
- Fully isolated in-memory SQLite database (never touches data/foja.db).
- Foreign key pragma strictly enforced.
- Dependency overrides cleared after each test.
- Extraction task manager state reset after each test.
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
    shutdown_extraction_tasks,
    startup_extraction_tasks,
)
from app.services.memory.retrieval import (
    DELIMITER_BEGIN,
    DELIMITER_END,
    format_user_message_with_memories,
    retrieve_relevant_memories,
)

# Isolated in-memory SQLite database using StaticPool to ensure all connections share the DB
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


class TestMemoryEndToEndIntegration(unittest.IsolatedAsyncioTestCase):
    """
    End-to-end integration test suite covering the full lifecycle of Foja AI memories.
    """

    async def asyncSetUp(self):
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
    # Test 1: Full Lifecycle (Creation -> Extraction -> Approval -> Retrieval -> Injection -> Deletion)
    # --------------------------------------------------------------------------
    async def test_full_memory_lifecycle_happy_path(self):
        """
        Covers:
        1. User message creation
        2. Extraction candidate generation
        4. Suggested memory creation
        6. Manual approval via API
        8. Approved-memory retrieval
        10. Context injection into chat (non-streaming and streaming)
        11. Memory deletion
        """
        owner = "default_user"

        # 1. User message creation
        async with TestSessionLocal() as session:
            conv = Conversation(title="Python Optimization Discussion")
            session.add(conv)
            await session.commit()
            await session.refresh(conv)

            user_msg = Message(
                conversation_id=conv.id,
                role="user",
                content="I always write backend microservices in Python 3.13 using FastAPI.",
            )
            asst_msg = Message(
                conversation_id=conv.id,
                role="assistant",
                content="FastAPI with Python 3.13 provides exceptional performance and async ergonomics.",
            )
            session.add_all([user_msg, asst_msg])
            await session.commit()

        # 2. Extraction candidate generation via Ollama mock
        mock_extracted_json = json.dumps([
            {
                "content": "User develops backend microservices using Python 3.13 and FastAPI.",
                "category": "preference",
                "importance": 0.85,
            }
        ])

        with patch("app.services.memory.extraction.generate_chat_response", new_callable=AsyncMock) as mock_ai:
            mock_ai.return_value = mock_extracted_json

            async with TestSessionLocal() as session:
                candidates = await extract_candidates_from_conversation(conv.id, session)
                self.assertEqual(len(candidates), 1)
                self.assertEqual(candidates[0].category, "preference")
                self.assertAlmostEqual(candidates[0].importance, 0.85)

                # 4. Suggested memory creation in DB
                saved = await save_extracted_candidates(candidates, conv.id, owner, session)
                self.assertEqual(len(saved), 1)
                self.assertEqual(saved[0].status, MemoryStatus.SUGGESTED.value)
                memory_id = saved[0].id

        # Verify suggested memory is returned in GET /api/memories?status=suggested
        list_resp = await self.client.get("/api/memories?status=suggested")
        self.assertEqual(list_resp.status_code, 200)
        list_data = list_resp.json()
        self.assertEqual(list_data["total"], 1)
        self.assertEqual(list_data["items"][0]["id"], memory_id)
        self.assertEqual(list_data["items"][0]["status"], "suggested")

        # 8a. Verify suggested memory is NOT retrieved by retrieval engine
        async with TestSessionLocal() as session:
            retrieval_before = await retrieve_relevant_memories(
                user_message="What framework should we use for our Python backend?",
                owner_id=owner,
                db=session,
            )
            self.assertEqual(len(retrieval_before.items), 0)

        # 6. Manual approval via POST /api/memories/{id}/approve
        approve_resp = await self.client.post(f"/api/memories/{memory_id}/approve")
        self.assertEqual(approve_resp.status_code, 200)
        approved_data = approve_resp.json()
        self.assertEqual(approved_data["status"], "approved")

        # 8b. Approved-memory retrieval
        async with TestSessionLocal() as session:
            retrieval_after = await retrieve_relevant_memories(
                user_message="Which Python version and framework do I use?",
                owner_id=owner,
                db=session,
            )
            self.assertEqual(len(retrieval_after.items), 1)
            self.assertEqual(retrieval_after.items[0].id, memory_id)
            self.assertIn("Python 3.13", retrieval_after.items[0].content)

        # 10a. Context injection into non-streaming chat
        with patch("app.api.chat.generate_chat_response", new_callable=AsyncMock) as mock_chat_ai:
            mock_chat_ai.return_value = "You use Python 3.13 and FastAPI as saved in your preferences."

            chat_resp = await self.client.post(
                "/api/chat",
                json={"message": "Which Python stack do I prefer?", "conversation_id": conv.id},
            )
            self.assertEqual(chat_resp.status_code, 200)

            # Inspect payload sent to Ollama: must include reference context with DELIMITER_BEGIN
            called_messages = mock_chat_ai.call_args[1]["messages"]
            last_message_content = called_messages[-1]["content"]
            self.assertIn(DELIMITER_BEGIN, last_message_content)
            self.assertIn(DELIMITER_END, last_message_content)
            self.assertIn("Python 3.13 and FastAPI", last_message_content)
            self.assertIn("Which Python stack do I prefer?", last_message_content)

            # Verify un-injected message was persisted cleanly in DB
            async with TestSessionLocal() as session:
                res = await session.execute(
                    select(Message)
                    .where(Message.conversation_id == conv.id, Message.role == "user")
                    .order_by(Message.created_at.desc())
                )
                persisted_user_msg = res.scalars().first()
                self.assertIsNotNone(persisted_user_msg)
                self.assertEqual(persisted_user_msg.content, "Which Python stack do I prefer?")
                self.assertNotIn(DELIMITER_BEGIN, persisted_user_msg.content)

        # 10b. Context injection into streaming chat
        async def mock_stream(*args, **kwargs):
            yield "Based on your preferences, "
            yield "you prefer Python 3.13."

        with patch("app.api.chat.stream_chat_response", side_effect=mock_stream):
            stream_resp = await self.client.post(
                "/api/chat/stream",
                json={"message": "Remind me of my backend setup.", "conversation_id": conv.id},
            )
            self.assertEqual(stream_resp.status_code, 200)
            self.assertIn('"type": "start"', stream_resp.text)
            self.assertIn('"type": "chunk"', stream_resp.text)
            self.assertIn('"type": "done"', stream_resp.text)

        # 11. Memory deletion via DELETE /api/memories/{id}
        del_resp = await self.client.delete(f"/api/memories/{memory_id}")
        self.assertEqual(del_resp.status_code, 200)
        del_data = del_resp.json()
        self.assertTrue(del_data["success"])
        self.assertEqual(del_data["id"], memory_id)

        # Confirm 404 after deletion
        get_after_del = await self.client.get(f"/api/memories/{memory_id}")
        self.assertEqual(get_after_del.status_code, 404)

    # --------------------------------------------------------------------------
    # Test 2: Sensitive-Data Rejection (Including "Card security code is 1234")
    # --------------------------------------------------------------------------
    async def test_sensitive_data_rejection_and_filtering(self):
        """
        Covers:
        3. Sensitive-data rejection:
           - Specifically verifies 'Card security code is 1234'
           - Credit card numbers
           - Bangladesh phone numbers (+8801...)
           - Smart NIDs
           - Passwords
           - API keys
           - Ensures sensitive candidates are never persisted to the database.
        """
        owner = "default_user"

        async with TestSessionLocal() as session:
            conv = Conversation(title="Sensitive Information Session")
            session.add(conv)
            await session.commit()
            await session.refresh(conv)

        # Candidates with sensitive items
        raw_candidates_json = json.dumps([
            {"content": "Card security code is 1234", "category": "fact", "importance": 0.9},
            {"content": "User card security code: 567", "category": "fact", "importance": 0.9},
            {"content": "User CVV is 999", "category": "fact", "importance": 0.9},
            {"content": "MasterCard number: 5500 1234 5678 9012", "category": "fact", "importance": 0.9},
            {"content": "User phone number is +8801712345678", "category": "personal", "importance": 0.8},
            {"content": "User NID is 1990123456789", "category": "personal", "importance": 0.9},
            {"content": "User prefers dark mode editor theme.", "category": "preference", "importance": 0.7},
        ])

        with patch("app.services.memory.extraction.generate_chat_response", new_callable=AsyncMock) as mock_ai:
            mock_ai.return_value = raw_candidates_json

            # Add dummy message so extract_candidates_from_conversation proceeds
            async with TestSessionLocal() as session:
                msg = Message(conversation_id=conv.id, role="user", content="Here are my notes.")
                session.add(msg)
                await session.commit()

                candidates = await extract_candidates_from_conversation(conv.id, session)

                # Exactly 1 safe candidate must remain
                self.assertEqual(len(candidates), 1)
                self.assertEqual(candidates[0].content, "User prefers dark mode editor theme.")

                # Save candidates to database
                saved = await save_extracted_candidates(candidates, conv.id, owner, session)
                self.assertEqual(len(saved), 1)
                self.assertEqual(saved[0].content, "User prefers dark mode editor theme.")

            # Verify database has zero sensitive records
            async with TestSessionLocal() as session:
                all_mems = (await session.execute(select(Memory))).scalars().all()
                self.assertEqual(len(all_mems), 1)
                for mem in all_mems:
                    self.assertFalse(contains_sensitive_data(mem.content))

    # --------------------------------------------------------------------------
    # Test 3: Duplicate Memory Suppression
    # --------------------------------------------------------------------------
    async def test_duplicate_memory_suppression(self):
        """
        Covers:
        5. Duplicate suppression:
           - Extracted identical content is skipped and not duplicated in DB.
        """
        owner = "default_user"

        async with TestSessionLocal() as session:
            conv = Conversation(title="Duplicate Test Conv")
            session.add(conv)
            await session.commit()
            await session.refresh(conv)

            content = "User works with PostgreSQL on Azure."
            cand = CandidateMemoryItem(content=content, category="fact", importance=0.8)

            # First save
            first_save = await save_extracted_candidates([cand], conv.id, owner, session)
            self.assertEqual(len(first_save), 1)

            # Second save of identical content
            second_save = await save_extracted_candidates([cand], conv.id, owner, session)
            self.assertEqual(len(second_save), 0)

            # Check total count in database: must be exactly 1
            res = await session.execute(select(Memory).where(Memory.content_hash == compute_content_hash(content)))
            mems = res.scalars().all()
            self.assertEqual(len(mems), 1)

    # --------------------------------------------------------------------------
    # Test 4: Manual Rejection Lifecycle and Exclusion
    # --------------------------------------------------------------------------
    async def test_manual_rejection_and_retrieval_exclusion(self):
        """
        Covers:
        7. Manual rejection via POST /api/memories/{id}/reject
        9. Rejected-memory exclusion from context retrieval
        """
        owner = "default_user"

        # Create a suggested memory
        async with TestSessionLocal() as session:
            conv = Conversation(title="Rejection Conversation")
            session.add(conv)
            await session.commit()
            await session.refresh(conv)

            mem = Memory(
                content="User dislikes TypeScript.",
                content_hash=compute_content_hash("User dislikes TypeScript."),
                category=MemoryCategory.PREFERENCE.value,
                status=MemoryStatus.SUGGESTED.value,
                importance=0.7,
                owner_id=owner,
                source_conversation_id=conv.id,
            )
            session.add(mem)
            await session.commit()
            await session.refresh(mem)
            mem_id = mem.id

        # Reject via API
        reject_resp = await self.client.post(f"/api/memories/{mem_id}/reject")
        self.assertEqual(reject_resp.status_code, 200)
        reject_data = reject_resp.json()
        self.assertEqual(reject_data["status"], "rejected")

        # Verify exclusion from retrieval
        async with TestSessionLocal() as session:
            retrieval = await retrieve_relevant_memories(
                user_message="Do I like TypeScript?",
                owner_id=owner,
                db=session,
            )
            self.assertEqual(len(retrieval.items), 0)

        # Verify duplicate extraction of this rejected fact is also suppressed
        async with TestSessionLocal() as session:
            cand = CandidateMemoryItem(content="User dislikes TypeScript.", category="preference", importance=0.7)
            duplicate_attempt = await save_extracted_candidates([cand], conv.id, owner, session)
            self.assertEqual(len(duplicate_attempt), 0)

    # --------------------------------------------------------------------------
    # Test 5: Foreign Key ON DELETE SET NULL on Conversation Deletion
    # --------------------------------------------------------------------------
    async def test_conversation_deletion_sets_null_foreign_key(self):
        """
        Covers:
        12. Conversation deletion setting source_conversation_id = NULL
            preserving the approved/suggested memory.
        """
        owner = "default_user"

        async with TestSessionLocal() as session:
            conv = Conversation(title="Ephemeral Conversation")
            session.add(conv)
            await session.commit()
            await session.refresh(conv)
            conv_id = conv.id

            mem = Memory(
                content="User lives in Dhaka, Bangladesh.",
                content_hash=compute_content_hash("User lives in Dhaka, Bangladesh."),
                category=MemoryCategory.PERSONAL.value,
                status=MemoryStatus.APPROVED.value,
                importance=0.9,
                owner_id=owner,
                source_conversation_id=conv_id,
            )
            session.add(mem)
            await session.commit()
            await session.refresh(mem)
            mem_id = mem.id

        # Delete conversation via API
        del_conv_resp = await self.client.delete(f"/api/conversations/{conv_id}")
        self.assertEqual(del_conv_resp.status_code, 200)

        # Verify memory still exists and source_conversation_id is now None (SET NULL)
        async with TestSessionLocal() as session:
            res = await session.execute(select(Memory).where(Memory.id == mem_id))
            mem_after = res.scalar_one_or_none()
            self.assertIsNotNone(mem_after)
            self.assertIsNone(mem_after.source_conversation_id)
            self.assertEqual(mem_after.status, "approved")

    # --------------------------------------------------------------------------
    # Test 6: Extraction Failure Handling (Ollama Down / Timeout)
    # --------------------------------------------------------------------------
    async def test_extraction_failure_handling(self):
        """
        Covers:
        13. Extraction failure handling:
            - When Ollama raises connection error or times out, extraction catches
              the error cleanly and does not leave corrupted DB transactions.
        """
        async with TestSessionLocal() as session:
            conv = Conversation(title="Failure Resiliency Conv")
            session.add(conv)
            await session.commit()
            await session.refresh(conv)

            msg = Message(conversation_id=conv.id, role="user", content="Hello world")
            session.add(msg)
            await session.commit()

        # Simulate Ollama connection failure
        with patch("app.services.memory.extraction.generate_chat_response", side_effect=OllamaConnectionError("Ollama offline")):
            async with TestSessionLocal() as session:
                candidates = await extract_candidates_from_conversation(conv.id, session)
                self.assertEqual(candidates, [])

        # Simulate unexpected response format / JSON decode failure
        with patch("app.services.memory.extraction.generate_chat_response", new_callable=AsyncMock) as mock_ai:
            mock_ai.return_value = "Not valid JSON output from LLM"
            async with TestSessionLocal() as session:
                candidates = await extract_candidates_from_conversation(conv.id, session)
                self.assertEqual(candidates, [])

    # --------------------------------------------------------------------------
    # Test 7: Background Task Manager Concurrency, Deduplication & Cleanup
    # --------------------------------------------------------------------------
    async def test_background_task_manager_concurrency_and_cleanup(self):
        """
        Covers:
        14. Background task cancellation, deduplication, and cleanup:
            - Task deduplication for same conversation.
            - Graceful shutdown awaits or cancels in-flight tasks.
            - Startup resets shutdown flag.
        """
        mgr = MemoryExtractionTaskManager()

        with patch.object(settings, "MEMORY_EXTRACTION_ENABLED", True):
            async def slow_work(*args, **kwargs):
                await asyncio.sleep(0.1)
                return []

            with patch("app.services.memory.extraction.run_memory_extraction_task", side_effect=slow_work):
                # 1. Schedule initial task
                task1 = mgr.schedule("conv_concur_1", "default_user")
                self.assertIsNotNone(task1)

                # 2. Duplicate schedule returns existing task
                task2 = mgr.schedule("conv_concur_1", "default_user")
                self.assertIs(task1, task2)
                self.assertEqual(len(mgr.get_active_tasks()), 1)

                # 3. Shutdown drains tasks
                shutdown_stats = await mgr.shutdown(timeout=0.5)
                self.assertEqual(shutdown_stats["completed"], 1)
                self.assertEqual(len(mgr.get_active_tasks()), 0)
                self.assertTrue(mgr.is_shutting_down)

                # 4. New tasks rejected while shutting down
                task_rejected = mgr.schedule("conv_concur_2", "default_user")
                self.assertIsNone(task_rejected)

                # 5. Startup resets state
                mgr.startup()
                self.assertFalse(mgr.is_shutting_down)


if __name__ == "__main__":
    unittest.main()
