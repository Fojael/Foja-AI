import React from 'react';

interface HeaderProps {
  title: string;
  onToggleSidebar: () => void;
  onNewChat: () => void;
  isSidebarOpen: boolean;
}

export const Header: React.FC<HeaderProps> = ({
  title,
  onToggleSidebar,
  onNewChat,
  isSidebarOpen,
}) => {
  return (
    <header className="chat-header">
      <div className="chat-header-left">
        <button
          type="button"
          className="header-menu-btn"
          onClick={onToggleSidebar}
          aria-label={isSidebarOpen ? 'Close sidebar' : 'Open sidebar'}
        >
          ☰
        </button>
        <h2 className="current-chat-title">{title}</h2>
      </div>

      <div className="chat-header-right">
        <div className="model-pill" title="Hardware-optimized local model (Ollama)">
          <span className="model-pill-dot" />
          <span className="model-pill-name">llama3.2:1b</span>
        </div>
        <button
          type="button"
          className="btn-header-new-chat"
          onClick={onNewChat}
          title="Start a new chat"
        >
          + New Chat
        </button>
      </div>
    </header>
  );
};
