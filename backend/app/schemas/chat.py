from datetime import datetime
from typing import List, Optional
from pydantic import BaseModel, ConfigDict, Field


class ChatRequest(BaseModel):
    message: str = Field(
        min_length=1,
        max_length=4000,
        description="Your message to Foja AI"
    )
    conversation_id: Optional[str] = Field(
        default=None,
        description="Optional ID of an existing conversation. If omitted, a new conversation is created."
    )
    model: Optional[str] = Field(
        default=None,
        description="Optional model override to use for this generation."
    )


class ChatResponse(BaseModel):
    assistant: str
    model: str
    reply: str
    conversation_id: Optional[str] = Field(
        default=None,
        description="ID of the conversation this message belongs to."
    )
    message_id: Optional[str] = Field(
        default=None,
        description="ID of the generated assistant message."
    )


class MessageRead(BaseModel):
    id: str
    conversation_id: str
    role: str
    content: str
    model: Optional[str] = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ConversationCreate(BaseModel):
    title: Optional[str] = Field(
        default="New Conversation",
        max_length=255,
        description="Title of the new conversation"
    )


class ConversationRead(BaseModel):
    id: str
    title: str
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ConversationDetail(ConversationRead):
    messages: List[MessageRead] = []


class StreamStartEvent(BaseModel):
    type: str = "start"
    conversation_id: str
    model: str


class StreamChunkEvent(BaseModel):
    type: str = "chunk"
    content: str


class StreamDoneEvent(BaseModel):
    type: str = "done"
    conversation_id: str
    message_id: str
    total_length: Optional[int] = None


class StreamErrorEvent(BaseModel):
    type: str = "error"
    detail: str
