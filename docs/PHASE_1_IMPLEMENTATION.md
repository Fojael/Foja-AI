# Foja AI — Phase 1 Backend Foundation Implementation

## Overview
Foja AI is a modern personal AI desktop assistant for Windows 11. Phase 1 establishes the robust, modular backend foundation using **Python 3.13**, **FastAPI**, **SQLAlchemy 2.0 (asyncio)**, **aiosqlite**, and local **Ollama** integration.

---

## 1. Environment & Installation

### Prerequisites
- Windows 11
- Python 3.13.6 (64-bit)
- Ollama (installed with `llama3.2:1b` pulled: `ollama pull llama3.2:1b`)

### Virtual Environment Setup
From the project root (`D:\vercity class\Python+django\foja_ai`):

```powershell
# Create virtual environment with Python 3.13 (if not already created)
py -3.13 -m venv backend\.venv

# Activate virtual environment
.\backend\.venv\Scripts\Activate.ps1

# Install pinned dependencies
pip install -r backend\requirements.txt
```

### Environment Configuration
Copy `backend/.env.example` to `backend/.env` to configure custom ports, models, or database paths if desired:

```bash
cp backend/.env.example backend/.env
```

Default settings:
- **Application:** `Foja AI` (v0.1.0)
- **Database URL:** `sqlite+aiosqlite:///../data/foja.db`
- **Ollama URL:** `http://127.0.0.1:11434`
- **Ollama Model:** `llama3.2:1b`
- **API Timeout:** `120.0s`

---

## 2. Database Architecture

Database tables are located at `data/foja.db` using an asynchronous SQLite engine powered by `aiosqlite` and `greenlet`.

### Schema Models

#### `conversations` Table
| Column | Type | Constraints | Description |
| :--- | :--- | :--- | :--- |
| `id` | `VARCHAR(36)` | Primary Key | UUID string |
| `title` | `VARCHAR(255)` | Not Null | Auto-derived or custom title |
| `created_at` | `DATETIME` | UTC Timestamp | Creation timestamp |
| `updated_at` | `DATETIME` | UTC Timestamp | Last updated timestamp |

#### `messages` Table
| Column | Type | Constraints | Description |
| :--- | :--- | :--- | :--- |
| `id` | `VARCHAR(36)` | Primary Key | UUID string |
| `conversation_id` | `VARCHAR(36)` | Foreign Key (`conversations.id`), Indexed | References parent conversation (CASCADE on delete) |
| `role` | `VARCHAR(20)` | Not Null | `system`, `user`, or `assistant` |
| `content` | `TEXT` | Not Null | Message textual content |
| `model` | `VARCHAR(100)` | Nullable | Model name used for generation |
| `created_at` | `DATETIME` | UTC Timestamp | Message creation timestamp |

### Database Initialization
The database directory and tables are created automatically during the FastAPI `lifespan` startup hook in `app/main.py`.

---

## 3. Server Startup

To launch the FastAPI development server with hot-reloading:

```powershell
# From project root:
$env:PYTHONPATH="backend"
.\backend\.venv\Scripts\uvicorn.exe app.main:app --host 127.0.0.1 --port 8000 --reload
```

Interactive API documentation (Swagger UI) is available at:
- **Swagger UI:** `http://127.0.0.1:8000/docs`
- **ReDoc:** `http://127.0.0.1:8000/redoc`
- **OpenAPI Schema:** `http://127.0.0.1:8000/openapi.json`

---

## 4. API Endpoints Reference

### Core & System

| Method | Endpoint | Description |
| :--- | :--- | :--- |
| `GET` | `/` | Returns service name, version, and running status. |
| `GET` | `/api/health` | Returns backend health status. |
| `GET` | `/api/ollama/status` | Probes local Ollama daemon connectivity and version. |

### AI Chat & Conversations

| Method | Endpoint | Description |
| :--- | :--- | :--- |
| `POST` | `/api/chat` | Send a prompt. Persists user and assistant messages to SQLite. Auto-creates a new conversation if `conversation_id` is omitted. |
| `POST` | `/api/conversations` | Explicitly create a new conversation thread. |
| `GET` | `/api/conversations` | List all conversations ordered by recent activity. |
| `GET` | `/api/conversations/{id}` | Retrieve a conversation along with its full ordered message history. |
| `DELETE` | `/api/conversations/{id}` | Delete a conversation and cascade delete all its messages. |

### Example Payloads

#### `POST /api/chat` (New Conversation)
```json
{
  "message": "How does Foja AI handle local memory?"
}
```
**Response (200 OK):**
```json
{
  "assistant": "Foja AI",
  "model": "llama3.2:1b",
  "reply": "Foja AI uses an asynchronous SQLite database initially...",
  "conversation_id": "a59e91a3-d084-4cb8-b99a-e717a6c09944",
  "message_id": "4b6f120c-99d7-41ab-829b-73b313ef0201"
}
```

#### `POST /api/chat` (Existing Conversation)
```json
{
  "conversation_id": "a59e91a3-d084-4cb8-b99a-e717a6c09944",
  "message": "Can you summarize that in 3 bullet points?"
}
```

---

## 5. Automated Testing

The automated test suite runs against an isolated, in-memory SQLite database (`sqlite+aiosqlite:///:memory:`) so it never touches or alters user data:

```powershell
$env:PYTHONPATH="backend"
.\backend\.venv\Scripts\python.exe -m unittest backend\tests\test_api.py -v
```

All 10 test cases verify:
- System root, health, and Ollama status endpoints
- Conversation creation, listing, retrieval, and deletion
- User message and assistant reply database persistence
- Multi-turn conversation continuation
- Proper 404 handling for invalid conversation IDs

