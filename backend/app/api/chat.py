from datetime import datetime, timezone
import json
import logging
from typing import List
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.auth import get_current_owner_id
from app.core.config import settings
from app.core.database import get_db
from app.models.chat import Conversation, Message
from app.schemas.chat import (
    ChatRequest,
    ChatResponse,
    ConversationCreate,
    ConversationDetail,
    ConversationRead,
)
from app.services.ai.ollama import (
    MODEL_NAME,
    OllamaConnectionError,
    OllamaModelNotFoundError,
    OllamaResponseError,
    generate_chat_response,
    stream_chat_response,
)
from app.services.memory.retrieval import (
    format_user_message_with_memories,
    retrieve_relevant_memories,
)

logger = logging.getLogger("foja.chat")

router = APIRouter(prefix="/api", tags=["AI Chat & Conversations"])


@router.post("/chat", response_model=ChatResponse)
async def chat(
    request: ChatRequest,
    owner_id: str = Depends(get_current_owner_id),
    db: AsyncSession = Depends(get_db)
):
    """
    Send a message to Foja AI.
    - If conversation_id is provided, appends to that conversation.
    - If omitted, automatically creates a new conversation.
    - Persists both user message and assistant reply to the database.
    """
    target_model = request.model or MODEL_NAME

    # 1. Resolve or create conversation
    if request.conversation_id:
        result = await db.execute(
            select(Conversation)
            .where(Conversation.id == request.conversation_id)
            .options(selectinload(Conversation.messages))
        )
        conversation = result.scalar_one_or_none()

        if not conversation:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Conversation '{request.conversation_id}' not found."
            )
    else:
        # Create a title based on the first few words of the user's message
        title_snippet = request.message.strip().split("\n")[0][:45]
        if len(request.message.strip()) > 45:
            title_snippet += "..."

        conversation = Conversation(
            title=title_snippet or "New Conversation"
        )
        db.add(conversation)
        await db.flush()  # Ensure conversation.id is populated

    # 2. Retrieve relevant approved memories if enabled
    retrieved_memories = []
    if settings.MEMORY_RETRIEVAL_ENABLED:
        try:
            retrieval_res = await retrieve_relevant_memories(
                user_message=request.message,
                owner_id=owner_id,
                db=db,
                conversation_id=request.conversation_id,
            )
            retrieved_memories = retrieval_res.items
        except Exception as err:
            logger.warning("Memory retrieval failed during chat, proceeding without context: %s", err)
            retrieved_memories = []

    # 3. Build multi-turn history from existing conversation messages
    history_payload: List[dict] = []
    if request.conversation_id and conversation.messages:
        for msg in conversation.messages:
            history_payload.append({
                "role": msg.role,
                "content": msg.content
            })

    # Append current user turn formatted with untrusted reference memory block (ephemeral)
    ai_user_content = format_user_message_with_memories(
        user_message=request.message,
        memories=retrieved_memories
    )
    history_payload.append({
        "role": "user",
        "content": ai_user_content
    })

    # 4. Persist clean user message (memory context is NEVER persisted to conversation history)
    user_message = Message(
        conversation_id=conversation.id,
        role="user",
        content=request.message,
        model=target_model
    )
    db.add(user_message)

    # 4. Invoke Ollama chat pipeline
    try:
        reply = await generate_chat_response(
            messages=history_payload,
            model=target_model
        )
    except OllamaConnectionError as err:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(err)
        )
    except OllamaModelNotFoundError as err:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(err)
        )
    except OllamaResponseError as err:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=str(err)
        )
    except Exception as err:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Unexpected error generating AI response: {str(err)}"
        )

    # 5. Persist assistant reply
    assistant_message = Message(
        conversation_id=conversation.id,
        role="assistant",
        content=reply,
        model=target_model
    )
    db.add(assistant_message)

    # Update conversation modification time
    conversation.updated_at = datetime.now(timezone.utc)
    await db.commit()

    return ChatResponse(
        assistant="Foja AI",
        model=target_model,
        reply=reply,
        conversation_id=conversation.id,
        message_id=assistant_message.id
    )


@router.post("/chat/stream")
async def chat_stream(
    request: ChatRequest,
    owner_id: str = Depends(get_current_owner_id),
    db: AsyncSession = Depends(get_db)
):
    """
    Stream assistant responses in real-time using Server-Sent Events (SSE).
    - If conversation_id is provided, appends to that conversation.
    - If omitted, creates a new conversation.
    - Retrieves relevant approved memories before streaming begins.
    - Persists clean user message to database before streaming begins.
    - Progressively yields SSE events (start, chunk, done, error).
    - Persists assistant completed response upon successful completion.
    """
    target_model = request.model or MODEL_NAME

    # 1. Resolve or create conversation
    if request.conversation_id:
        result = await db.execute(
            select(Conversation)
            .where(Conversation.id == request.conversation_id)
            .options(selectinload(Conversation.messages))
        )
        conversation = result.scalar_one_or_none()

        if not conversation:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Conversation '{request.conversation_id}' not found."
            )
    else:
        title_snippet = request.message.strip().split("\n")[0][:45]
        if len(request.message.strip()) > 45:
            title_snippet += "..."

        conversation = Conversation(
            title=title_snippet or "New Conversation"
        )
        db.add(conversation)
        await db.flush()

    conv_id = conversation.id

    # 2. Retrieve relevant approved memories before streaming begins
    retrieved_memories = []
    if settings.MEMORY_RETRIEVAL_ENABLED:
        try:
            retrieval_res = await retrieve_relevant_memories(
                user_message=request.message,
                owner_id=owner_id,
                db=db,
                conversation_id=request.conversation_id,
            )
            retrieved_memories = retrieval_res.items
        except Exception as err:
            logger.warning("Memory retrieval failed during stream init, proceeding without context: %s", err)
            retrieved_memories = []

    # 3. Build multi-turn history from existing conversation messages
    history_payload: List[dict] = []
    if request.conversation_id and conversation.messages:
        for msg in conversation.messages:
            history_payload.append({
                "role": msg.role,
                "content": msg.content
            })

    # Ephemeral user message with memories for Ollama
    ai_user_content = format_user_message_with_memories(
        user_message=request.message,
        memories=retrieved_memories
    )
    history_payload.append({
        "role": "user",
        "content": ai_user_content
    })

    # 4. Persist clean user message before streaming begins (un-injected)
    user_message = Message(
        conversation_id=conv_id,
        role="user",
        content=request.message,
        model=target_model
    )
    db.add(user_message)
    await db.commit()

    async def event_generator():
        accumulated_chunks: List[str] = []
        try:
            # Event 1: start
            start_data = {
                "type": "start",
                "conversation_id": conv_id,
                "model": target_model
            }
            yield f"data: {json.dumps(start_data)}\n\n"

            # Event 2: chunks
            async for chunk in stream_chat_response(
                messages=history_payload,
                model=target_model
            ):
                accumulated_chunks.append(chunk)
                chunk_data = {
                    "type": "chunk",
                    "content": chunk
                }
                yield f"data: {json.dumps(chunk_data)}\n\n"

            # Check if any content was produced
            full_reply = "".join(accumulated_chunks).strip()
            if not full_reply:
                raise OllamaResponseError("Ollama stream returned empty content.")

            # Event 3: Persist assistant message
            assistant_msg = Message(
                conversation_id=conv_id,
                role="assistant",
                content=full_reply,
                model=target_model
            )
            db.add(assistant_msg)

            # Update conversation timestamp
            res = await db.execute(
                select(Conversation).where(Conversation.id == conv_id)
            )
            conv_obj = res.scalar_one_or_none()
            if conv_obj:
                conv_obj.updated_at = datetime.now(timezone.utc)

            await db.commit()

            # Event 4: done
            done_data = {
                "type": "done",
                "conversation_id": conv_id,
                "message_id": assistant_msg.id,
                "total_length": len(full_reply)
            }
            yield f"data: {json.dumps(done_data)}\n\n"

        except (OllamaConnectionError, OllamaModelNotFoundError, OllamaResponseError) as err:
            await db.rollback()
            error_data = {
                "type": "error",
                "detail": str(err)
            }
            yield f"data: {json.dumps(error_data)}\n\n"
        except Exception as err:
            await db.rollback()
            error_data = {
                "type": "error",
                "detail": f"Streaming failed: {str(err)}"
            }
            yield f"data: {json.dumps(error_data)}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no"
        }
    )


@router.post(
    "/conversations",
    response_model=ConversationRead,
    status_code=status.HTTP_201_CREATED
)
async def create_conversation(
    payload: ConversationCreate,
    db: AsyncSession = Depends(get_db)
):
    """Explicitly create a new conversation session."""
    conversation = Conversation(
        title=payload.title or "New Conversation"
    )
    db.add(conversation)
    await db.commit()
    await db.refresh(conversation)
    return conversation


@router.get("/conversations", response_model=List[ConversationRead])
async def list_conversations(
    db: AsyncSession = Depends(get_db)
):
    """List all conversations ordered by most recently updated."""
    result = await db.execute(
        select(Conversation).order_by(Conversation.updated_at.desc())
    )
    return result.scalars().all()


@router.get(
    "/conversations/{conversation_id}",
    response_model=ConversationDetail
)
async def get_conversation(
    conversation_id: str,
    db: AsyncSession = Depends(get_db)
):
    """Retrieve a conversation along with its full message history."""
    result = await db.execute(
        select(Conversation)
        .where(Conversation.id == conversation_id)
        .options(selectinload(Conversation.messages))
    )
    conversation = result.scalar_one_or_none()

    if not conversation:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Conversation '{conversation_id}' not found."
        )

    return conversation


@router.delete("/conversations/{conversation_id}")
async def delete_conversation(
    conversation_id: str,
    db: AsyncSession = Depends(get_db)
):
    """Delete a conversation and all its associated messages."""
    result = await db.execute(
        select(Conversation).where(Conversation.id == conversation_id)
    )
    conversation = result.scalar_one_or_none()

    if not conversation:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Conversation '{conversation_id}' not found."
        )

    await db.delete(conversation)
    await db.commit()

    return {
        "status": "deleted",
        "conversation_id": conversation_id
    }
