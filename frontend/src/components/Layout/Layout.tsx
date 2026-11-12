import React, { useState } from 'react';
import { Sidebar } from '../Sidebar/Sidebar';
import { Header } from './Header';
import { ChatArea } from '../Chat/ChatArea';
import { ErrorBanner } from '../Common/ErrorBanner';
import type { ConversationRead, ConversationDetail } from '../../types/chat';

interface LayoutProps {
  conversations: ConversationRead[];
  activeConversationId: string | null;
  activeConversation: ConversationDetail | null;
  isLoading: boolean;
  error: string | null;
  backendHealthy: boolean | null;
  onSelectConversation: (id: string) => void;
  onNewChat: () => void;
  onDeleteConversation: (id: string) => Promise<void>;
  onSendMessage: (message: string) => void;
  onDismissError: () => void;
}

export const Layout: React.FC<LayoutProps> = ({
  conversations,
  activeConversationId,
  activeConversation,
  isLoading,
  error,
  backendHealthy,
  onSelectConversation,
  onNewChat,
  onDeleteConversation,
  onSendMessage,
  onDismissError,
}) => {
  const [isSidebarOpen, setIsSidebarOpen] = useState(true);
  const [prefillMessage, setPrefillMessage] = useState('');

  const currentTitle = activeConversation?.title || 'New Chat';

  const handleSelectSuggestion = (prompt: string) => {
    setPrefillMessage(prompt);
  };

  const handleSend = (msg: string) => {
    setPrefillMessage('');
    onSendMessage(msg);
  };

  return (
    <div className="layout-root">
      {/* Responsive mobile sidebar backdrop */}
      <div
        className={`sidebar-overlay ${isSidebarOpen ? 'active' : ''}`}
        onClick={() => setIsSidebarOpen(false)}
        aria-hidden="true"
      />

      {/* Sidebar */}
      <Sidebar
        conversations={conversations}
        activeConversationId={activeConversationId}
        isOpen={isSidebarOpen}
        onToggle={() => setIsSidebarOpen((prev) => !prev)}
        onSelectConversation={(id) => {
          onSelectConversation(id);
          // Auto close on small screens
          if (window.innerWidth <= 768) {
            setIsSidebarOpen(false);
          }
        }}
        onNewChat={() => {
          onNewChat();
          if (window.innerWidth <= 768) {
            setIsSidebarOpen(false);
          }
        }}
        onDeleteConversation={onDeleteConversation}
        backendHealthy={backendHealthy}
      />

      {/* Main View Area */}
      <div className="main-content-pane">
        <Header
          title={currentTitle}
          onToggleSidebar={() => setIsSidebarOpen((prev) => !prev)}
          onNewChat={onNewChat}
          isSidebarOpen={isSidebarOpen}
        />

        <ErrorBanner message={error} onDismiss={onDismissError} />

        <ChatArea
          activeConversation={activeConversation}
          isLoading={isLoading}
          onSendMessage={handleSend}
          onSelectSuggestion={handleSelectSuggestion}
          prefillMessage={prefillMessage}
        />
      </div>
    </div>
  );
};
