import { useState, useEffect, useCallback, useRef } from 'react';
import { chatApi } from '../api/chatApi';
import type { ConversationRead, ConversationDetail, MessageRead } from '../types/chat';

export function useChat() {
  const [conversations, setConversations] = useState<ConversationRead[]>([]);
  const [activeConversationId, setActiveConversationId] = useState<string | null>(null);
  const [activeConversation, setActiveConversation] = useState<ConversationDetail | null>(null);
  const [isLoading, setIsLoading] = useState<boolean>(false);
  const [isInitialLoading, setIsInitialLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);
  const [backendHealthy, setBackendHealthy] = useState<boolean | null>(null);

  // Synchronization refs to eliminate race conditions and avoid stale closures
  const activeConversationIdRef = useRef<string | null>(null);
  const activeConversationRef = useRef<ConversationDetail | null>(null);
  const selectAbortControllerRef = useRef<AbortController | null>(null);

  useEffect(() => {
    activeConversationIdRef.current = activeConversationId;
  }, [activeConversationId]);

  useEffect(() => {
    activeConversationRef.current = activeConversation;
  }, [activeConversation]);

  // Clean up any pending abort controllers on unmount
  useEffect(() => {
    return () => {
      if (selectAbortControllerRef.current) {
        selectAbortControllerRef.current.abort();
      }
    };
  }, []);

  // 1. Initial health and conversation loading
  const loadConversations = useCallback(async () => {
    try {
      const [health, convs] = await Promise.all([
        chatApi.getHealth().catch(() => null),
        chatApi.listConversations(),
      ]);

      setBackendHealthy(health !== null && health.status === 'healthy');
      setConversations(convs);
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : 'Failed to load conversations';
      setError(msg);
      setBackendHealthy(false);
    } finally {
      setIsInitialLoading(false);
    }
  }, []);

  useEffect(() => {
    loadConversations();
  }, [loadConversations]);

  // 2. Select conversation & load full detail/history
  const selectConversation = useCallback(async (conversationId: string | null) => {
    // Abort any prior in-flight conversation loading request (BUG-03)
    if (selectAbortControllerRef.current) {
      selectAbortControllerRef.current.abort();
      selectAbortControllerRef.current = null;
    }

    activeConversationIdRef.current = conversationId;
    setActiveConversationId(conversationId);
    setError(null);

    if (!conversationId) {
      activeConversationRef.current = null;
      setActiveConversation(null);
      return;
    }

    const controller = new AbortController();
    selectAbortControllerRef.current = controller;

    try {
      const detail = await chatApi.getConversation(conversationId, { signal: controller.signal });
      // Guard against stale responses if user switched away before this completed
      if (activeConversationIdRef.current === conversationId) {
        activeConversationRef.current = detail;
        setActiveConversation(detail);
      }
    } catch (err: unknown) {
      if (err instanceof Error && err.name === 'AbortError') {
        // Request was canceled by subsequent user navigation; do not display error banner
        return;
      }
      // Only set error if the user is still on this conversation
      if (activeConversationIdRef.current === conversationId) {
        const msg = err instanceof Error ? err.message : 'Failed to load conversation history';
        setError(msg);
        activeConversationRef.current = null;
        setActiveConversation(null);
      }
    } finally {
      if (selectAbortControllerRef.current === controller) {
        selectAbortControllerRef.current = null;
      }
    }
  }, []);

  // 3. Start a new empty chat session
  const startNewChat = useCallback(() => {
    if (selectAbortControllerRef.current) {
      selectAbortControllerRef.current.abort();
      selectAbortControllerRef.current = null;
    }
    activeConversationIdRef.current = null;
    activeConversationRef.current = null;
    setActiveConversationId(null);
    setActiveConversation(null);
    setError(null);
  }, []);

  // 4. Delete a conversation
  const deleteConversation = useCallback(async (conversationId: string) => {
    try {
      await chatApi.deleteConversation(conversationId);

      // Remove from list
      setConversations((prev) => prev.filter((c) => c.id !== conversationId));

      // BUG-02 Fix: Remove nested state updater side-effects.
      // Pure top-level check whether deleted conversation was the active one.
      if (activeConversationIdRef.current === conversationId) {
        if (selectAbortControllerRef.current) {
          selectAbortControllerRef.current.abort();
          selectAbortControllerRef.current = null;
        }
        activeConversationIdRef.current = null;
        activeConversationRef.current = null;
        setActiveConversationId(null);
        setActiveConversation(null);
      }
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : 'Failed to delete conversation';
      setError(msg);
      throw err;
    }
  }, []);

  // 5. Send message with progressive real-time streaming (Phase 2.3)
  const sendMessage = useCallback(async (content: string) => {
    const trimmed = content.trim();
    if (!trimmed || isLoading) return;

    setIsLoading(true);
    setError(null);

    // Capture target conversation identity at dispatch time (BUG-01 Fix)
    const targetConversationId = activeConversationIdRef.current;
    const isNewConversation = targetConversationId === null;
    const tempSessionId = isNewConversation ? `temp-${Date.now()}` : null;

    // Optimistic user message
    const tempUserId = `temp-user-${Date.now()}`;
    const optimisticUserMessage: MessageRead = {
      id: tempUserId,
      conversation_id: targetConversationId || '',
      role: 'user',
      content: trimmed,
      created_at: new Date().toISOString(),
    };

    // Optimistic assistant placeholder message (starts with empty content while thinking)
    const tempAsstId = `temp-asst-${Date.now()}`;
    const initialAssistantMessage: MessageRead = {
      id: tempAsstId,
      conversation_id: targetConversationId || '',
      role: 'assistant',
      content: '',
      model: 'llama3.2:1b',
      created_at: new Date().toISOString(),
    };

    if (activeConversationRef.current && !isNewConversation) {
      const updatedActive = {
        ...activeConversationRef.current,
        messages: [
          ...activeConversationRef.current.messages,
          optimisticUserMessage,
          initialAssistantMessage,
        ],
      };
      activeConversationRef.current = updatedActive;
      setActiveConversation(updatedActive);
    } else {
      // Starting a brand new thread from the welcome screen
      const tempNewConv: ConversationDetail = {
        id: tempSessionId!,
        title: trimmed.slice(0, 40),
        created_at: new Date().toISOString(),
        updated_at: new Date().toISOString(),
        messages: [optimisticUserMessage, initialAssistantMessage],
      };
      activeConversationRef.current = tempNewConv;
      setActiveConversation(tempNewConv);
    }

    let accumulatedText = '';
    let assignedConversationId = targetConversationId;

    try {
      await chatApi.sendMessageStream(
        {
          message: trimmed,
          conversation_id: targetConversationId,
        },
        {
          onStart: (event) => {
            assignedConversationId = event.conversation_id;
          },

          onChunk: (chunk: string) => {
            accumulatedText += chunk;

            // Check if user is still on the conversation receiving this chunk
            const isStillViewing = isNewConversation
              ? activeConversationIdRef.current === null &&
                activeConversationRef.current?.id === tempSessionId
              : activeConversationIdRef.current === targetConversationId;

            if (isStillViewing && activeConversationRef.current) {
              const updatedMessages = activeConversationRef.current.messages.map((m) =>
                m.id === tempAsstId ? { ...m, content: accumulatedText } : m
              );
              const updatedActive = {
                ...activeConversationRef.current,
                messages: updatedMessages,
              };
              activeConversationRef.current = updatedActive;
              setActiveConversation(updatedActive);
            }
          },

          onDone: (event) => {
            assignedConversationId = event.conversation_id;

            const isStillViewing = isNewConversation
              ? activeConversationIdRef.current === null &&
                activeConversationRef.current?.id === tempSessionId
              : activeConversationIdRef.current === targetConversationId;

            if (isStillViewing && activeConversationRef.current) {
              const updatedMessages = activeConversationRef.current.messages.map((m) =>
                m.id === tempAsstId
                  ? { ...m, id: event.message_id, content: accumulatedText }
                  : m
              );
              const updatedActive: ConversationDetail = {
                ...activeConversationRef.current,
                id: assignedConversationId!,
                messages: updatedMessages,
              };
              activeConversationRef.current = updatedActive;
              setActiveConversation(updatedActive);

              if (isNewConversation) {
                activeConversationIdRef.current = assignedConversationId;
                setActiveConversationId(assignedConversationId);
              }
            }

            // Refresh conversations list so sidebar title, timestamp, and order update
            chatApi.listConversations().then(setConversations).catch(() => {});
          },

          onError: (errorMsg: string) => {
            setError(errorMsg);

            const isStillViewing = isNewConversation
              ? activeConversationIdRef.current === null &&
                activeConversationRef.current?.id === tempSessionId
              : activeConversationIdRef.current === targetConversationId;

            if (isStillViewing) {
              if (targetConversationId) {
                // Re-fetch persisted messages (user message is preserved)
                chatApi
                  .getConversation(targetConversationId)
                  .then((cleanDetail) => {
                    if (activeConversationIdRef.current === targetConversationId) {
                      activeConversationRef.current = cleanDetail;
                      setActiveConversation(cleanDetail);
                    }
                  })
                  .catch(() => {});
              } else if (assignedConversationId) {
                chatApi
                  .getConversation(assignedConversationId)
                  .then((cleanDetail) => {
                    activeConversationIdRef.current = assignedConversationId;
                    activeConversationRef.current = cleanDetail;
                    setActiveConversationId(assignedConversationId);
                    setActiveConversation(cleanDetail);
                  })
                  .catch(() => {});
              }
            }
          },
        }
      );

      // Final list refresh to ensure sidebar accuracy
      const updatedList = await chatApi.listConversations();
      setConversations(updatedList);
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : 'Error generating assistant response';
      setError(msg);

      // Revert optimistic placeholder only if user is still on this conversation
      const isStillViewing = isNewConversation
        ? activeConversationIdRef.current === null &&
          activeConversationRef.current?.id === tempSessionId
        : activeConversationIdRef.current === targetConversationId;

      if (isStillViewing) {
        if (targetConversationId) {
          chatApi
            .getConversation(targetConversationId)
            .then((cleanDetail) => {
              if (activeConversationIdRef.current === targetConversationId) {
                activeConversationRef.current = cleanDetail;
                setActiveConversation(cleanDetail);
              }
            })
            .catch(() => {});
        } else {
          activeConversationRef.current = null;
          setActiveConversation(null);
        }
      }
    } finally {
      setIsLoading(false);
    }
  }, [isLoading]);

  const dismissError = useCallback(() => {
    setError(null);
  }, []);

  return {
    conversations,
    activeConversationId,
    activeConversation,
    isLoading,
    isInitialLoading,
    error,
    backendHealthy,
    selectConversation,
    startNewChat,
    deleteConversation,
    sendMessage,
    dismissError,
    reloadConversations: loadConversations,
  };
}
