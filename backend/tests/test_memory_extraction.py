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
from pydantic import ValidationError
from sqlalchemy import event, select
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.auth import DEFAULT_OWNER_ID, get_current_owner_id
from app.core.config import Settings, settings
from app.core.database import Base, get_db
from app.main import app
from app.models.chat import Conversation, Message
from app.models.memory import (
    Memory,
    MemoryCategory,
    MemoryStatus,
    compute_content_hash,
)
from app.services.ai.ollama import OllamaConnectionError
from app.services.memory.extraction import (
    CandidateMemoryItem,
    contains_sensitive_data,
    extract_candidates_from_conversation,
    parse_extraction_response,
    run_memory_extraction_task,
    save_extracted_candidates,
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


class TestMemoryExtraction(unittest.IsolatedAsyncioTestCase):

    async def asyncSetUp(self):
        async with test_engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
            await conn.run_sync(Base.metadata.create_all)

        app.dependency_overrides[get_db] = override_get_db
        self.transport = httpx.ASGITransport(app=app)
        self.client = httpx.AsyncClient(transport=self.transport, base_url="http://test")

    async def asyncTearDown(self):
        await self.client.aclose()
        app.dependency_overrides.clear()
        async with test_engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)

    # --------------------------------------------------------------------------
    # 1. Configuration Defaults and Validators
    # --------------------------------------------------------------------------
    def test_default_extraction_settings(self):
        """Verify default extraction settings match architecture requirements."""
        self.assertFalse(settings.MEMORY_EXTRACTION_ENABLED)
        self.assertEqual(settings.MEMORY_EXTRACTION_MAX_CANDIDATES, 3)
        self.assertEqual(settings.MEMORY_EXTRACTION_MAX_MESSAGES, 10)
        self.assertEqual(settings.MEMORY_EXTRACTION_MAX_CONTENT_LENGTH, 500)

    def test_config_validators_max_candidates(self):
        """Test bounds validation for MEMORY_EXTRACTION_MAX_CANDIDATES (1-10)."""
        valid_low = Settings(MEMORY_EXTRACTION_MAX_CANDIDATES=1)
        self.assertEqual(valid_low.MEMORY_EXTRACTION_MAX_CANDIDATES, 1)

        valid_high = Settings(MEMORY_EXTRACTION_MAX_CANDIDATES=10)
        self.assertEqual(valid_high.MEMORY_EXTRACTION_MAX_CANDIDATES, 10)

        with self.assertRaises(ValidationError):
            Settings(MEMORY_EXTRACTION_MAX_CANDIDATES=0)

        with self.assertRaises(ValidationError):
            Settings(MEMORY_EXTRACTION_MAX_CANDIDATES=11)

    def test_config_validators_max_messages(self):
        """Test bounds validation for MEMORY_EXTRACTION_MAX_MESSAGES (2-50)."""
        valid_low = Settings(MEMORY_EXTRACTION_MAX_MESSAGES=2)
        self.assertEqual(valid_low.MEMORY_EXTRACTION_MAX_MESSAGES, 2)

        valid_high = Settings(MEMORY_EXTRACTION_MAX_MESSAGES=50)
        self.assertEqual(valid_high.MEMORY_EXTRACTION_MAX_MESSAGES, 50)

        with self.assertRaises(ValidationError):
            Settings(MEMORY_EXTRACTION_MAX_MESSAGES=1)

        with self.assertRaises(ValidationError):
            Settings(MEMORY_EXTRACTION_MAX_MESSAGES=51)

    def test_config_validators_max_content_length(self):
        """Test bounds validation for MEMORY_EXTRACTION_MAX_CONTENT_LENGTH (50-2000)."""
        valid_low = Settings(MEMORY_EXTRACTION_MAX_CONTENT_LENGTH=50)
        self.assertEqual(valid_low.MEMORY_EXTRACTION_MAX_CONTENT_LENGTH, 50)

        valid_high = Settings(MEMORY_EXTRACTION_MAX_CONTENT_LENGTH=2000)
        self.assertEqual(valid_high.MEMORY_EXTRACTION_MAX_CONTENT_LENGTH, 2000)

        with self.assertRaises(ValidationError):
            Settings(MEMORY_EXTRACTION_MAX_CONTENT_LENGTH=49)

        with self.assertRaises(ValidationError):
            Settings(MEMORY_EXTRACTION_MAX_CONTENT_LENGTH=2001)

    # --------------------------------------------------------------------------
    # 2. Candidate Memory Item Schema Validation
    # --------------------------------------------------------------------------
    def test_candidate_item_schema_valid(self):
        """Test CandidateMemoryItem normalization of content, category, and importance."""
        item = CandidateMemoryItem(
            content="   User prefers   FastAPI for backend   services.   ",
            category="preference",
            importance=0.85
        )
        self.assertEqual(item.content, "User prefers FastAPI for backend services.")
        self.assertEqual(item.category, "preference")
        self.assertEqual(item.importance, 0.85)

        # Context category maps to fact
        item_ctx = CandidateMemoryItem(
            content="User is running Python 3.13 on Windows 11.",
            category="context",
            importance=0.9
        )
        self.assertEqual(item_ctx.category, "fact")

        # Unknown category defaults to fact
        item_unknown = CandidateMemoryItem(
            content="User prefers dark theme.",
            category="custom_unsupported",
            importance=0.5
        )
        self.assertEqual(item_unknown.category, "fact")

    def test_candidate_item_schema_invalid_content(self):
        """Test that blank content or content exceeding max length raises ValidationError."""
        with self.assertRaises(ValidationError):
            CandidateMemoryItem(content="   ", category="fact")

        with self.assertRaises(ValidationError):
            CandidateMemoryItem(
                content="x" * (settings.MEMORY_EXTRACTION_MAX_CONTENT_LENGTH + 1),
                category="fact"
            )

    # --------------------------------------------------------------------------
    # 3. Parsing and Formatting
    # --------------------------------------------------------------------------
    def test_parse_clean_json_array(self):
        """Test parsing a valid JSON array into CandidateMemoryItem objects."""
        raw = json.dumps([
            {"content": "User prefers concise code.", "category": "preference", "importance": 0.8},
            {"content": "User works with SQLite and PostgreSQL.", "category": "fact", "importance": 0.7}
        ])
        candidates = parse_extraction_response(raw)
        self.assertEqual(len(candidates), 2)
        self.assertEqual(candidates[0].content, "User prefers concise code.")
        self.assertEqual(candidates[0].category, "preference")
        self.assertEqual(candidates[1].category, "fact")

    def test_parse_markdown_codeblock_json(self):
        """Test parsing JSON wrapped in markdown code fence."""
        raw = """```json
[
  {"content": "User prefers pytest for unit tests.", "category": "preference", "importance": 0.75}
]
```"""
        candidates = parse_extraction_response(raw)
        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0].content, "User prefers pytest for unit tests.")

    def test_parse_surrounding_text_json(self):
        """Test extracting JSON array when surrounded by explanatory conversational text."""
        raw = """Here are the extracted memories from the user conversation:
[
  {"content": "User is building a desktop app called Foja AI.", "category": "project", "importance": 0.9}
]
Hope that helps!"""
        candidates = parse_extraction_response(raw)
        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0].content, "User is building a desktop app called Foja AI.")
        self.assertEqual(candidates[0].category, "project")

    def test_parse_malformed_json_returns_empty(self):
        """Test that malformed JSON safely returns an empty list without raising."""
        malformed = "[{'content': 'missing closing bracket'..."
        candidates = parse_extraction_response(malformed)
        self.assertEqual(candidates, [])

    def test_parse_non_list_json_returns_empty(self):
        """Test that a JSON object instead of an array returns an empty list."""
        not_a_list = json.dumps({"content": "This is an object not a list"})
        candidates = parse_extraction_response(not_a_list)
        self.assertEqual(candidates, [])

    def test_parse_empty_or_whitespace_returns_empty(self):
        """Test that empty or whitespace strings safely return empty lists."""
        self.assertEqual(parse_extraction_response(""), [])
        self.assertEqual(parse_extraction_response("   \n\t  "), [])

    # --------------------------------------------------------------------------
    # 4. Sensitive Data Filtering
    # --------------------------------------------------------------------------
    def test_sensitive_data_detection_api_keys(self):
        """Test detection and filtering of OpenAI, GitHub, and AWS API keys."""
        openai_key = "User API key is sk-abcdef12345678901234567890123456"
        github_token = "User token is ghp_1234567890abcdefghijklmnopqrstuv"
        aws_key = "User AWS key is AKIAIOSFODNN7EXAMPLE"

        self.assertTrue(contains_sensitive_data(openai_key))
        self.assertTrue(contains_sensitive_data(github_token))
        self.assertTrue(contains_sensitive_data(aws_key))

        # Ensure parser discards candidate containing an API key
        raw = json.dumps([{"content": openai_key, "category": "fact", "importance": 0.5}])
        self.assertEqual(parse_extraction_response(raw), [])

    def test_sensitive_data_detection_passwords_and_tokens(self):
        """Test detection and filtering of password assignments and bearer tokens."""
        pwd_text = "User set password = MySuperSecret123!"
        bearer_text = "Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.doNotStoreThis"
        priv_key = "-----BEGIN RSA PRIVATE KEY-----\nMIIEowIBAAKCAQEA0...\n-----END RSA PRIVATE KEY-----"

        self.assertTrue(contains_sensitive_data(pwd_text))
        self.assertTrue(contains_sensitive_data(bearer_text))
        self.assertTrue(contains_sensitive_data(priv_key))

        raw = json.dumps([
            {"content": pwd_text, "category": "fact", "importance": 0.5},
            {"content": bearer_text, "category": "fact", "importance": 0.5},
        ])
        self.assertEqual(parse_extraction_response(raw), [])

    def test_sensitive_data_detection_pii(self):
        """Test detection and filtering of credit cards and SSNs."""
        cc_text = "User credit card is 4532-1234-5678-9012"
        ssn_text = "User SSN is 123-45-6789"

        self.assertTrue(contains_sensitive_data(cc_text))
        self.assertTrue(contains_sensitive_data(ssn_text))

        raw = json.dumps([{"content": cc_text, "category": "personal", "importance": 0.5}])
        self.assertEqual(parse_extraction_response(raw), [])

    def test_sensitive_data_safe_normal_content(self):
        """Test that normal, benign user preferences and facts pass sensitive data checks."""
        safe_texts = [
            "User prefers Python 3.13 for all backend microservices.",
            "User lives in Dhaka, Bangladesh.",
            "User likes concise architectural diagrams.",
            "User works on Windows 11 with PowerShell.",
        ]
        for text in safe_texts:
            self.assertFalse(contains_sensitive_data(text))

    # --------------------------------------------------------------------------
    # 5. Deduplication and Max Candidates Enforcement
    # --------------------------------------------------------------------------
    def test_intra_batch_deduplication(self):
        """Test that duplicate candidates in the same extraction output are deduplicated."""
        raw = json.dumps([
            {"content": "User prefers dark mode UI.", "category": "preference", "importance": 0.8},
            {"content": "  USER PREFERS DARK MODE UI.  ", "category": "preference", "importance": 0.7},
            {"content": "User uses Windows 11.", "category": "fact", "importance": 0.9},
        ])
        candidates = parse_extraction_response(raw)
        self.assertEqual(len(candidates), 2)
        self.assertEqual(candidates[0].content, "User prefers dark mode UI.")
        self.assertEqual(candidates[1].content, "User uses Windows 11.")

    def test_max_candidates_limit_enforcement(self):
        """Test that extracted candidates are capped at settings.MEMORY_EXTRACTION_MAX_CANDIDATES."""
        raw = json.dumps([
            {"content": f"User preference number {i}", "category": "preference", "importance": 0.5}
            for i in range(10)
        ])
        with patch.object(settings, "MEMORY_EXTRACTION_MAX_CANDIDATES", 2):
            candidates = parse_extraction_response(raw)
            self.assertEqual(len(candidates), 2)

    # --------------------------------------------------------------------------
    # 6. Database Duplicate Suppression (Approved, Suggested, Rejected)
    # --------------------------------------------------------------------------
    async def test_db_duplicate_suppression_approved_memory(self):
        """Test that an existing approved memory suppresses proposing a duplicate candidate."""
        async with TestSessionLocal() as session:
            conv = Conversation(title="Approved Dup Test")
            session.add(conv)
            await session.commit()
            await session.refresh(conv)

            # Seed an approved memory
            existing_mem = Memory(
                owner_id=DEFAULT_OWNER_ID,
                content="User prefers PostgreSQL over MySQL.",
                content_hash=compute_content_hash("User prefers PostgreSQL over MySQL."),
                category="preference",
                status=MemoryStatus.APPROVED.value,
                importance=0.8,
                is_global=False,
                source_conversation_id=conv.id,
            )
            session.add(existing_mem)
            await session.commit()

            # Candidate with matching normalized content
            candidates = [
                CandidateMemoryItem(
                    content="  user prefers postgresql over mysql.  ",
                    category="preference",
                    importance=0.8
                )
            ]
            saved = await save_extracted_candidates(
                candidates=candidates,
                conversation_id=conv.id,
                owner_id=DEFAULT_OWNER_ID,
                db=session,
            )
            self.assertEqual(saved, [])

            # Verify total count in DB remains 1
            total = (await session.execute(select(Memory))).scalars().all()
            self.assertEqual(len(total), 1)

    async def test_db_duplicate_suppression_suggested_memory(self):
        """Test that an existing suggested memory suppresses duplicate suggestions."""
        async with TestSessionLocal() as session:
            conv = Conversation(title="Suggested Dup Test")
            session.add(conv)
            await session.commit()
            await session.refresh(conv)

            existing_mem = Memory(
                owner_id=DEFAULT_OWNER_ID,
                content="User is learning Rust.",
                content_hash=compute_content_hash("User is learning Rust."),
                category="personal",
                status=MemoryStatus.SUGGESTED.value,
                importance=0.6,
                is_global=False,
                source_conversation_id=conv.id,
            )
            session.add(existing_mem)
            await session.commit()

            candidates = [
                CandidateMemoryItem(
                    content="User is learning Rust.",
                    category="personal",
                    importance=0.6
                )
            ]
            saved = await save_extracted_candidates(
                candidates=candidates,
                conversation_id=conv.id,
                owner_id=DEFAULT_OWNER_ID,
                db=session,
            )
            self.assertEqual(saved, [])

    async def test_db_duplicate_suppression_rejected_memory(self):
        """Test that a previously rejected memory suppresses duplicate re-suggestions."""
        async with TestSessionLocal() as session:
            conv = Conversation(title="Rejected Dup Test")
            session.add(conv)
            await session.commit()
            await session.refresh(conv)

            existing_mem = Memory(
                owner_id=DEFAULT_OWNER_ID,
                content="User dislikes dark coffee.",
                content_hash=compute_content_hash("User dislikes dark coffee."),
                category="preference",
                status=MemoryStatus.REJECTED.value,
                importance=0.5,
                is_global=False,
                source_conversation_id=conv.id,
            )
            session.add(existing_mem)
            await session.commit()

            candidates = [
                CandidateMemoryItem(
                    content="User dislikes dark coffee.",
                    category="preference",
                    importance=0.5
                )
            ]
            saved = await save_extracted_candidates(
                candidates=candidates,
                conversation_id=conv.id,
                owner_id=DEFAULT_OWNER_ID,
                db=session,
            )
            self.assertEqual(saved, [])

    async def test_owner_isolation_in_deduplication(self):
        """Test that duplicate suppression is strictly scoped to owner_id."""
        async with TestSessionLocal() as session:
            conv = Conversation(title="Isolation Test Conv")
            session.add(conv)
            await session.commit()
            await session.refresh(conv)

            # Memory exists for other_user
            existing_mem = Memory(
                owner_id="other_user",
                content="User works on Windows 11.",
                content_hash=compute_content_hash("User works on Windows 11."),
                category="fact",
                status=MemoryStatus.APPROVED.value,
                importance=0.9,
                is_global=False,
                source_conversation_id=conv.id,
            )
            session.add(existing_mem)
            await session.commit()

            # Now propose the same content for default_user
            candidates = [
                CandidateMemoryItem(
                    content="User works on Windows 11.",
                    category="fact",
                    importance=0.9
                )
            ]
            saved = await save_extracted_candidates(
                candidates=candidates,
                conversation_id=conv.id,
                owner_id=DEFAULT_OWNER_ID,
                db=session,
            )
            self.assertEqual(len(saved), 1)
            self.assertEqual(saved[0].owner_id, DEFAULT_OWNER_ID)
            self.assertEqual(saved[0].status, MemoryStatus.SUGGESTED.value)

    # --------------------------------------------------------------------------
    # 7. Candidate Persistence Properties
    # --------------------------------------------------------------------------
    async def test_save_candidates_properties(self):
        """Verify saved candidate has status='suggested', is_global=False, and correct source_conversation_id."""
        async with TestSessionLocal() as session:
            conv = Conversation(title="Test Extraction Conv")
            session.add(conv)
            await session.commit()
            await session.refresh(conv)

            candidates = [
                CandidateMemoryItem(
                    content="User prefers tabs over spaces.",
                    category="preference",
                    importance=0.72
                )
            ]

            saved = await save_extracted_candidates(
                candidates=candidates,
                conversation_id=conv.id,
                owner_id=DEFAULT_OWNER_ID,
                db=session,
            )
            self.assertEqual(len(saved), 1)
            mem = saved[0]

            self.assertEqual(mem.status, MemoryStatus.SUGGESTED.value)
            self.assertFalse(mem.is_global)
            self.assertEqual(mem.source_conversation_id, conv.id)
            self.assertEqual(mem.owner_id, DEFAULT_OWNER_ID)
            self.assertEqual(mem.category, "preference")
            self.assertEqual(mem.importance, 0.72)
            self.assertEqual(mem.content, "User prefers tabs over spaces.")

    # --------------------------------------------------------------------------
    # 8. Extraction Runner and Error Resilience
    # --------------------------------------------------------------------------
    async def test_run_extraction_task_disabled(self):
        """Test that task returns empty list immediately when MEMORY_EXTRACTION_ENABLED is False."""
        with patch.object(settings, "MEMORY_EXTRACTION_ENABLED", False):
            res = await run_memory_extraction_task("conv_any", owner_id=DEFAULT_OWNER_ID)
            self.assertEqual(res, [])

    async def test_run_extraction_ollama_failure_handled_gracefully(self):
        """Test that Ollama connection failure is handled safely without raising unhandled exceptions."""
        async with TestSessionLocal() as session:
            conv = Conversation(title="Error Test Conv")
            session.add(conv)
            await session.flush()

            msg1 = Message(conversation_id=conv.id, role="user", content="I prefer FastAPI.")
            msg2 = Message(conversation_id=conv.id, role="assistant", content="Great choice!")
            session.add_all([msg1, msg2])
            await session.commit()

            with patch.object(settings, "MEMORY_EXTRACTION_ENABLED", True), \
                 patch("app.services.memory.extraction.generate_chat_response", side_effect=OllamaConnectionError("Ollama is down")):
                res = await run_memory_extraction_task(conv.id, owner_id=DEFAULT_OWNER_ID, db=session)
                self.assertEqual(res, [])

    async def test_run_extraction_task_no_user_messages(self):
        """Test that conversations with no user messages return empty list without calling Ollama."""
        async with TestSessionLocal() as session:
            conv = Conversation(title="System Only Conv")
            session.add(conv)
            await session.flush()

            msg = Message(conversation_id=conv.id, role="system", content="System initialization.")
            session.add(msg)
            await session.commit()

            with patch.object(settings, "MEMORY_EXTRACTION_ENABLED", True), \
                 patch("app.services.memory.extraction.generate_chat_response") as mock_gen:
                res = await run_memory_extraction_task(conv.id, owner_id=DEFAULT_OWNER_ID, db=session)
                self.assertEqual(res, [])
                mock_gen.assert_not_called()

    # --------------------------------------------------------------------------
    # 9. API Chat Integration: Non-Streaming
    # --------------------------------------------------------------------------
    async def test_chat_non_streaming_triggers_extraction_when_enabled(self):
        """Test that non-streaming chat triggers schedule_extraction_task when enabled."""
        mock_reply = "I noted that you prefer FastAPI."
        with patch.object(settings, "MEMORY_EXTRACTION_ENABLED", True), \
             patch("app.api.chat.generate_chat_response", return_value=mock_reply), \
             patch("app.api.chat.schedule_extraction_task") as mock_task:

            resp = await self.client.post("/api/chat", json={"message": "I prefer FastAPI."})
            self.assertEqual(resp.status_code, 200)

            # Allow any spawned event loop tasks to run
            await asyncio.sleep(0.05)
            mock_task.assert_called_once()
            call_kwargs = mock_task.call_args.kwargs
            self.assertEqual(call_kwargs["owner_id"], DEFAULT_OWNER_ID)
            self.assertTrue(bool(call_kwargs["conversation_id"]))

    async def test_chat_non_streaming_does_not_trigger_extraction_when_disabled(self):
        """Test that non-streaming chat does not trigger extraction when disabled."""
        mock_reply = "Hello there!"
        with patch.object(settings, "MEMORY_EXTRACTION_ENABLED", False), \
             patch("app.api.chat.generate_chat_response", return_value=mock_reply), \
             patch("app.api.chat.schedule_extraction_task") as mock_task:

            resp = await self.client.post("/api/chat", json={"message": "Hello!"})
            self.assertEqual(resp.status_code, 200)

            await asyncio.sleep(0.05)
            mock_task.assert_not_called()

    # --------------------------------------------------------------------------
    # 10. API Chat Integration: Streaming
    # --------------------------------------------------------------------------
    async def test_chat_streaming_triggers_extraction_on_done(self):
        """Test that streaming chat triggers extraction upon complete successful stream."""
        async def mock_stream(*args, **kwargs):
            yield "Hello "
            yield "world!"

        with patch.object(settings, "MEMORY_EXTRACTION_ENABLED", True), \
             patch("app.api.chat.stream_chat_response", side_effect=mock_stream), \
             patch("app.api.chat.schedule_extraction_task") as mock_task:

            resp = await self.client.post("/api/chat/stream", json={"message": "Stream hello"})
            self.assertEqual(resp.status_code, 200)
            body = resp.text
            self.assertIn('"type": "done"', body)

            await asyncio.sleep(0.05)
            mock_task.assert_called_once()
            call_kwargs = mock_task.call_args.kwargs
            self.assertEqual(call_kwargs["owner_id"], DEFAULT_OWNER_ID)

    async def test_chat_streaming_does_not_trigger_extraction_on_stream_error(self):
        """Test that streaming chat does not trigger extraction when stream raises an error."""
        async def mock_failing_stream(*args, **kwargs):
            yield "Starting..."
            raise OllamaConnectionError("Connection lost during streaming.")

        with patch.object(settings, "MEMORY_EXTRACTION_ENABLED", True), \
             patch("app.api.chat.stream_chat_response", side_effect=mock_failing_stream), \
             patch("app.api.chat.schedule_extraction_task") as mock_task:

            resp = await self.client.post("/api/chat/stream", json={"message": "Fail stream"})
            self.assertEqual(resp.status_code, 200)
            body = resp.text
            self.assertIn('"type": "error"', body)

            await asyncio.sleep(0.05)
            mock_task.assert_not_called()
