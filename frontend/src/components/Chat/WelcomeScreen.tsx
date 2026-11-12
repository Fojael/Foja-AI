import React from 'react';

interface WelcomeScreenProps {
  onSelectPrompt: (prompt: string) => void;
}

const SUGGESTIONS = [
  {
    icon: '💡',
    title: 'Explain Foja AI',
    prompt: 'Can you introduce yourself and explain how you assist me on Windows 11?',
  },
  {
    icon: '🐍',
    title: 'Python & FastAPI',
    prompt: 'How does FastAPI lifespan handle startup database initialization?',
  },
  {
    icon: '⚡',
    title: 'Local Ollama Model',
    prompt: 'What local AI model are you currently running and how is it optimized?',
  },
  {
    icon: '🛠',
    title: 'Code Assistant',
    prompt: 'Write a clean Python function to parse JSON files with error handling.',
  },
];

export const WelcomeScreen: React.FC<WelcomeScreenProps> = ({ onSelectPrompt }) => {
  return (
    <div className="welcome-screen">
      <div className="welcome-hero-chat">
        <div className="logo-badge-lg">F</div>
        <h2>What can I help with today?</h2>
        <p>
          I'm Foja AI, your personal desktop assistant for Windows 11. Send a prompt below or pick
          an idea to get started.
        </p>
      </div>

      <div className="suggestions-grid">
        {SUGGESTIONS.map((item, index) => (
          <button
            key={index}
            type="button"
            className="suggestion-card"
            onClick={() => onSelectPrompt(item.prompt)}
          >
            <div className="suggestion-icon">{item.icon}</div>
            <div className="suggestion-text">
              <span className="suggestion-title">{item.title}</span>
              <span className="suggestion-preview">{item.prompt}</span>
            </div>
          </button>
        ))}
      </div>
    </div>
  );
};
