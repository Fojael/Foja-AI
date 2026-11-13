import sys
from pathlib import Path

# Ensure backend directory is in sys.path
BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

import asyncio
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

from app.core.auth import DEFAULT_OWNER_ID
from app.core.config import Settings, settings
from app.core.database import Base, get_db
from app.main import app
from app.models.chat import Conversation, Message
from app.models.memory import Memory, MemoryStatus
from app.services.ai.ollama import OllamaConnectionError
from app.services.memory.extraction import (
    CandidateMemoryItem,
    MemoryExtractionTaskManager,
    contains_sensitive_data,
    extraction_task_manager,
    parse_extraction_response,
    run_memory_extraction_task,
    save_extracted_candidates,
    schedule_extraction_task,
    shutdown_extraction_tasks,
)

# Isolated in-memory SQLite database for testing - Never touches production data
TEST_DB_URL = "sqlite+aiosqlite:///:memory:"

test_engine = create_async_engine(
    TEST_DB_URL,
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


class TestMemoryExtractionHardening(unittest.IsolatedAsyncioTestCase):

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
    # 1. Background Task Lifecycle & Tracking
    # --------------------------------------------------------------------------
    async def test_task_manager_strong_references(self):
        """Verify task manager registers active tasks and keeps strong references."""
        mgr = MemoryExtractionTaskManager()
        with patch.object(settings, "MEMORY_EXTRACTION_ENABLED", True):
            async def mock_coro(*args, **kwargs):
                await asyncio.sleep(0.05)
                return []

            with patch("app.services.memory.extraction.run_memory_extraction_task", side_effect=mock_coro):
                task = mgr.schedule("conv_track_1", "default_user")
                self.assertIsNotNone(task)
                self.assertIn("conv_track_1", mgr.get_active_tasks())
                self.assertFalse(task.done())

                await task
                # Once done callback executes, it must be removed
                self.assertNotIn("conv_track_1", mgr.get_active_tasks())

    async def test_task_manager_deduplicates_active_tasks(self):
        """Verify calling schedule for the same conversation returns existing active task."""
        mgr = MemoryExtractionTaskManager()
        with patch.object(settings, "MEMORY_EXTRACTION_ENABLED", True):
            async def slow_coro(*args, **kwargs):
                await asyncio.sleep(0.1)
                return []

            with patch("app.services.memory.extraction.run_memory_extraction_task", side_effect=slow_coro):
                task1 = mgr.schedule("conv_dedup", "default_user")
                task2 = mgr.schedule("conv_dedup", "default_user")
                self.assertIs(task1, task2)
                self.assertEqual(len(mgr.get_active_tasks()), 1)
                await task1

    async def test_task_manager_rejects_tasks_when_shutting_down(self):
        """Verify new tasks are rejected once shutdown has initiated."""
        mgr = MemoryExtractionTaskManager()
        with patch.object(settings, "MEMORY_EXTRACTION_ENABLED", True):
            await mgr.shutdown(timeout=0.1)
            self.assertTrue(mgr.is_shutting_down)

            task = mgr.schedule("conv_reject", "default_user")
            self.assertIsNone(task)

            # Test that startup() restores accepting tasks
            mgr.startup()
            self.assertFalse(mgr.is_shutting_down)
            async def dummy_coro(*args, **kwargs):
                return []
            with patch("app.services.memory.extraction.run_memory_extraction_task", side_effect=dummy_coro):
                task_resumed = mgr.schedule("conv_resumed", "default_user")
                self.assertIsNotNone(task_resumed)
                await task_resumed

    async def test_task_manager_graceful_shutdown_drains_tasks(self):
        """Verify in-flight tasks finish within timeout during graceful shutdown."""
        mgr = MemoryExtractionTaskManager()
        completed = False

        with patch.object(settings, "MEMORY_EXTRACTION_ENABLED", True):
            async def quick_coro(*args, **kwargs):
                nonlocal completed
                await asyncio.sleep(0.02)
                completed = True
                return []

            with patch("app.services.memory.extraction.run_memory_extraction_task", side_effect=quick_coro):
                mgr.schedule("conv_drain", "default_user")
                stats = await mgr.shutdown(timeout=0.5)

                self.assertTrue(completed)
                self.assertEqual(stats["completed"], 1)
                self.assertEqual(stats["cancelled"], 0)
                self.assertEqual(stats["timed_out"], 0)
                self.assertEqual(len(mgr.get_active_tasks()), 0)

    async def test_task_manager_graceful_shutdown_cancels_timed_out_tasks(self):
        """Verify tasks exceeding shutdown timeout are cancelled and cleanly awaited."""
        mgr = MemoryExtractionTaskManager()
        cancelled = False

        with patch.object(settings, "MEMORY_EXTRACTION_ENABLED", True):
            async def infinite_coro(*args, **kwargs):
                nonlocal cancelled
                try:
                    await asyncio.sleep(10.0)
                except asyncio.CancelledError:
                    cancelled = True
                    raise

            with patch("app.services.memory.extraction.run_memory_extraction_task", side_effect=infinite_coro):
                mgr.schedule("conv_timeout", "default_user")
                stats = await mgr.shutdown(timeout=0.05)

                self.assertTrue(cancelled)
                self.assertEqual(stats["cancelled"], 1)
                self.assertEqual(stats["timed_out"], 1)
                self.assertEqual(len(mgr.get_active_tasks()), 0)

    # --------------------------------------------------------------------------
    # 2. Bangladesh-Focused Sensitive Data Protection
    # --------------------------------------------------------------------------
    def test_sensitive_data_bangladesh_mobile_numbers(self):
        """Test detection of Bangladesh mobile numbers (+8801..., 01...)."""
        samples = [
            "User contact phone number is +8801712345678",
            "Call me at 01712-345678 tomorrow",
            "Emergency number: 01819123456",
            "Phone: +880 1912345678",
            "User's mobile is 01312345678",
            "Contact: 01412345678",
            "Number: 01512345678",
            "Number: 01612345678",
        ]
        for s in samples:
            self.assertTrue(contains_sensitive_data(s), f"Failed to detect BD mobile: {s}")

    def test_sensitive_data_bangladesh_national_id(self):
        """Test detection of Bangladesh 10-digit Smart NID, 13-digit and 17-digit Old NID."""
        samples = [
            "User's NID is 1982736450",
            "National ID number: 1234567890",
            "User national identity no: 19901234567890123",
            "User's NID: 19851234567890123",
            "Old National ID is 1234567890123",
        ]
        for s in samples:
            self.assertTrue(contains_sensitive_data(s), f"Failed to detect NID: {s}")

    def test_sensitive_data_bangladesh_passport(self):
        """Test detection of Bangladesh passport identifiers."""
        samples = [
            "User passport number is A01234567",
            "Holder of passport EA0123456",
            "Bangladesh passport: EE0123456",
            "Passport no: B09876543",
        ]
        for s in samples:
            self.assertTrue(contains_sensitive_data(s), f"Failed to detect passport: {s}")

    def test_sensitive_data_emails_and_banking(self):
        """Test detection of email addresses, IBAN and bank account numbers."""
        samples = [
            "Contact user at developer@foja.ai",
            "Email: user.name+tag@company.com.bd",
            "User IBAN is BD12ABCD12345678901234",
            "Bank account number is 123456789012",
            "Routing no: 020261234",
            "Card security code: 456",
            "Card security code is 1234",
            "card security code is 1234",
            "security code is 123",
            "cvv is 123",
            "cvc is 456",
        ]
        for s in samples:
            self.assertTrue(contains_sensitive_data(s), f"Failed to detect email/bank: {s}")

    def test_sensitive_data_google_and_anthropic_api_keys(self):
        """Test detection of Google Cloud API keys and Anthropic API keys."""
        samples = [
            "Google API key is AIzaSyD-1234567890abcdefghijklmnopqrst",
            "Anthropic key is sk-ant-api03-abcdefghijklmnopqrstuvwxyz1234567890",
        ]
        for s in samples:
            self.assertTrue(contains_sensitive_data(s), f"Failed to detect API key: {s}")

    def test_sensitive_data_tightened_jwt(self):
        """Test detection of JWTs even with shorter signatures."""
        jwt_text = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.abcd"
        self.assertTrue(contains_sensitive_data(jwt_text))

    def test_sensitive_data_false_positive_resistance(self):
        """Test that ordinary numeric facts, ports, dates, and timestamps are NOT falsely rejected."""
        safe_samples = [
            "The server runs on port 8000.",
            "Model temperature is 0.7.",
            "Unix timestamp is 1731518400.",
            "The resolution is 1920x1080.",
            "File size is 49152 bytes.",
            "Bangladesh Independence Day is 26 March 1971.",
            "Process memory usage is 250 MB.",
            "API latency is 120 ms.",
            "User has 15 years of experience.",
            "Version is 2.4.4.2.",
            "Merged commit abc123def456.",
            "Total items in cart: 15.",
        ]
        for s in safe_samples:
            self.assertFalse(contains_sensitive_data(s), f"False positive detected on safe text: '{s}'")

    # --------------------------------------------------------------------------
    # 3. Candidate Filtering Before Database Insertion
    # --------------------------------------------------------------------------
    def test_sensitive_candidate_discarded_before_db(self):
        """Verify parser drops entire candidate containing sensitive data without altering it."""
        raw_output = json.dumps([
            {"content": "User phone number is +8801712345678", "category": "personal", "importance": 0.8},
            {"content": "User prefers dark mode UI.", "category": "preference", "importance": 0.9},
        ])
        candidates = parse_extraction_response(raw_output)
        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0].content, "User prefers dark mode UI.")

    # --------------------------------------------------------------------------
    # 4. Streaming Disconnect and Real ASGI Client Regression Tests
    # --------------------------------------------------------------------------
    async def test_real_asgi_streaming_success(self):
        """Verify real ASGI streaming request yields start, chunk, and done events."""
        async def mock_stream(*args, **kwargs):
            yield "Hello "
            yield "world!"

        with patch.object(settings, "MEMORY_EXTRACTION_ENABLED", True), \
             patch("app.api.chat.stream_chat_response", side_effect=mock_stream), \
             patch("app.api.chat.schedule_extraction_task") as mock_sched:

            resp = await self.client.post("/api/chat/stream", json={"message": "Hi"})
            self.assertEqual(resp.status_code, 200)
            self.assertIn('"type": "start"', resp.text)
            self.assertIn('"type": "chunk"', resp.text)
            self.assertIn('"type": "done"', resp.text)

            await asyncio.sleep(0.02)
            mock_sched.assert_called_once()

    async def test_real_asgi_streaming_ollama_failure_aborts_extraction(self):
        """Verify real ASGI streaming with Ollama error yields error event and skips extraction."""
        async def mock_failing_stream(*args, **kwargs):
            yield "Partial..."
            raise OllamaConnectionError("Ollama failed")

        with patch.object(settings, "MEMORY_EXTRACTION_ENABLED", True), \
             patch("app.api.chat.stream_chat_response", side_effect=mock_failing_stream), \
             patch("app.api.chat.schedule_extraction_task") as mock_sched:

            resp = await self.client.post("/api/chat/stream", json={"message": "Hi fail"})
            self.assertEqual(resp.status_code, 200)
            self.assertIn('"type": "error"', resp.text)

            await asyncio.sleep(0.02)
            mock_sched.assert_not_called()

    async def test_extraction_task_cancellation_rolls_back_cleanly(self):
        """Verify cancelling an in-flight extraction task rolls back and closes session."""
        async with TestSessionLocal() as session:
            conv = Conversation(title="Cancellation Rollback Test")
            session.add(conv)
            await session.commit()
            await session.refresh(conv)

            # Start extraction task and immediately cancel it
            with patch.object(settings, "MEMORY_EXTRACTION_ENABLED", True):
                task = asyncio.create_task(
                    run_memory_extraction_task(conv.id, "default_user", db=session)
                )
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass

            # Verify no corrupted memory was persisted
            total = (await session.execute(select(Memory).where(Memory.source_conversation_id == conv.id))).scalars().all()
            self.assertEqual(len(total), 0)
