import React from 'react';
import type { MemoryRead, MemoryCategory } from '../../types/memory';

interface MemoryCardProps {
  memory: MemoryRead;
  isMutating: boolean;
  onApprove: (id: string) => void;
  onReject: (id: string) => void;
  onEdit: (memory: MemoryRead) => void;
  onDelete: (memory: MemoryRead) => void;
}

const CATEGORY_META: Record<MemoryCategory, { label: string; icon: string; className: string }> = {
  preference: { label: 'Preference', icon: '⭐', className: 'badge-cat-preference' },
  fact: { label: 'Fact', icon: '📌', className: 'badge-cat-fact' },
  project: { label: 'Project', icon: '💼', className: 'badge-cat-project' },
  instruction: { label: 'Instruction', icon: '📝', className: 'badge-cat-instruction' },
  personal: { label: 'Personal', icon: '👤', className: 'badge-cat-personal' },
};

export const MemoryCard: React.FC<MemoryCardProps> = ({
  memory,
  isMutating,
  onApprove,
  onReject,
  onEdit,
  onDelete,
}) => {
  const catMeta = CATEGORY_META[memory.category] || {
    label: memory.category,
    icon: '📄',
    className: 'badge-cat-default',
  };

  const formatDate = (dateString: string) => {
    try {
      const d = new Date(dateString);
      return d.toLocaleDateString(undefined, {
        month: 'short',
        day: 'numeric',
        year: 'numeric',
        hour: '2-digit',
        minute: '2-digit',
      });
    } catch {
      return dateString;
    }
  };

  const importancePercent = Math.round(memory.importance * 100);

  return (
    <div className={`memory-card status-${memory.status}`}>
      {/* Header Badges */}
      <div className="memory-card-header">
        <div className="card-tags-left">
          {/* Category Badge */}
          <span className={`category-badge ${catMeta.className}`}>
            <span className="badge-icon">{catMeta.icon}</span>
            <span>{catMeta.label}</span>
          </span>

          {/* Status Badge */}
          <span className={`status-badge status-badge-${memory.status}`}>
            {memory.status === 'suggested' && '⏳ Suggested'}
            {memory.status === 'approved' && '✓ Approved'}
            {memory.status === 'rejected' && '✗ Rejected'}
          </span>

          {/* Global Directive Flag */}
          {memory.is_global && (
            <span className="global-badge" title="Applied across all chats in system prompt">
              🌐 Global Directive
            </span>
          )}
        </div>

        {/* Importance Meter */}
        <div className="importance-meter" title={`Importance Score: ${memory.importance.toFixed(2)}`}>
          <span className="importance-label">Importance</span>
          <div className="importance-bar-bg">
            <div
              className="importance-bar-fill"
              style={{ width: `${Math.max(10, importancePercent)}%` }}
            />
          </div>
          <span className="importance-val">{importancePercent}%</span>
        </div>
      </div>

      {/* Content */}
      <div className="memory-card-content">
        <p>{memory.content}</p>
      </div>

      {/* Footer & Actions */}
      <div className="memory-card-footer">
        <div className="card-metadata">
          <span className="card-date" title={`Created: ${formatDate(memory.created_at)}`}>
            {formatDate(memory.updated_at || memory.created_at)}
          </span>
          {memory.source_conversation_id && (
            <span className="source-conv-tag" title={`Extracted from conversation: ${memory.source_conversation_id}`}>
              💬 Chat extracted
            </span>
          )}
        </div>

        <div className="card-actions">
          {/* Suggested State: Quick Approve & Quick Reject */}
          {memory.status === 'suggested' && (
            <>
              <button
                type="button"
                className="btn-action btn-approve"
                onClick={() => onApprove(memory.id)}
                disabled={isMutating}
                title="Approve this suggestion into active memory"
              >
                <span>✓</span>
                <span>Approve</span>
              </button>

              <button
                type="button"
                className="btn-action btn-reject"
                onClick={() => onReject(memory.id)}
                disabled={isMutating}
                title="Reject this suggestion"
              >
                <span>✗</span>
                <span>Reject</span>
              </button>
            </>
          )}

          {/* Rejected State: Option to Re-approve */}
          {memory.status === 'rejected' && (
            <button
              type="button"
              className="btn-action btn-approve"
              onClick={() => onApprove(memory.id)}
              disabled={isMutating}
              title="Re-approve memory"
            >
              <span>✓</span>
              <span>Re-approve</span>
            </button>
          )}

          {/* Approved State: Option to Reject */}
          {memory.status === 'approved' && (
            <button
              type="button"
              className="btn-action btn-secondary-action"
              onClick={() => onReject(memory.id)}
              disabled={isMutating}
              title="Change status to rejected"
            >
              <span>Disable</span>
            </button>
          )}

          {/* Edit Button */}
          <button
            type="button"
            className="btn-action btn-edit"
            onClick={() => onEdit(memory)}
            disabled={isMutating}
            title="Edit memory content or attributes"
          >
            <span>✎</span>
            <span>Edit</span>
          </button>

          {/* Delete Button */}
          <button
            type="button"
            className="btn-action btn-delete"
            onClick={() => onDelete(memory)}
            disabled={isMutating}
            title="Permanently delete this memory"
          >
            <span>🗑</span>
          </button>
        </div>
      </div>
    </div>
  );
};
