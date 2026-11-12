import React from 'react';
import { useChat } from './hooks/useChat';
import { Layout } from './components/Layout/Layout';

export const App: React.FC = () => {
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
      onSelectConversation={selectConversation}
      onNewChat={startNewChat}
      onDeleteConversation={deleteConversation}
      onSendMessage={sendMessage}
      onDismissError={dismissError}
    />
  );
};

export default App;
