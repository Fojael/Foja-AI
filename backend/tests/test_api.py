import sys
from pathlib import Path

# Ensure backend directory is in sys.path
BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

import json
import unittest
from unittest.mock import patch
import httpx
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.database import Base, get_db
from app.main import app

# Isolated in-memory SQLite database for testing - Never touches real user data
TEST_DB_URL = "sqlite+aiosqlite:///:memory:"

test_engine = create_async_engine(
    TEST_DB_URL,
    echo=False,
    future=True,
)

TestSessionLocal = async_sessionmaker(
    bind=test_engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
)


async def override_get_db():
    """Dependency override providing isolated in-memory test session."""
    async with TestSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


class TestFojaAPI(unittest.IsolatedAsyncioTestCase):

    async def asyncSetUp(self):
        """Initialize in-memory schema and configure dependency overrides."""
        async with test_engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        app.dependency_overrides[get_db] = override_get_db
        self.transport = httpx.ASGITransport(app=app)
        self.client = httpx.AsyncClient(transport=self.transport, base_url="http://testserver")

    async def asyncTearDown(self):
        """Clean up database and client."""
        await self.client.aclose()
        app.dependency_overrides.clear()
        async with test_engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)

    # 1. Home endpoint test
    async def test_home_endpoint(self):
        response = await self.client.get("/")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data.get("assistant"), "Foja AI")
        self.assertEqual(data.get("status"), "running")

    # 2. Health endpoint test
    async def test_health_endpoint(self):
        response = await self.client.get("/api/health")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data.get("status"), "healthy")
        self.assertEqual(data.get("backend"), "FastAPI")

    # 3. Ollama status endpoint test
    async def test_ollama_status_endpoint(self):
        response = await self.client.get("/api/ollama/status")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn("connected", data)
        self.assertIn("default_model", data)

    # 4. Conversation creation test
    async def test_create_conversation(self):
        payload = {"title": "Test Coding Session"}
        response = await self.client.post("/api/conversations", json=payload)
        self.assertEqual(response.status_code, 201)
        data = response.json()
        self.assertEqual(data["title"], "Test Coding Session")
        self.assertIn("id", data)
        self.assertTrue(len(data["id"]) > 10)

    # 5. Invalid conversation ID test
    async def test_invalid_conversation_id(self):
        response = await self.client.get("/api/conversations/non-existent-uuid-12345")
        self.assertEqual(response.status_code, 404)
        data = response.json()
        self.assertIn("not found", data["detail"].lower())

    # 6. Chat endpoint: new conversation & message persistence
    @patch("app.api.chat.generate_chat_response")
    async def test_chat_creates_conversation_and_persists_messages(self, mock_ai):
        mock_ai.return_value = "Hello! I am Foja AI, how can I assist you?"

        chat_payload = {"message": "How do I build a desktop assistant?"}
        response = await self.client.post("/api/chat", json=chat_payload)
        self.assertEqual(response.status_code, 200)
        data = response.json()

        self.assertEqual(data["assistant"], "Foja AI")
        self.assertEqual(data["reply"], "Hello! I am Foja AI, how can I assist you?")
        self.assertIsNotNone(data.get("conversation_id"))
        self.assertIsNotNone(data.get("message_id"))

        # Verify conversation was persisted
        conv_id = data["conversation_id"]
        conv_res = await self.client.get(f"/api/conversations/{conv_id}")
        self.assertEqual(conv_res.status_code, 200)
        conv_data = conv_res.json()

        # Should have 2 messages: user and assistant
        self.assertEqual(len(conv_data["messages"]), 2)
        self.assertEqual(conv_data["messages"][0]["role"], "user")
        self.assertEqual(conv_data["messages"][0]["content"], "How do I build a desktop assistant?")
        self.assertEqual(conv_data["messages"][1]["role"], "assistant")
        self.assertEqual(conv_data["messages"][1]["content"], "Hello! I am Foja AI, how can I assist you?")

    # 7. Chat endpoint: continuing an existing conversation
    @patch("app.api.chat.generate_chat_response")
    async def test_chat_appends_to_existing_conversation(self, mock_ai):
        mock_ai.return_value = "Python with FastAPI is a great choice."

        # First create a conversation
        create_res = await self.client.post("/api/conversations", json={"title": "Tech Stack"})
        conv_id = create_res.json()["id"]

        # Send message to this conversation
        chat_payload = {
            "message": "Which backend should I use?",
            "conversation_id": conv_id
        }
        response = await self.client.post("/api/chat", json=chat_payload)
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["conversation_id"], conv_id)

        # Verify messages in conversation
        conv_res = await self.client.get(f"/api/conversations/{conv_id}")
        messages = conv_res.json()["messages"]
        self.assertEqual(len(messages), 2)
        self.assertEqual(messages[0]["content"], "Which backend should I use?")
        self.assertEqual(messages[1]["content"], "Python with FastAPI is a great choice.")

    # 8. Chat endpoint: invalid conversation ID error handling
    async def test_chat_invalid_conversation_id(self):
        chat_payload = {
            "message": "Hello",
            "conversation_id": "invalid-id-xyz"
        }
        response = await self.client.post("/api/chat", json=chat_payload)
        self.assertEqual(response.status_code, 404)
        self.assertIn("not found", response.json()["detail"].lower())

    # 9. Conversation history retrieval list
    async def test_list_conversations(self):
        # Create two conversations
        await self.client.post("/api/conversations", json={"title": "First"})
        await self.client.post("/api/conversations", json={"title": "Second"})

        response = await self.client.get("/api/conversations")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertGreaterEqual(len(data), 2)
        titles = [c["title"] for c in data]
        self.assertIn("First", titles)
        self.assertIn("Second", titles)

    # 10. Delete conversation
    async def test_delete_conversation(self):
        create_res = await self.client.post("/api/conversations", json={"title": "To Delete"})
        conv_id = create_res.json()["id"]

        del_res = await self.client.delete(f"/api/conversations/{conv_id}")
        self.assertEqual(del_res.status_code, 200)
        self.assertEqual(del_res.json()["status"], "deleted")

        # Verify it no longer exists
        get_res = await self.client.get(f"/api/conversations/{conv_id}")
        self.assertEqual(get_res.status_code, 404)

    # 11. Streaming: successful generation & SSE event sequence
    @patch("app.api.chat.stream_chat_response")
    async def test_chat_stream_success(self, mock_stream):
        async def fake_stream(*args, **kwargs):
            yield "Hello "
            yield "from "
            yield "real-time "
            yield "streaming!"

        mock_stream.side_effect = fake_stream

        payload = {"message": "Tell me about streaming"}
        response = await self.client.post("/api/chat/stream", json=payload)
        self.assertEqual(response.status_code, 200)
        self.assertIn("text/event-stream", response.headers.get("content-type", ""))

        events = []
        for part in response.text.split("\n\n"):
            part = part.strip()
            if part.startswith("data:"):
                events.append(json.loads(part[5:].strip()))

        # Check event sequence: start -> 4 chunks -> done
        self.assertGreaterEqual(len(events), 6)
        self.assertEqual(events[0]["type"], "start")
        conv_id = events[0]["conversation_id"]

        chunk_texts = [e["content"] for e in events if e["type"] == "chunk"]
        self.assertEqual("".join(chunk_texts), "Hello from real-time streaming!")

        done_event = events[-1]
        self.assertEqual(done_event["type"], "done")
        self.assertEqual(done_event["conversation_id"], conv_id)
        self.assertIsNotNone(done_event.get("message_id"))

        # Verify database persistence: both user message and completed assistant message exist
        conv_res = await self.client.get(f"/api/conversations/{conv_id}")
        self.assertEqual(conv_res.status_code, 200)
        messages = conv_res.json()["messages"]
        self.assertEqual(len(messages), 2)
        self.assertEqual(messages[0]["role"], "user")
        self.assertEqual(messages[0]["content"], "Tell me about streaming")
        self.assertEqual(messages[1]["role"], "assistant")
        self.assertEqual(messages[1]["content"], "Hello from real-time streaming!")

    # 12. Streaming: into an existing conversation
    @patch("app.api.chat.stream_chat_response")
    async def test_chat_stream_existing_conversation(self, mock_stream):
        async def fake_stream(*args, **kwargs):
            yield "Streamed "
            yield "answer."

        mock_stream.side_effect = fake_stream

        create_res = await self.client.post("/api/conversations", json={"title": "Streaming Thread"})
        conv_id = create_res.json()["id"]

        payload = {
            "message": "Next question in stream",
            "conversation_id": conv_id
        }
        response = await self.client.post("/api/chat/stream", json=payload)
        self.assertEqual(response.status_code, 200)

        events = [
            json.loads(p[5:].strip())
            for p in response.text.split("\n\n")
            if p.strip().startswith("data:")
        ]
        self.assertEqual(events[0]["type"], "start")
        self.assertEqual(events[0]["conversation_id"], conv_id)
        self.assertEqual(events[-1]["type"], "done")

        # Verify DB has user + assistant
        conv_res = await self.client.get(f"/api/conversations/{conv_id}")
        messages = conv_res.json()["messages"]
        self.assertEqual(len(messages), 2)
        self.assertEqual(messages[1]["content"], "Streamed answer.")

    # 13. Streaming: invalid conversation ID returns HTTP 404
    async def test_chat_stream_invalid_conversation_id(self):
        payload = {
            "message": "Hello",
            "conversation_id": "non-existent-conv-id-999"
        }
        response = await self.client.post("/api/chat/stream", json=payload)
        self.assertEqual(response.status_code, 404)
        self.assertIn("not found", response.json()["detail"].lower())

    # 14. Streaming: Ollama error during generation yields safe error event and preserves user message
    @patch("app.api.chat.stream_chat_response")
    async def test_chat_stream_ollama_error_handling(self, mock_stream):
        from app.services.ai.ollama import OllamaConnectionError

        async def failing_stream(*args, **kwargs):
            if False:
                yield ""
            raise OllamaConnectionError("Connection to Ollama refused.")

        mock_stream.side_effect = failing_stream

        payload = {"message": "Will fail"}
        response = await self.client.post("/api/chat/stream", json=payload)
        self.assertEqual(response.status_code, 200)

        events = [
            json.loads(p[5:].strip())
            for p in response.text.split("\n\n")
            if p.strip().startswith("data:")
        ]

        # Should have start event, then error event
        self.assertEqual(events[0]["type"], "start")
        conv_id = events[0]["conversation_id"]
        self.assertEqual(events[-1]["type"], "error")
        self.assertIn("Connection to Ollama refused", events[-1]["detail"])

        # Crucial check: User message is PRESERVED in SQLite, but no failed assistant message was saved
        conv_res = await self.client.get(f"/api/conversations/{conv_id}")
        self.assertEqual(conv_res.status_code, 200)
        messages = conv_res.json()["messages"]
        self.assertEqual(len(messages), 1)
        self.assertEqual(messages[0]["role"], "user")
        self.assertEqual(messages[0]["content"], "Will fail")


if __name__ == "__main__":
    unittest.main()

