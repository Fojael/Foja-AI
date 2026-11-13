import React from 'react';
import type { MemoryStatus, MemoryStats } from '../../types/memory';

interface MemoryFiltersProps {
  stats: MemoryStats;
  selectedStatus: 'all' | MemoryStatus;
  isGlobalOnly: boolean;
  searchQuery: string;
  loadedCount: number;
  totalMatching: number;
  onSelectStatus: (status: 'all' | MemoryStatus) => void;
  onToggleGlobalOnly: () => void;
  onSearchChange: (query: string) => void;
}

export const MemoryFilters: React.FC<MemoryFiltersProps> = ({
  stats,
  selectedStatus,
  isGlobalOnly,
  searchQuery,
  loadedCount,
  totalMatching,
  onSelectStatus,
  onToggleGlobalOnly,
  onSearchChange,
}) => {
  return (
    <div className="memory-filters-container">
      {/* Status Filter Tabs */}
      <div className="status-tabs" role="tablist">
        <button
          type="button"
          role="tab"
          aria-selected={selectedStatus === 'all'}
          className={`status-tab ${selectedStatus === 'all' ? 'active' : ''}`}
          onClick={() => onSelectStatus('all')}
        >
          All
          <span className="tab-badge">{stats.total}</span>
        </button>

        <button
          type="button"
          role="tab"
          aria-selected={selectedStatus === 'suggested'}
          className={`status-tab tab-suggested ${selectedStatus === 'suggested' ? 'active' : ''}`}
          onClick={() => onSelectStatus('suggested')}
        >
          Pending Review
          <span className={`tab-badge ${stats.suggested > 0 ? 'badge-amber' : ''}`}>
            {stats.suggested}
          </span>
        </button>

        <button
          type="button"
          role="tab"
          aria-selected={selectedStatus === 'approved'}
          className={`status-tab ${selectedStatus === 'approved' ? 'active' : ''}`}
          onClick={() => onSelectStatus('approved')}
        >
          Approved
          <span className="tab-badge">{stats.approved}</span>
        </button>

        <button
          type="button"
          role="tab"
          aria-selected={selectedStatus === 'rejected'}
          className={`status-tab ${selectedStatus === 'rejected' ? 'active' : ''}`}
          onClick={() => onSelectStatus('rejected')}
        >
          Rejected
          <span className="tab-badge">{stats.rejected}</span>
        </button>
      </div>

      {/* Search and Global Directives Toggle */}
      <div className="search-and-toggles-row">
        <div className="search-input-wrapper">
          <span className="search-icon">🔍</span>
          <input
            type="text"
            className="search-input"
            placeholder="Search loaded memories by keyword..."
            value={searchQuery}
            onChange={(e) => onSearchChange(e.target.value)}
          />
          {searchQuery && (
            <button
              type="button"
              className="search-clear-btn"
              onClick={() => onSearchChange('')}
              title="Clear search"
            >
              ×
            </button>
          )}
        </div>

        <button
          type="button"
          className={`global-filter-btn ${isGlobalOnly ? 'active' : ''}`}
          onClick={onToggleGlobalOnly}
          title="Filter only global directives (injected into every prompt)"
        >
          <span>🌐</span>
          <span>Global Only ({stats.globalDirectives})</span>
        </button>

        <div className="filtered-counter">
          {searchQuery ? (
            <span>
              Matching: <strong>{loadedCount}</strong> of <strong>{totalMatching}</strong>
            </span>
          ) : (
            <span>
              Showing <strong>{loadedCount}</strong> of <strong>{totalMatching}</strong> {totalMatching === 1 ? 'record' : 'records'}
            </span>
          )}
        </div>
      </div>
    </div>
  );
};
