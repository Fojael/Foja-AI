import React from 'react';
import type { MessageRead } from '../../types/chat';

interface MessageBubbleProps {
  message: MessageRead;
  isStreaming?: boolean;
}

export const MessageBubble: React.FC<MessageBubbleProps> = ({ message, isStreaming = false }) => {
  const isUser = message.role === 'user';

  const formattedTime = React.useMemo(() => {
    try {
      const date = new Date(message.created_at);
      return date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
    } catch {
      return '';
    }
  }, [message.created_at]);

  return (
    <div className={`message-wrapper ${isUser ? 'user' : 'assistant'}`}>
      <div className="message-avatar">
        {isUser ? '👤' : 'F'}
      </div>

      <div className="message-content-container">
        <div className="message-header">
          <span className="message-author">
            {isUser ? 'You' : 'Foja AI'}
          </span>
          {!isUser && message.model && (
            <span className="message-badge">{message.model}</span>
          )}
          {formattedTime && (
            <span className="message-time">{formattedTime}</span>
          )}
        </div>

        <div className={`message-bubble ${isUser ? 'bubble-user' : 'bubble-assistant'}`}>
          <div className="message-text">
            {message.content}
            {isStreaming && <span className="streaming-cursor" aria-hidden="true">▊</span>}
          </div>
        </div>
      </div>
    </div>
  );
};
