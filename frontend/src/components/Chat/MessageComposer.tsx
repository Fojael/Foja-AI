import React, { useState, useRef, useEffect } from 'react';

interface MessageComposerProps {
  onSend: (message: string) => void;
  isLoading: boolean;
  prefillValue?: string;
}

export const MessageComposer: React.FC<MessageComposerProps> = ({
  onSend,
  isLoading,
  prefillValue = '',
}) => {
  const [content, setContent] = useState(prefillValue);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  // Sync prefillValue when passed (e.g. from suggestion pill)
  useEffect(() => {
    if (prefillValue) {
      setContent(prefillValue);
      if (textareaRef.current) {
        textareaRef.current.focus();
      }
    }
  }, [prefillValue]);

  // Auto-resize textarea height as content changes
  useEffect(() => {
    if (textareaRef.current) {
      textareaRef.current.style.height = 'auto';
      const scrollHeight = textareaRef.current.scrollHeight;
      // Cap max height to ~200px
      textareaRef.current.style.height = `${Math.min(scrollHeight, 200)}px`;
    }
  }, [content]);

  const handleSubmit = (e?: React.FormEvent) => {
    if (e) e.preventDefault();
    const trimmed = content.trim();
    if (!trimmed || isLoading) return;

    onSend(trimmed);
    setContent('');

    // Reset height
    if (textareaRef.current) {
      textareaRef.current.style.height = 'auto';
      textareaRef.current.focus();
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSubmit();
    }
  };

  const isSendDisabled = !content.trim() || isLoading;

  return (
    <div className="composer-container">
      <form onSubmit={handleSubmit} className="composer-form">
        <textarea
          ref={textareaRef}
          value={content}
          onChange={(e) => setContent(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder={isLoading ? 'Foja AI is responding...' : 'Message Foja AI... (Enter to send, Shift+Enter for newline)'}
          disabled={isLoading}
          rows={1}
          className="composer-textarea"
          aria-label="Message input"
        />
        <button
          type="submit"
          disabled={isSendDisabled}
          className={`composer-send-btn ${isSendDisabled ? 'disabled' : ''}`}
          aria-label="Send message"
          title="Send message"
        >
          {isLoading ? (
            <span className="spinner-icon" aria-hidden="true" />
          ) : (
            <span className="send-icon" aria-hidden="true">▲</span>
          )}
        </button>
      </form>
      <div className="composer-hints">
        Foja AI can make mistakes. Verify important information.
      </div>
    </div>
  );
};
