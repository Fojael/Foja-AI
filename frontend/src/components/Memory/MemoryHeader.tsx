import React, { useState } from 'react';

interface MemoryHeaderProps {
  onToggleSidebar: () => void;
  isSidebarOpen: boolean;
  onBackToChat: () => void;
  onOpenCreateModal: () => void;
  onRefresh: () => void;
  onRequestClearApproved: () => void;
  onRequestClearAll: () => void;
  hasApproved: boolean;
  hasAny: boolean;
  isMutating: boolean;
}

export const MemoryHeader: React.FC<MemoryHeaderProps> = ({
  onToggleSidebar,
  isSidebarOpen,
  onBackToChat,
  onOpenCreateModal,
  onRefresh,
  onRequestClearApproved,
  onRequestClearAll,
  hasApproved,
  hasAny,
  isMutating,
}) => {
  const [showClearDropdown, setShowClearDropdown] = useState(false);

  return (
    <header className="chat-header memory-header">
      <div className="chat-header-left">
        <button
          type="button"
          className="header-menu-btn"
          onClick={onToggleSidebar}
          aria-label={isSidebarOpen ? 'Close sidebar' : 'Open sidebar'}
        >
          ☰
        </button>

        <button
          type="button"
          className="btn-back-to-chat"
          onClick={onBackToChat}
          title="Return to conversation"
        >
          ← Chat
        </button>

        <div className="memory-title-group">
          <h2 className="current-chat-title">Long-Term Memory</h2>
          <span className="memory-subtitle-tag">Knowledge Engine</span>
        </div>
      </div>

      <div className="chat-header-right">
        {/* Refresh button */}
        <button
          type="button"
          className="btn-icon-header"
          onClick={onRefresh}
          disabled={isMutating}
          title="Refresh memories from server"
        >
          ↻
        </button>

        {/* Clear Actions Dropdown */}
        {hasAny && (
          <div className="clear-dropdown-wrapper">
            <button
              type="button"
              className="btn-header-danger-outline"
              onClick={() => setShowClearDropdown((prev) => !prev)}
              disabled={isMutating}
            >
              <span>Purge...</span>
              <span className="arrow-down">▾</span>
            </button>

            {showClearDropdown && (
              <>
                <div
                  className="dropdown-backdrop"
                  onClick={() => setShowClearDropdown(false)}
                />
                <div className="dropdown-menu-list">
                  <button
                    type="button"
                    className="dropdown-menu-item"
                    disabled={!hasApproved || isMutating}
                    onClick={() => {
                      setShowClearDropdown(false);
                      onRequestClearApproved();
                    }}
                  >
                    <span>🗑 Clear Approved Memories</span>
                    <small>Preserves suggestions & rejected</small>
                  </button>

                  <div className="dropdown-divider" />

                  <button
                    type="button"
                    className="dropdown-menu-item danger"
                    disabled={!hasAny || isMutating}
                    onClick={() => {
                      setShowClearDropdown(false);
                      onRequestClearAll();
                    }}
                  >
                    <span>⚠ Clear All Memories</span>
                    <small>Permanently purges all records</small>
                  </button>
                </div>
              </>
            )}
          </div>
        )}

        {/* Create Memory Button */}
        <button
          type="button"
          className="btn btn-primary btn-sm"
          onClick={onOpenCreateModal}
          disabled={isMutating}
        >
          <span className="plus-icon">+</span>
          <span>New Memory</span>
        </button>
      </div>
    </header>
  );
};
