import { ApiError, request } from './client';
import type {
  ChatRequest,
  ChatResponse,
  ConversationCreate,
  ConversationDetail,
  ConversationRead,
  DeleteConversationResponse,
  HealthResponse,
  OllamaStatusResponse,
  StreamCallbacks,
} from '../types/chat';

export interface RequestOptions {
  signal?: AbortSignal;
}

export const chatApi = {
  /**
   * Health probe
   */
  async getHealth(options?: RequestOptions): Promise<HealthResponse> {
    return request<HealthResponse>('/api/health', {
      method: 'GET',
      signal: options?.signal,
    });
  },

  /**
   * Ollama connection status probe
   */
  async getOllamaStatus(options?: RequestOptions): Promise<OllamaStatusResponse> {
    return request<OllamaStatusResponse>('/api/ollama/status', {
      method: 'GET',
      signal: options?.signal,
    });
  },

  /**
   * List all conversations ordered by recent activity
   */
  async listConversations(options?: RequestOptions): Promise<ConversationRead[]> {
    return request<ConversationRead[]>('/api/conversations', {
      method: 'GET',
      signal: options?.signal,
    });
  },

  /**
   * Create a new conversation session explicitly
   */
  async createConversation(payload: ConversationCreate = {}): Promise<ConversationRead> {
    return request<ConversationRead>('/api/conversations', {
      method: 'POST',
      body: JSON.stringify(payload),
    });
  },

  /**
   * Retrieve a conversation along with its full message history
   */
  async getConversation(conversationId: string, options?: RequestOptions): Promise<ConversationDetail> {
    return request<ConversationDetail>(`/api/conversations/${conversationId}`, {
      method: 'GET',
      signal: options?.signal,
    });
  },

  /**
   * Delete a conversation and cascade delete its messages
   */
  async deleteConversation(conversationId: string): Promise<DeleteConversationResponse> {
    return request<DeleteConversationResponse>(`/api/conversations/${conversationId}`, {
      method: 'DELETE',
    });
  },

  /**
   * Send a chat message to Foja AI (auto-creates conversation if conversation_id is omitted)
   */
  async sendMessage(payload: ChatRequest): Promise<ChatResponse> {
    return request<ChatResponse>('/api/chat', {
      method: 'POST',
      body: JSON.stringify(payload),
    });
  },

  /**
   * Send a chat message with progressive real-time SSE streaming.
   */
  async sendMessageStream(
    payload: ChatRequest,
    callbacks: StreamCallbacks,
    options?: RequestOptions
  ): Promise<void> {
    const url = '/api/chat/stream';
    let response: Response;

    try {
      response = await fetch(url, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          Accept: 'text/event-stream',
        },
        body: JSON.stringify(payload),
        signal: options?.signal,
      });
    } catch (err: unknown) {
      if (err instanceof Error && err.name === 'AbortError') {
        throw err;
      }
      throw new ApiError(
        0,
        'Unable to connect to Foja AI backend. Ensure the FastAPI server is running on port 8000.'
      );
    }

    if (!response.ok) {
      let errorMessage = `Request failed with status ${response.status}`;
      try {
        const errorData = await response.json();
        if (typeof errorData?.detail === 'string') {
          errorMessage = errorData.detail;
        } else if (Array.isArray(errorData?.detail)) {
          errorMessage = errorData.detail
            .map((e: { msg?: string }) => e.msg || 'Validation error')
            .join(', ');
        }
      } catch {
        if (response.statusText) {
          errorMessage = response.statusText;
        }
      }
      throw new ApiError(response.status, errorMessage);
    }

    if (!response.body) {
      throw new ApiError(0, 'Streaming response body is null');
    }

    const reader = response.body.getReader();
    const decoder = new TextDecoder('utf-8');
    let buffer = '';

    try {
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });

        // SSE messages are delimited by double newlines (\n\n or \r\n\r\n)
        const parts = buffer.split(/\r?\n\r?\n/);
        // The last item is the remaining partial message
        buffer = parts.pop() || '';

        for (const part of parts) {
          const trimmed = part.trim();
          if (!trimmed) continue;

          const lines = trimmed.split(/\r?\n/);
          for (const line of lines) {
            if (line.startsWith('data:')) {
              const jsonStr = line.slice(5).trim();
              if (!jsonStr) continue;
              try {
                const event = JSON.parse(jsonStr);
                if (event.type === 'start') {
                  callbacks.onStart?.(event);
                } else if (event.type === 'chunk') {
                  callbacks.onChunk(event.content);
                } else if (event.type === 'done') {
                  callbacks.onDone(event);
                } else if (event.type === 'error') {
                  callbacks.onError(event.detail || 'Streaming failed');
                }
              } catch {
                // Ignore malformed JSON chunk safely
              }
            }
          }
        }
      }

      // Process any trailing complete event in the buffer upon stream closure
      if (buffer.trim()) {
        const lines = buffer.trim().split(/\r?\n/);
        for (const line of lines) {
          if (line.startsWith('data:')) {
            const jsonStr = line.slice(5).trim();
            if (!jsonStr) continue;
            try {
              const event = JSON.parse(jsonStr);
              if (event.type === 'chunk') {
                callbacks.onChunk(event.content);
              } else if (event.type === 'done') {
                callbacks.onDone(event);
              } else if (event.type === 'error') {
                callbacks.onError(event.detail || 'Streaming failed');
              }
            } catch {
              // Ignore
            }
          }
        }
      }
    } finally {
      reader.releaseLock();
    }
  },
};
