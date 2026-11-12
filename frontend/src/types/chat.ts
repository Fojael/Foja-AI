/**
 * TypeScript definitions strictly matching backend Pydantic schemas:
 * backend/app/schemas/chat.py
 */

export type MessageRole = 'user' | 'assistant' | 'system';

export interface ChatRequest {
  message: string;
  conversation_id?: string | null;
  model?: string | null;
}

export interface ChatResponse {
  assistant: string;
  model: string;
  reply: string;
  conversation_id?: string | null;
  message_id?: string | null;
}

export interface MessageRead {
  id: string;
  conversation_id: string;
  role: MessageRole;
  content: string;
  model?: string | null;
  created_at: string;
}

export interface ConversationCreate {
  title?: string;
}

export interface ConversationRead {
  id: string;
  title: string;
  created_at: string;
  updated_at: string;
}

export interface ConversationDetail extends ConversationRead {
  messages: MessageRead[];
}

export interface DeleteConversationResponse {
  status: string;
  conversation_id: string;
}

export interface HealthResponse {
  status: string;
  assistant: string;
  backend: string;
}

export interface OllamaStatusResponse {
  connected: boolean;
  message?: string;
  ollama?: {
    version?: string;
  };
  base_url?: string;
  default_model?: string;
}

export interface StreamStartEvent {
  type: 'start';
  conversation_id: string;
  model: string;
}

export interface StreamChunkEvent {
  type: 'chunk';
  content: string;
}

export interface StreamDoneEvent {
  type: 'done';
  conversation_id: string;
  message_id: string;
  total_length?: number;
}

export interface StreamErrorEvent {
  type: 'error';
  detail: string;
}

export type StreamEvent = StreamStartEvent | StreamChunkEvent | StreamDoneEvent | StreamErrorEvent;

export interface StreamCallbacks {
  onStart?: (event: StreamStartEvent) => void;
  onChunk: (chunk: string) => void;
  onDone: (event: StreamDoneEvent) => void;
  onError: (error: string) => void;
}
