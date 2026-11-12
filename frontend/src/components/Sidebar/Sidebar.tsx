import React, { useState } from 'react';
import type { ConversationRead } from '../../types/chat';
import { ConversationItem } from './ConversationItem';
import { ConfirmModal } from '../Common/ConfirmModal';

interface SidebarProps {
  conversations: ConversationRead[];
  activeConversationId: string | null;
  isOpen: boolean;
  onToggle: () => void;
  onSelectConversation: (id: string) => void;
  onNewChat: () => void;
  onDeleteConversation: (id: string) => Promise<void>;
  backendHealthy: boolean | null;
}

export const Sidebar: React.FC<SidebarProps> = ({
  conversations,
  activeConversationId,
  isOpen,
  onToggle,
  onSelectConversation,
  onNewChat,
  onDeleteConversation,
  backendHealthy,
}) => {
  const [deleteCandidate, setDeleteCandidate] = useState<ConversationRead | null>(null);
  const [isDeleting, setIsDeleting] = useState(false);

  const handleConfirmDelete = async () => {
    if (!deleteCandidate) return;
    setIsDeleting(true);
    try {
      await onDeleteConversation(deleteCandidate.id);
      setDeleteCandidate(null);
    } finally {
      setIsDeleting(false);
    }
  };

  return (
    <>
      <aside className={`sidebar ${isOpen ? 'open' : 'collapsed'}`} aria-label="Chat sidebar">
        {/* Sidebar Header */}
        <div className="sidebar-header">
          <div className="brand" onClick={onNewChat} role="button" tabIndex={0}>
            <div className="logo-badge-sm">F</div>
            <div className="brand-text-sm">
              <h2>Foja AI</h2>
              <span className="brand-sub">Windows 11 Assistant</span>
            </div>
          </div>
          <button
            type="button"
            className="sidebar-toggle-btn"
            onClick={onToggle}
            aria-label={isOpen ? 'Collapse sidebar' : 'Expand sidebar'}
            title={isOpen ? 'Collapse sidebar' : 'Expand sidebar'}
          >
            {isOpen ? '◀' : '▶'}
          </button>
        </div>

        {/* New Chat Button */}
        <div className="sidebar-actions">
          <button
            type="button"
            className="btn btn-new-chat"
            onClick={onNewChat}
          >
            <span className="plus-icon">+</span>
            <span>New Chat</span>
          </button>
        </div>

        {/* Conversation List */}
        <div className="sidebar-content">
          <div className="sidebar-section-title">Conversations</div>
          {conversations.length === 0 ? (
            <div className="empty-conversations">
              <p>No conversations yet</p>
              <span>Click "New Chat" or send a message to start.</span>
            </div>
          ) : (
            <div className="conversation-list">
              {conversations.map((conv) => (
                <ConversationItem
                  key={conv.id}
                  conversation={conv}
                  isActive={conv.id === activeConversationId}
                  onSelect={onSelectConversation}
                  onRequestDelete={(target) => setDeleteCandidate(target)}
                />
              ))}
            </div>
          )}
        </div>

        {/* Sidebar Footer (Settings placeholder + System status) */}
        <div className="sidebar-footer">
          <div className="status-indicator-row">
            <span
              className={`status-dot ${backendHealthy ? 'online' : 'offline'}`}
              title={backendHealthy ? 'Backend Online' : 'Backend Connecting / Offline'}
            />
            <span className="status-label">
              {backendHealthy ? 'Backend Connected' : 'Connecting...'}
            </span>
          </div>

          <button
            type="button"
            className="settings-placeholder-btn"
            title="Settings (Coming in future phase)"
            disabled
          >
            ⚙ Settings
          </button>
        </div>
      </aside>

      {/* Confirmation Modal */}
      <ConfirmModal
        isOpen={deleteCandidate !== null}
        title="Delete Conversation"
        message={`Are you sure you want to delete "${deleteCandidate?.title}"? All messages in this conversation will be permanently removed.`}
        confirmLabel={isDeleting ? 'Deleting...' : 'Delete'}
        cancelLabel="Cancel"
        isDestructive={true}
        onConfirm={handleConfirmDelete}
        onCancel={() => setDeleteCandidate(null)}
      />
    </>
  );
};
