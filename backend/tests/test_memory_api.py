import sys
from pathlib import Path

# Ensure backend directory is in sys.path
BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

import unittest
import uuid
import httpx
from sqlalchemy import event, select
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.auth import DEFAULT_OWNER_ID, get_current_owner_id
from app.core.database import Base, get_db
from app.main import app
from app.models.memory import Memory, MemoryCategory, MemoryStatus, compute_content_hash


# Isolated in-memory SQLite database for testing - Never touches real data
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


class TestMemoryAPI(unittest.IsolatedAsyncioTestCase):

    async def asyncSetUp(self):
        # Apply clean tables for each test
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
    # 1. Manual memory creation
    # --------------------------------------------------------------------------
    async def test_manual_memory_creation(self):
        payload = {
            "content": "User prefers dark mode and high-contrast UI.",
            "category": "preference",
            "importance": 0.85,
            "is_global": False
        }
        resp = await self.client.post("/api/memories", json=payload)
        self.assertEqual(resp.status_code, 201)
        data = resp.json()

        self.assertEqual(data["content"], payload["content"])
        self.assertEqual(data["category"], "preference")
        self.assertEqual(data["status"], "approved")  # Manually created memories are immediately approved
        self.assertEqual(data["importance"], 0.85)
        self.assertFalse(data["is_global"])
        self.assertEqual(data["owner_id"], DEFAULT_OWNER_ID)
        self.assertEqual(data["content_hash"], compute_content_hash(payload["content"]))
        self.assertIsNotNone(data["id"])
        self.assertIsNotNone(data["created_at"])
        self.assertIsNotNone(data["updated_at"])

    # --------------------------------------------------------------------------
    # 2. Listing memories
    # --------------------------------------------------------------------------
    async def test_list_memories(self):
        # Create 3 memories
        for i in range(3):
            await self.client.post("/api/memories", json={
                "content": f"Memory item #{i}",
                "category": "fact",
                "importance": 0.5
            })

        resp = await self.client.get("/api/memories")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["total"], 3)
        self.assertEqual(len(data["items"]), 3)
        self.assertEqual(data["limit"], 50)
        self.assertEqual(data["offset"], 0)

    # --------------------------------------------------------------------------
    # 3. Listing with filters
    # --------------------------------------------------------------------------
    async def test_list_memories_filters(self):
        # Add diverse items
        await self.client.post("/api/memories", json={"content": "Item A", "category": "preference", "importance": 0.9})
        await self.client.post("/api/memories", json={"content": "Item B", "category": "fact", "importance": 0.3})
        await self.client.post("/api/memories", json={"content": "Item C", "category": "instruction", "importance": 0.7, "is_global": True})

        # Insert a suggested memory directly via DB session
        async with TestSessionLocal() as session:
            sugg = Memory(
                owner_id=DEFAULT_OWNER_ID,
                content="Suggested item",
                content_hash=compute_content_hash("Suggested item"),
                category="project",
                status=MemoryStatus.SUGGESTED.value,
                importance=0.4
            )
            session.add(sugg)
            await session.commit()

        # Filter by status
        r_status = await self.client.get("/api/memories?status=suggested")
        self.assertEqual(r_status.status_code, 200)
        self.assertEqual(r_status.json()["total"], 1)
        self.assertEqual(r_status.json()["items"][0]["content"], "Suggested item")

        # Filter by category
        r_cat = await self.client.get("/api/memories?category=preference")
        self.assertEqual(r_cat.status_code, 200)
        self.assertEqual(r_cat.json()["total"], 1)
        self.assertEqual(r_cat.json()["items"][0]["content"], "Item A")

        # Filter by is_global
        r_glob = await self.client.get("/api/memories?is_global=true")
        self.assertEqual(r_glob.status_code, 200)
        self.assertEqual(r_glob.json()["total"], 1)
        self.assertEqual(r_glob.json()["items"][0]["content"], "Item C")

        # Filter by importance range
        r_imp = await self.client.get("/api/memories?min_importance=0.6&max_importance=0.8")
        self.assertEqual(r_imp.status_code, 200)
        self.assertEqual(r_imp.json()["total"], 1)
        self.assertEqual(r_imp.json()["items"][0]["content"], "Item C")

    # --------------------------------------------------------------------------
    # 4. Pagination
    # --------------------------------------------------------------------------
    async def test_pagination(self):
        for i in range(5):
            await self.client.post("/api/memories", json={"content": f"Paginated item {i}"})

        r_page1 = await self.client.get("/api/memories?limit=2&offset=0")
        self.assertEqual(r_page1.status_code, 200)
        d1 = r_page1.json()
        self.assertEqual(d1["total"], 5)
        self.assertEqual(len(d1["items"]), 2)
        self.assertEqual(d1["offset"], 0)
        self.assertEqual(d1["limit"], 2)

        r_page2 = await self.client.get("/api/memories?limit=2&offset=2")
        self.assertEqual(r_page2.status_code, 200)
        d2 = r_page2.json()
        self.assertEqual(d2["total"], 5)
        self.assertEqual(len(d2["items"]), 2)
        self.assertEqual(d2["offset"], 2)

        # Check disjoint items
        page1_ids = {item["id"] for item in d1["items"]}
        page2_ids = {item["id"] for item in d2["items"]}
        self.assertEqual(len(page1_ids.intersection(page2_ids)), 0)

    # --------------------------------------------------------------------------
    # 5. Retrieving a single memory
    # --------------------------------------------------------------------------
    async def test_retrieve_memory(self):
        create_resp = await self.client.post("/api/memories", json={"content": "Fetch me by ID"})
        mem_id = create_resp.json()["id"]

        resp = await self.client.get(f"/api/memories/{mem_id}")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["id"], mem_id)
        self.assertEqual(resp.json()["content"], "Fetch me by ID")

    # --------------------------------------------------------------------------
    # 6. Updating memory content and content hash recalculation
    # --------------------------------------------------------------------------
    async def test_update_memory_content_and_hash(self):
        c_resp = await self.client.post("/api/memories", json={"content": "Original Content"})
        mem_id = c_resp.json()["id"]
        old_hash = c_resp.json()["content_hash"]

        update_resp = await self.client.patch(f"/api/memories/{mem_id}", json={
            "content": "Newly Updated Content"
        })
        self.assertEqual(update_resp.status_code, 200)
        updated_data = update_resp.json()
        self.assertEqual(updated_data["content"], "Newly Updated Content")
        new_hash = compute_content_hash("Newly Updated Content")
        self.assertEqual(updated_data["content_hash"], new_hash)
        self.assertNotEqual(updated_data["content_hash"], old_hash)

    # --------------------------------------------------------------------------
    # 7. Updating importance and category
    # --------------------------------------------------------------------------
    async def test_update_importance_and_category(self):
        c_resp = await self.client.post("/api/memories", json={"content": "Change metadata"})
        mem_id = c_resp.json()["id"]

        update_resp = await self.client.patch(f"/api/memories/{mem_id}", json={
            "category": "project",
            "importance": 0.95
        })
        self.assertEqual(update_resp.status_code, 200)
        data = update_resp.json()
        self.assertEqual(data["category"], "project")
        self.assertEqual(data["importance"], 0.95)

    # --------------------------------------------------------------------------
    # 8. Invalid content validation
    # --------------------------------------------------------------------------
    async def test_invalid_content(self):
        # Empty string
        r1 = await self.client.post("/api/memories", json={"content": ""})
        self.assertEqual(r1.status_code, 422)

        # Whitespace-only
        r2 = await self.client.post("/api/memories", json={"content": "    \n   "})
        self.assertEqual(r2.status_code, 422)

        # Exceeds max length
        r3 = await self.client.post("/api/memories", json={"content": "x" * 2001})
        self.assertEqual(r3.status_code, 422)

    # --------------------------------------------------------------------------
    # 9. Invalid category and status validation
    # --------------------------------------------------------------------------
    async def test_invalid_category(self):
        r = await self.client.post("/api/memories", json={"content": "Valid", "category": "invalid_cat"})
        self.assertEqual(r.status_code, 422)

    # --------------------------------------------------------------------------
    # 10. Invalid importance validation
    # --------------------------------------------------------------------------
    async def test_invalid_importance(self):
        r_high = await self.client.post("/api/memories", json={"content": "Valid", "importance": 1.1})
        self.assertEqual(r_high.status_code, 422)

        r_low = await self.client.post("/api/memories", json={"content": "Valid", "importance": -0.1})
        self.assertEqual(r_low.status_code, 422)

    # --------------------------------------------------------------------------
    # 11. Global instruction validation
    # --------------------------------------------------------------------------
    async def test_global_instruction_validation(self):
        # Valid global instruction
        r_valid = await self.client.post("/api/memories", json={
            "content": "Always format code with standard spacing",
            "category": "instruction",
            "is_global": True
        })
        self.assertEqual(r_valid.status_code, 201)
        self.assertTrue(r_valid.json()["is_global"])

        # Invalid: is_global=True on non-instruction category
        r_invalid = await self.client.post("/api/memories", json={
            "content": "User has 8GB RAM",
            "category": "fact",
            "is_global": True
        })
        self.assertEqual(r_invalid.status_code, 422)

        # PATCH: attempting to set is_global=True on existing 'fact' record -> 422
        fact_resp = await self.client.post("/api/memories", json={"content": "Fact item", "category": "fact"})
        fact_id = fact_resp.json()["id"]

        r_patch_invalid = await self.client.patch(f"/api/memories/{fact_id}", json={"is_global": True})
        self.assertEqual(r_patch_invalid.status_code, 422)

        # PATCH: attempting to change category to 'preference' when is_global is True -> 422
        r_patch_cat = await self.client.patch(f"/api/memories/{r_valid.json()['id']}", json={"category": "preference"})
        self.assertEqual(r_patch_cat.status_code, 422)

    # --------------------------------------------------------------------------
    # 12. Duplicate memory conflict (HTTP 409)
    # --------------------------------------------------------------------------
    async def test_duplicate_memory_conflict(self):
        content = "Exact duplicate statement."
        r1 = await self.client.post("/api/memories", json={"content": content})
        self.assertEqual(r1.status_code, 201)

        # Duplicate submission with different casing and whitespace -> same content_hash -> 409
        r2 = await self.client.post("/api/memories", json={"content": "  EXACT   DUPLICATE STATEMENT.  "})
        self.assertEqual(r2.status_code, 409)
        self.assertIn("already exists", r2.json()["detail"])

        # PATCH collision test
        m2 = await self.client.post("/api/memories", json={"content": "Second different statement"})
        m2_id = m2.json()["id"]

        r_patch_dup = await self.client.patch(f"/api/memories/{m2_id}", json={"content": content})
        self.assertEqual(r_patch_dup.status_code, 409)

    # --------------------------------------------------------------------------
    # 13. Approving a suggested memory
    # --------------------------------------------------------------------------
    async def test_approve_suggested_memory(self):
        # Insert a suggested memory
        async with TestSessionLocal() as session:
            mem = Memory(
                owner_id=DEFAULT_OWNER_ID,
                content="Pending candidate to approve",
                content_hash=compute_content_hash("Pending candidate to approve"),
                status=MemoryStatus.SUGGESTED.value
            )
            session.add(mem)
            await session.commit()
            mem_id = mem.id

        resp = await self.client.post(f"/api/memories/{mem_id}/approve")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["status"], "approved")

    # --------------------------------------------------------------------------
    # 14. Rejecting a suggested memory
    # --------------------------------------------------------------------------
    async def test_reject_suggested_memory(self):
        async with TestSessionLocal() as session:
            mem = Memory(
                owner_id=DEFAULT_OWNER_ID,
                content="Pending candidate to reject",
                content_hash=compute_content_hash("Pending candidate to reject"),
                status=MemoryStatus.SUGGESTED.value
            )
            session.add(mem)
            await session.commit()
            mem_id = mem.id

        resp = await self.client.post(f"/api/memories/{mem_id}/reject")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["status"], "rejected")

    # --------------------------------------------------------------------------
    # 15. Invalid status transitions
    # --------------------------------------------------------------------------
    async def test_invalid_status_transitions(self):
        c_resp = await self.client.post("/api/memories", json={"content": "Already approved on create"})
        mem_id = c_resp.json()["id"]

        # Attempting to approve an already approved memory -> 400
        r_app = await self.client.post(f"/api/memories/{mem_id}/approve")
        self.assertEqual(r_app.status_code, 400)
        self.assertIn("already approved", r_app.json()["detail"])

        # Reject it
        r_rej1 = await self.client.post(f"/api/memories/{mem_id}/reject")
        self.assertEqual(r_rej1.status_code, 200)

        # Attempting to reject an already rejected memory -> 400
        r_rej2 = await self.client.post(f"/api/memories/{mem_id}/reject")
        self.assertEqual(r_rej2.status_code, 400)
        self.assertIn("already rejected", r_rej2.json()["detail"])

    # --------------------------------------------------------------------------
    # 16. Deleting one memory
    # --------------------------------------------------------------------------
    async def test_delete_one_memory(self):
        c_resp = await self.client.post("/api/memories", json={"content": "Delete me"})
        mem_id = c_resp.json()["id"]

        del_resp = await self.client.delete(f"/api/memories/{mem_id}")
        self.assertEqual(del_resp.status_code, 200)
        self.assertTrue(del_resp.json()["success"])
        self.assertEqual(del_resp.json()["id"], mem_id)

        # Verify 404 on subsequent get
        get_resp = await self.client.get(f"/api/memories/{mem_id}")
        self.assertEqual(get_resp.status_code, 404)

    # --------------------------------------------------------------------------
    # 17. Deleting approved memories in bulk
    # --------------------------------------------------------------------------
    async def test_delete_approved_memories_bulk(self):
        # 2 approved memories
        await self.client.post("/api/memories", json={"content": "Approved 1"})
        await self.client.post("/api/memories", json={"content": "Approved 2"})

        # 1 suggested memory
        async with TestSessionLocal() as session:
            sugg = Memory(
                owner_id=DEFAULT_OWNER_ID,
                content="Suggested survivor",
                content_hash=compute_content_hash("Suggested survivor"),
                status=MemoryStatus.SUGGESTED.value
            )
            session.add(sugg)
            await session.commit()

        # Call DELETE /api/memories/approved
        del_resp = await self.client.delete("/api/memories/approved")
        self.assertEqual(del_resp.status_code, 200)
        self.assertEqual(del_resp.json()["deleted_count"], 2)

        # Verify only suggested memory remains
        list_resp = await self.client.get("/api/memories?status=suggested")
        self.assertEqual(list_resp.json()["total"], 1)
        self.assertEqual(list_resp.json()["items"][0]["content"], "Suggested survivor")

        # Verify approved count is 0
        app_list = await self.client.get("/api/memories?status=approved")
        self.assertEqual(app_list.json()["total"], 0)

    # --------------------------------------------------------------------------
    # 18. Deleting all memories in bulk
    # --------------------------------------------------------------------------
    async def test_delete_all_memories_bulk(self):
        await self.client.post("/api/memories", json={"content": "Item 1"})
        await self.client.post("/api/memories", json={"content": "Item 2"})

        async with TestSessionLocal() as session:
            session.add(Memory(
                owner_id=DEFAULT_OWNER_ID,
                content="Item 3",
                content_hash=compute_content_hash("Item 3"),
                status=MemoryStatus.REJECTED.value
            ))
            await session.commit()

        del_all = await self.client.delete("/api/memories/all")
        self.assertEqual(del_all.status_code, 200)
        self.assertEqual(del_all.json()["deleted_count"], 3)

        list_resp = await self.client.get("/api/memories")
        self.assertEqual(list_resp.json()["total"], 0)

    # --------------------------------------------------------------------------
    # 19. Owner isolation
    # --------------------------------------------------------------------------
    async def test_owner_isolation(self):
        # Create memory under default_user
        c_resp = await self.client.post("/api/memories", json={"content": "Owner A secret"})
        mem_id = c_resp.json()["id"]

        # Switch owner to owner_b
        app.dependency_overrides[get_current_owner_id] = lambda: "owner_b"

        # Owner B lists memories -> 0 items
        list_resp = await self.client.get("/api/memories")
        self.assertEqual(list_resp.json()["total"], 0)

        # Owner B gets Owner A's memory -> 404
        get_resp = await self.client.get(f"/api/memories/{mem_id}")
        self.assertEqual(get_resp.status_code, 404)

        # Owner B attempts to patch -> 404
        patch_resp = await self.client.patch(f"/api/memories/{mem_id}", json={"content": "Hacked"})
        self.assertEqual(patch_resp.status_code, 404)

        # Owner B attempts to delete -> 404
        del_resp = await self.client.delete(f"/api/memories/{mem_id}")
        self.assertEqual(del_resp.status_code, 404)

        # Switch back to default_user
        app.dependency_overrides[get_current_owner_id] = lambda: DEFAULT_OWNER_ID
        owner_a_get = await self.client.get(f"/api/memories/{mem_id}")
        self.assertEqual(owner_a_get.status_code, 200)

    # --------------------------------------------------------------------------
    # 20. Client-supplied owner ID rejected/ignored
    # --------------------------------------------------------------------------
    async def test_client_supplied_owner_id_ignored(self):
        # Even if attacker sends owner_id in body or header, dependency dictates ownership
        payload = {
            "content": "Owner spoof test",
            "owner_id": "malicious_spoofed_user"  # Pydantic schema extra='ignore'
        }
        headers = {
            "X-Foja-Owner-Id": "malicious_header_owner",
            "X-User-Id": "admin"
        }
        resp = await self.client.post("/api/memories", json=payload, headers=headers)
        self.assertEqual(resp.status_code, 201)
        self.assertEqual(resp.json()["owner_id"], DEFAULT_OWNER_ID)
        self.assertNotEqual(resp.json()["owner_id"], "malicious_spoofed_user")
        self.assertNotEqual(resp.json()["owner_id"], "malicious_header_owner")

    # --------------------------------------------------------------------------
    # 21. Nonexistent and invalid UUID IDs return 404
    # --------------------------------------------------------------------------
    async def test_nonexistent_and_invalid_uuid(self):
        # Valid UUID but non-existent
        fake_uuid = str(uuid.uuid4())
        r1 = await self.client.get(f"/api/memories/{fake_uuid}")
        self.assertEqual(r1.status_code, 404)

        # Malformed non-UUID string
        r2 = await self.client.get("/api/memories/not-a-real-uuid")
        self.assertEqual(r2.status_code, 404)

    # --------------------------------------------------------------------------
    # 22. Existing conversation API regression
    # --------------------------------------------------------------------------
    async def test_existing_conversation_api_regression(self):
        # Verify /api/conversations still operates cleanly
        conv_resp = await self.client.post("/api/conversations", json={"title": "Test Chat"})
        self.assertEqual(conv_resp.status_code, 201)
        conv_id = conv_resp.json()["id"]

        list_resp = await self.client.get("/api/conversations")
        self.assertEqual(list_resp.status_code, 200)
        self.assertEqual(len(list_resp.json()), 1)

        health_resp = await self.client.get("/api/health")
        self.assertEqual(health_resp.status_code, 200)
        self.assertEqual(health_resp.json()["status"], "healthy")


if __name__ == "__main__":
    unittest.main()
