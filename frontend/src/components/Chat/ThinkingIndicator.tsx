import React from 'react';

export const ThinkingIndicator: React.FC = () => {
  return (
    <div className="message-wrapper assistant">
      <div className="message-avatar">F</div>
      <div className="message-content-container">
        <div className="message-header">
          <span className="message-author">Foja AI</span>
          <span className="message-badge">Generating</span>
        </div>
        <div className="thinking-bubble">
          <div className="typing-indicator">
            <span />
            <span />
            <span />
          </div>
          <span className="thinking-text">Foja AI is thinking...</span>
        </div>
      </div>
    </div>
  );
};
