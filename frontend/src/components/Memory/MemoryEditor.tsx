import React, { useState, useEffect } from 'react';
import type { MemoryRead, MemoryCreate, MemoryUpdate, MemoryCategory } from '../../types/memory';

interface MemoryEditorProps {
  isOpen: boolean;
  memory: MemoryRead | null; // null for Create, MemoryRead for Edit
  isSaving: boolean;
  onSave: (payload: MemoryCreate | MemoryUpdate) => Promise<void>;
  onClose: () => void;
}

const CATEGORIES: { value: MemoryCategory; label: string; description: string }[] = [
  { value: 'fact', label: 'Fact', description: 'Persistent truths or knowledge (e.g. user lives in Dhaka).' },
  { value: 'preference', label: 'Preference', description: 'User tastes, formats, or tone (e.g. prefers concise Python code).' },
  { value: 'instruction', label: 'Instruction', description: 'Explicit behavioral guidelines or directives.' },
  { value: 'project', label: 'Project', description: 'Context regarding active projects, repos, or workflows.' },
  { value: 'personal', label: 'Personal', description: 'Personal details or biographical context.' },
];

export const MemoryEditor: React.FC<MemoryEditorProps> = ({
  isOpen,
  memory,
  isSaving,
  onSave,
  onClose,
}) => {
  const isEditing = memory !== null;

  const [content, setContent] = useState('');
  const [category, setCategory] = useState<MemoryCategory>('fact');
  const [importance, setImportance] = useState<number>(0.5);
  const [isGlobal, setIsGlobal] = useState<boolean>(false);
  const [localError, setLocalError] = useState<string | null>(null);

  useEffect(() => {
    if (isOpen) {
      if (memory) {
        setContent(memory.content);
        setCategory(memory.category);
        setImportance(memory.importance);
        setIsGlobal(memory.is_global);
      } else {
        setContent('');
        setCategory('fact');
        setImportance(0.5);
        setIsGlobal(false);
      }
      setLocalError(null);
    }
  }, [isOpen, memory]);

  // When category changes away from 'instruction', reset isGlobal to false
  const handleCategoryChange = (newCat: MemoryCategory) => {
    setCategory(newCat);
    if (newCat !== 'instruction') {
      setIsGlobal(false);
    }
  };

  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape' && isOpen) {
        onClose();
      }
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [isOpen, onClose]);

  if (!isOpen) return null;

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    const cleaned = content.trim();

    if (!cleaned) {
      setLocalError('Memory content cannot be empty or blank.');
      return;
    }

    if (cleaned.length > 2000) {
      setLocalError('Memory content exceeds 2000 characters limit.');
      return;
    }

    if (isGlobal && category !== 'instruction') {
      setLocalError("Global scope ('is_global=true') is only permitted for category='instruction'.");
      return;
    }

    setLocalError(null);
    try {
      if (isEditing) {
        await onSave({
          content: cleaned,
          category,
          importance,
          is_global: isGlobal,
        });
      } else {
        await onSave({
          content: cleaned,
          category,
          importance,
          is_global: isGlobal,
        });
      }
      onClose();
    } catch (err: any) {
      if (err?.detail) {
        setLocalError(err.detail);
      } else if (err?.message) {
        setLocalError(err.message);
      } else {
        setLocalError('Failed to save memory.');
      }
    }
  };

  const getImportanceLabel = (val: number) => {
    if (val < 0.35) return 'Low Importance';
    if (val < 0.7) return 'Medium Importance';
    return 'High Importance';
  };

  return (
    <div className="modal-backdrop" onClick={onClose} role="dialog" aria-modal="true">
      <div className="modal-dialog memory-editor-dialog" onClick={(e) => e.stopPropagation()}>
        <div className="modal-header">
          <h3 className="modal-title">
            {isEditing ? 'Edit Memory' : 'Create New Memory'}
          </h3>
          <button
            type="button"
            className="modal-close-btn"
            onClick={onClose}
            aria-label="Close dialog"
          >
            ×
          </button>
        </div>

        {localError && (
          <div className="editor-error-banner" role="alert">
            <span>⚠</span>
            <span>{localError}</span>
          </div>
        )}

        <form onSubmit={handleSubmit} className="memory-editor-form">
          {/* Content field */}
          <div className="form-group">
            <div className="form-label-row">
              <label htmlFor="memory-content" className="form-label">
                Memory Content *
              </label>
              <span className={`char-counter ${content.length > 1900 ? 'counter-warning' : ''}`}>
                {content.length} / 2000
              </span>
            </div>
            <textarea
              id="memory-content"
              className="form-textarea"
              placeholder="e.g. User prefers Python and FastAPI for backend development, using async SQLite."
              value={content}
              onChange={(e) => setContent(e.target.value)}
              rows={4}
              maxLength={2000}
              required
              autoFocus
            />
          </div>

          {/* Category Selector */}
          <div className="form-group">
            <label htmlFor="memory-category" className="form-label">
              Category
            </label>
            <select
              id="memory-category"
              className="form-select"
              value={category}
              onChange={(e) => handleCategoryChange(e.target.value as MemoryCategory)}
            >
              {CATEGORIES.map((cat) => (
                <option key={cat.value} value={cat.value}>
                  {cat.label} — {cat.description}
                </option>
              ))}
            </select>
          </div>

          {/* Importance Slider */}
          <div className="form-group">
            <div className="form-label-row">
              <label htmlFor="memory-importance" className="form-label">
                Importance Score: <strong>{(importance * 100).toFixed(0)}%</strong> ({getImportanceLabel(importance)})
              </label>
            </div>
            <input
              id="memory-importance"
              type="range"
              min="0.0"
              max="1.0"
              step="0.05"
              className="form-range"
              value={importance}
              onChange={(e) => setImportance(parseFloat(e.target.value))}
            />
          </div>

          {/* Global Directive Flag */}
          <div className={`form-checkbox-card ${category !== 'instruction' ? 'disabled' : ''}`}>
            <label className="checkbox-label-wrapper">
              <input
                type="checkbox"
                className="form-checkbox"
                checked={isGlobal}
                onChange={(e) => setIsGlobal(e.target.checked)}
                disabled={category !== 'instruction'}
              />
              <div className="checkbox-text-block">
                <span className="checkbox-title">
                  🌐 Global Directive
                </span>
                <span className="checkbox-description">
                  {category === 'instruction'
                    ? 'When enabled, this instruction is directly included in the AI system prompt for EVERY conversation.'
                    : 'Global scope is only available for memories categorized as "Instruction".'}
                </span>
              </div>
            </label>
          </div>

          {/* Modal Footer */}
          <div className="modal-footer">
            <button
              type="button"
              className="btn btn-secondary"
              onClick={onClose}
              disabled={isSaving}
            >
              Cancel
            </button>
            <button
              type="submit"
              className="btn btn-primary"
              disabled={isSaving || !content.trim()}
            >
              {isSaving ? 'Saving...' : isEditing ? 'Update Memory' : 'Create Memory'}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
};
