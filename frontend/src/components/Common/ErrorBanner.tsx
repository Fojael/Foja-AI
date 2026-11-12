import React from 'react';

interface ErrorBannerProps {
  message: string | null;
  onDismiss: () => void;
}

export const ErrorBanner: React.FC<ErrorBannerProps> = ({ message, onDismiss }) => {
  if (!message) return null;

  return (
    <div className="error-banner" role="alert">
      <div className="error-content">
        <span className="error-icon" aria-hidden="true">⚠️</span>
        <span className="error-text">{message}</span>
      </div>
      <button
        type="button"
        className="error-dismiss"
        onClick={onDismiss}
        aria-label="Dismiss error"
      >
        ✕
      </button>
    </div>
  );
};
