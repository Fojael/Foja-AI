import React, { useState } from 'react';
import type { ConversationRead } from '../../types/chat';

interface ConversationItemProps {
  conversation: ConversationRead;
  isActive: boolean;
  onSelect: (id: string) => void;
  onRequestDelete: (conversation: ConversationRead) => void;
}

export const ConversationItem: React.FC<ConversationItemProps> = ({
  conversation,
  isActive,
  onSelect,
  onRequestDelete,
}) => {
  const [isHovered, setIsHovered] = useState(false);

  // Format date nicely: e.g. "Nov 12, 5:05 PM" or "Today, 5:05 PM"
  const formattedDate = React.useMemo(() => {
    try {
      const date = new Date(conversation.updated_at || conversation.created_at);
      const now = new Date();
      const isToday = date.toDateString() === now.toDateString();

      const timeStr = date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
      if (isToday) {
        return `Today, ${timeStr}`;
      }
      return `${date.toLocaleDateString([], { month: 'short', day: 'numeric' })}, ${timeStr}`;
    } catch {
      return '';
    }
  }, [conversation.updated_at, conversation.created_at]);

  return (
    <div
      className={`conversation-item ${isActive ? 'active' : ''}`}
      onClick={() => onSelect(conversation.id)}
      onMouseEnter={() => setIsHovered(true)}
      onMouseLeave={() => setIsHovered(false)}
      role="button"
      tabIndex={0}
      onKeyDown={(e) => {
        if (e.key === 'Enter' || e.key === ' ') {
          e.preventDefault();
          onSelect(conversation.id);
        }
      }}
      title={conversation.title}
    >
      <div className="conversation-info">
        <span className="conversation-title">{conversation.title}</span>
        <span className="conversation-date">{formattedDate}</span>
      </div>

      {(isHovered || isActive) && (
        <button
          type="button"
          className="delete-btn"
          aria-label={`Delete conversation ${conversation.title}`}
          onClick={(e) => {
            e.stopPropagation();
            onRequestDelete(conversation);
          }}
          title="Delete conversation"
        >
          🗑
        </button>
      )}
    </div>
  );
};
