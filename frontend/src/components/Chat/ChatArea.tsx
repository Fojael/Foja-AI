import React, { useRef, useEffect } from 'react';
import type { ConversationDetail } from '../../types/chat';
import { MessageBubble } from './MessageBubble';
import { ThinkingIndicator } from './ThinkingIndicator';
import { MessageComposer } from './MessageComposer';
import { WelcomeScreen } from './WelcomeScreen';

interface ChatAreaProps {
  activeConversation: ConversationDetail | null;
  isLoading: boolean;
  onSendMessage: (message: string) => void;
  onSelectSuggestion: (prompt: string) => void;
  prefillMessage: string;
}

export const ChatArea: React.FC<ChatAreaProps> = ({
  activeConversation,
  isLoading,
  onSendMessage,
  onSelectSuggestion,
  prefillMessage,
}) => {
  const messagesEndRef = useRef<HTMLDivElement>(null);

  const messages = activeConversation?.messages || [];
  const hasMessages = messages.length > 0;

  // Auto-scroll to the bottom of the chat on new messages or loading state
  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  };

  useEffect(() => {
    scrollToBottom();
  }, [messages, isLoading]);

  return (
    <main className="chat-area" role="main">
      <div className="chat-messages-scrollable">
        {!hasMessages && !isLoading ? (
          <WelcomeScreen onSelectPrompt={onSelectSuggestion} />
        ) : (
          <div className="messages-container">
            {messages.map((msg, index) => {
              const isLast = index === messages.length - 1;
              const isWaitingForFirstChunk =
                isLoading && msg.role === 'assistant' && !msg.content && isLast;

              if (isWaitingForFirstChunk) {
                return <ThinkingIndicator key={msg.id} />;
              }

              return (
                <MessageBubble
                  key={msg.id}
                  message={msg}
                  isStreaming={isLoading && isLast && msg.role === 'assistant'}
                />
              );
            })}
            {isLoading && messages.length === 0 && <ThinkingIndicator />}
            <div ref={messagesEndRef} className="scroll-anchor" />
          </div>
        )}
      </div>

      <MessageComposer
        onSend={onSendMessage}
        isLoading={isLoading}
        prefillValue={prefillMessage}
      />
    </main>
  );
};
