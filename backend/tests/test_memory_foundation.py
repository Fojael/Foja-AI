import sys
from pathlib import Path

# Ensure backend directory is in sys.path
BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

import asyncio
from datetime import datetime, timezone, timedelta
import unittest
import uuid
from sqlalchemy import delete, event, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.auth import DEFAULT_OWNER_ID, get_current_owner_id
from app.core.database import Base, UTCDateTime
from app.models.chat import Conversation, Message
from app.models.memory import (
    Memory,
    MemoryCategory,
    MemoryStatus,
    compute_content_hash,
)


class TestMemoryFoundation(unittest.IsolatedAsyncioTestCase):
    """
    Focused verification suite for Phase 2.4.1 Backend Memory Foundation:
    - Ownership dependency & header non-trust
    - Custom UTCDateTime type & timezone awareness
    - SQLAlchemy Memory model schema, constraints & indexes
    - SQLite foreign-key enforcement & ON DELETE SET NULL
    - Idempotent schema initialization
    """

    async def asyncSetUp(self):
        # Create an isolated in-memory SQLite database for each test
        self.engine = create_async_engine(
            "sqlite+aiosqlite:///:memory:",
            echo=False,
            future=True,
        )

        # Register the identical SQLite foreign key pragma listener
        @event.listens_for(self.engine.sync_engine, "connect")
        def set_sqlite_pragma(dbapi_connection, connection_record):
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        self.session_factory = async_sessionmaker(
            bind=self.engine,
            class_=AsyncSession,
            expire_on_commit=False,
            autoflush=False,
        )

    async def asyncTearDown(self):
        await self.engine.dispose()

    # --------------------------------------------------------------------------
    # 1. Memory creation and retrieval
    # --------------------------------------------------------------------------
    async def test_memory_creation_and_retrieval(self):
        content = "The user prefers Python 3.13 and FastAPI."
        content_hash = compute_content_hash(content)

        async with self.session_factory() as session:
            mem = Memory(
                content=content,
                content_hash=content_hash,
                category=MemoryCategory.PREFERENCE.value,
                status=MemoryStatus.APPROVED.value,
                importance=0.8,
            )
            session.add(mem)
            await session.commit()
            mem_id = mem.id

        async with self.session_factory() as session:
            res = await session.execute(select(Memory).where(Memory.id == mem_id))
            retrieved = res.scalar_one_or_none()
            self.assertIsNotNone(retrieved)
            self.assertEqual(retrieved.content, content)
            self.assertEqual(retrieved.content_hash, content_hash)
            self.assertEqual(retrieved.category, "preference")
            self.assertEqual(retrieved.status, "approved")
            self.assertAlmostEqual(retrieved.importance, 0.8)
            self.assertFalse(retrieved.is_global)

    # --------------------------------------------------------------------------
    # 2. UUID generation
    # --------------------------------------------------------------------------
    async def test_uuid_generation(self):
        async with self.session_factory() as session:
            mem = Memory(
                content="Test UUID generation",
                content_hash=compute_content_hash("Test UUID generation"),
            )
            session.add(mem)
            await session.commit()
            mem_id = mem.id

        self.assertIsInstance(mem_id, str)
        self.assertEqual(len(mem_id), 36)
        # Verify valid RFC 4122 UUID format
        parsed_uuid = uuid.UUID(mem_id)
        self.assertEqual(str(parsed_uuid), mem_id)

    # --------------------------------------------------------------------------
    # 3. Default ownership
    # --------------------------------------------------------------------------
    async def test_default_ownership(self):
        async with self.session_factory() as session:
            mem = Memory(
                content="Default ownership test",
                content_hash=compute_content_hash("Default ownership test"),
            )
            session.add(mem)
            await session.commit()
            mem_id = mem.id

        async with self.session_factory() as session:
            retrieved = (await session.execute(select(Memory).where(Memory.id == mem_id))).scalar_one()
            self.assertEqual(retrieved.owner_id, DEFAULT_OWNER_ID)
            self.assertEqual(retrieved.owner_id, "default_user")

    # --------------------------------------------------------------------------
    # 4. UTC-aware timestamps after retrieval
    # --------------------------------------------------------------------------
    async def test_utc_aware_timestamps_after_retrieval(self):
        t_before = datetime.now(timezone.utc)
        async with self.session_factory() as session:
            mem = Memory(
                content="UTC timestamp validation",
                content_hash=compute_content_hash("UTC timestamp validation"),
            )
            session.add(mem)
            await session.commit()
            mem_id = mem.id

        async with self.session_factory() as session:
            retrieved = (await session.execute(select(Memory).where(Memory.id == mem_id))).scalar_one()

            # Assert timezone awareness
            self.assertIsNotNone(retrieved.created_at.tzinfo, "created_at must not be naive")
            self.assertIsNotNone(retrieved.updated_at.tzinfo, "updated_at must not be naive")

            # Assert UTC timezone explicitly
            self.assertEqual(retrieved.created_at.tzinfo, timezone.utc)
            self.assertEqual(retrieved.updated_at.tzinfo, timezone.utc)
            self.assertEqual(retrieved.created_at.utcoffset(), timedelta(0))
            self.assertEqual(retrieved.updated_at.utcoffset(), timedelta(0))

            # Assert chronological validity
            self.assertGreaterEqual(retrieved.created_at, t_before)

    # --------------------------------------------------------------------------
    # 5. Timestamp update behavior
    # --------------------------------------------------------------------------
    async def test_timestamp_update_behavior(self):
        async with self.session_factory() as session:
            mem = Memory(
                content="Initial content",
                content_hash=compute_content_hash("Initial content"),
            )
            session.add(mem)
            await session.commit()
            mem_id = mem.id
            created_at = mem.created_at

        # Sleep briefly to ensure clock advances
        await asyncio.sleep(0.05)

        async with self.session_factory() as session:
            m = (await session.execute(select(Memory).where(Memory.id == mem_id))).scalar_one()
            m.content = "Updated content"
            m.content_hash = compute_content_hash("Updated content")
            m.updated_at = datetime.now(timezone.utc)
            await session.commit()

        async with self.session_factory() as session:
            retrieved = (await session.execute(select(Memory).where(Memory.id == mem_id))).scalar_one()
            self.assertGreater(retrieved.updated_at, created_at)
            self.assertEqual(retrieved.updated_at.tzinfo, timezone.utc)

    # --------------------------------------------------------------------------
    # 6. Unique (owner_id, content_hash) enforcement
    # --------------------------------------------------------------------------
    async def test_unique_owner_content_hash_enforcement(self):
        content = "Prefers dark mode."
        c_hash = compute_content_hash(content)

        async with self.session_factory() as session:
            mem1 = Memory(
                owner_id="default_user",
                content=content,
                content_hash=c_hash,
            )
            session.add(mem1)
            await session.commit()

        # Same owner + same hash -> IntegrityError
        async with self.session_factory() as session:
            mem2 = Memory(
                owner_id="default_user",
                content=content,
                content_hash=c_hash,
            )
            session.add(mem2)
            with self.assertRaises(IntegrityError):
                await session.commit()

        # Different owner + same hash -> Allowed (multi-owner isolation)
        async with self.session_factory() as session:
            mem3 = Memory(
                owner_id="different_owner",
                content=content,
                content_hash=c_hash,
            )
            session.add(mem3)
            await session.commit()
            self.assertIsNotNone(mem3.id)

    # --------------------------------------------------------------------------
    # 7. Global instruction check constraint
    # --------------------------------------------------------------------------
    async def test_global_instruction_check_constraint(self):
        # Case A: is_global=True with category="instruction" -> SUCCEEDS
        async with self.session_factory() as session:
            valid_global = Memory(
                content="Always include type annotations",
                content_hash=compute_content_hash("Always include type annotations"),
                category="instruction",
                is_global=True,
            )
            session.add(valid_global)
            await session.commit()
            self.assertTrue(valid_global.is_global)

        # Case B: is_global=True with category="fact" -> FAILS with IntegrityError
        async with self.session_factory() as session:
            invalid_global = Memory(
                content="Operating system is Windows 11",
                content_hash=compute_content_hash("Operating system is Windows 11"),
                category="fact",
                is_global=True,
            )
            session.add(invalid_global)
            with self.assertRaises(IntegrityError):
                await session.commit()

        # Case C: is_global=False with any category -> SUCCEEDS
        async with self.session_factory() as session:
            normal_fact = Memory(
                content="Operating system is Windows 11",
                content_hash=compute_content_hash("Operating system is Windows 11 (normal)"),
                category="fact",
                is_global=False,
            )
            session.add(normal_fact)
            await session.commit()
            self.assertFalse(normal_fact.is_global)

    # --------------------------------------------------------------------------
    # 8. Foreign-key enforcement
    # --------------------------------------------------------------------------
    async def test_foreign_key_enforcement(self):
        # PRAGMA foreign_keys=ON must reject non-existent conversation_id
        async with self.session_factory() as session:
            bad_fk_mem = Memory(
                content="Bad foreign key test",
                content_hash=compute_content_hash("Bad foreign key test"),
                source_conversation_id="non-existent-conv-id-12345",
            )
            session.add(bad_fk_mem)
            with self.assertRaises(IntegrityError):
                await session.commit()

    # --------------------------------------------------------------------------
    # 9. Conversation deletion sets source_conversation_id to NULL
    # --------------------------------------------------------------------------
    async def test_conversation_deletion_sets_source_conversation_id_to_null(self):
        async with self.session_factory() as session:
            conv = Conversation(title="Temporary Conversation")
            session.add(conv)
            await session.commit()
            conv_id = conv.id

            mem = Memory(
                content="Memory linked to conversation",
                content_hash=compute_content_hash("Memory linked to conversation"),
                source_conversation_id=conv_id,
            )
            session.add(mem)
            await session.commit()
            mem_id = mem.id

        # Delete conversation
        async with self.session_factory() as session:
            target_conv = (await session.execute(select(Conversation).where(Conversation.id == conv_id))).scalar_one()
            await session.delete(target_conv)
            await session.commit()

        # Assert memory still exists and source_conversation_id is now NULL
        async with self.session_factory() as session:
            mem_after = (await session.execute(select(Memory).where(Memory.id == mem_id))).scalar_one_or_none()
            self.assertIsNotNone(mem_after, "Memory must NOT be deleted when conversation is deleted")
            self.assertIsNone(mem_after.source_conversation_id, "source_conversation_id must be set to NULL")

    # --------------------------------------------------------------------------
    # 10. Existing conversation and message records remain intact
    # --------------------------------------------------------------------------
    async def test_existing_conversation_and_message_records_intact(self):
        async with self.session_factory() as session:
            conv = Conversation(title="Chat Thread")
            session.add(conv)
            await session.flush()

            msg1 = Message(conversation_id=conv.id, role="user", content="Hello Foja")
            msg2 = Message(conversation_id=conv.id, role="assistant", content="Hello! How can I assist you?")
            session.add_all([msg1, msg2])
            await session.commit()

            conv_id = conv.id

        async with self.session_factory() as session:
            res = (await session.execute(select(Conversation).where(Conversation.id == conv_id))).scalar_one()
            self.assertEqual(len(res.messages), 2)
            self.assertEqual(res.messages[0].role, "user")
            self.assertEqual(res.messages[1].role, "assistant")

    # --------------------------------------------------------------------------
    # 11. Repeated database initialization does not create errors (Idempotency)
    # --------------------------------------------------------------------------
    async def test_repeated_database_initialization_idempotent(self):
        async with self.engine.begin() as conn:
            # Re-running create_all multiple times must be completely idempotent
            await conn.run_sync(Base.metadata.create_all)
            await conn.run_sync(Base.metadata.create_all)

        async with self.session_factory() as session:
            mem = Memory(
                content="Idempotency test memory",
                content_hash=compute_content_hash("Idempotency test memory"),
            )
            session.add(mem)
            await session.commit()
            self.assertIsNotNone(mem.id)

    # --------------------------------------------------------------------------
    # 12. Client headers cannot override the default owner dependency
    # --------------------------------------------------------------------------
    async def test_client_headers_cannot_override_default_owner(self):
        class MockRequest:
            headers = {
                "X-Foja-Owner-Id": "attacker_spoofed_user",
                "X-User-Id": "admin",
                "Authorization": "Bearer bogus-token",
            }

        # Verify dependency ignores client headers and returns DEFAULT_OWNER_ID
        owner = await get_current_owner_id(MockRequest())
        self.assertEqual(owner, DEFAULT_OWNER_ID)
        self.assertEqual(owner, "default_user")
        self.assertNotEqual(owner, "attacker_spoofed_user")


if __name__ == "__main__":
    unittest.main()
