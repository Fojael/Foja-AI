import React from 'react';
import type { MemoryStats, MemoryCategory } from '../../types/memory';

interface MemoryDashboardProps {
  stats: MemoryStats;
  selectedCategory: 'all' | MemoryCategory;
  onSelectCategory: (cat: 'all' | MemoryCategory) => void;
}

export const MemoryDashboard: React.FC<MemoryDashboardProps> = ({
  stats,
  selectedCategory,
  onSelectCategory,
}) => {
  const categoryLabels: { key: MemoryCategory; label: string; icon: string }[] = [
    { key: 'fact', label: 'Facts', icon: '📌' },
    { key: 'preference', label: 'Preferences', icon: '⭐' },
    { key: 'instruction', label: 'Instructions', icon: '📝' },
    { key: 'project', label: 'Projects', icon: '💼' },
    { key: 'personal', label: 'Personal', icon: '👤' },
  ];

  return (
    <div className="memory-dashboard">
      <div className="memory-stats-grid">
        {/* Total Memories */}
        <div className="memory-stat-card">
          <div className="stat-icon-wrapper blue">🧠</div>
          <div className="stat-content">
            <span className="stat-label">Total Memories</span>
            <span className="stat-value">{stats.total}</span>
          </div>
        </div>

        {/* Suggested (Pending Review) */}
        <div className={`memory-stat-card ${stats.suggested > 0 ? 'highlight-amber' : ''}`}>
          <div className="stat-icon-wrapper amber">⏳</div>
          <div className="stat-content">
            <div className="stat-label-row">
              <span className="stat-label">Pending Review</span>
              {stats.suggested > 0 && <span className="stat-badge-pulse">Action Needed</span>}
            </div>
            <span className="stat-value">{stats.suggested}</span>
          </div>
        </div>

        {/* Approved (Active in Retrieval) */}
        <div className="memory-stat-card">
          <div className="stat-icon-wrapper green">✓</div>
          <div className="stat-content">
            <span className="stat-label">Approved (Active)</span>
            <span className="stat-value">{stats.approved}</span>
          </div>
        </div>

        {/* Global Directives */}
        <div className="memory-stat-card">
          <div className="stat-icon-wrapper purple">🌐</div>
          <div className="stat-content">
            <span className="stat-label">Global Directives</span>
            <span className="stat-value">{stats.globalDirectives}</span>
          </div>
        </div>
      </div>

      {/* Category breakdown pill buttons */}
      <div className="memory-category-breakdown">
        <span className="breakdown-title">Categories:</span>
        <div className="category-pill-group">
          <button
            type="button"
            className={`category-pill ${selectedCategory === 'all' ? 'active' : ''}`}
            onClick={() => onSelectCategory('all')}
          >
            All ({stats.total})
          </button>
          {categoryLabels.map(({ key, label, icon }) => (
            <button
              key={key}
              type="button"
              className={`category-pill ${selectedCategory === key ? 'active' : ''}`}
              onClick={() => onSelectCategory(key)}
            >
              <span className="pill-icon">{icon}</span>
              <span>{label}</span>
              <span className="pill-count">({stats.categories[key] || 0})</span>
            </button>
          ))}
        </div>
      </div>
    </div>
  );
};
