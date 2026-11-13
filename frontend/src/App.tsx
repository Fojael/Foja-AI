import React, { useState } from 'react';
import { useChat } from './hooks/useChat';
import { useMemories } from './hooks/useMemories';
import { Layout } from './components/Layout/Layout';

export const App: React.FC = () => {
  const [currentView, setCurrentView] = useState<'chat' | 'memory'>('chat');

  const {
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
  } = useChat();

  const memoryState = useMemories();

  if (isInitialLoading) {
    return (
      <div className="app-loading-screen">
        <div className="logo-badge-lg pulse">F</div>
        <h2>Initializing Foja AI</h2>
        <p>Connecting to backend and loading conversation history...</p>
      </div>
    );
  }

  return (
    <Layout
      conversations={conversations}
      activeConversationId={activeConversationId}
      activeConversation={activeConversation}
      isLoading={isLoading}
      error={error}
      backendHealthy={backendHealthy}
      currentView={currentView}
      pendingSuggestionsCount={memoryState.stats.suggested}
      memoryState={memoryState}
      onSelectView={setCurrentView}
      onSelectConversation={selectConversation}
      onNewChat={startNewChat}
      onDeleteConversation={deleteConversation}
      onSendMessage={sendMessage}
      onDismissError={dismissError}
    />
  );
};

export default App;
