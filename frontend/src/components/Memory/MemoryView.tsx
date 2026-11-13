import React, { useState } from 'react';
import type { useMemories } from '../../hooks/useMemories';
import { MemoryHeader } from './MemoryHeader';
import { MemoryDashboard } from './MemoryDashboard';
import { MemoryFilters } from './MemoryFilters';
import { MemoryCard } from './MemoryCard';
import { MemoryEditor } from './MemoryEditor';
import { ConfirmModal } from '../Common/ConfirmModal';
import { ErrorBanner } from '../Common/ErrorBanner';
import type { MemoryRead, MemoryCreate, MemoryUpdate } from '../../types/memory';

interface MemoryViewProps {
  onToggleSidebar: () => void;
  isSidebarOpen: boolean;
  onBackToChat: () => void;
  memoryState: ReturnType<typeof useMemories>;
}

export const MemoryView: React.FC<MemoryViewProps> = ({
  onToggleSidebar,
  isSidebarOpen,
  onBackToChat,
  memoryState,
}) => {
  const {
    memories,
    filteredMemories,
    total,
    hasMore,
    stats,
    isLoading,
    isLoadingMore,
    isMutating,
    error,
    selectedStatus,
    selectedCategory,
    isGlobalOnly,
    searchQuery,
    setSelectedStatus,
    setSelectedCategory,
    setIsGlobalOnly,
    setSearchQuery,
    loadMemories,
    loadMore,
    approveMemory,
    rejectMemory,
    createMemory,
    updateMemory,
    deleteMemory,
    clearApprovedMemories,
    clearAllMemories,
    dismissError,
  } = memoryState;

  // Modals state
  const [isEditorOpen, setIsEditorOpen] = useState(false);
  const [editingMemory, setEditingMemory] = useState<MemoryRead | null>(null);

  const [deleteCandidate, setDeleteCandidate] = useState<MemoryRead | null>(null);
  const [isConfirmClearApprovedOpen, setIsConfirmClearApprovedOpen] = useState(false);
  const [isConfirmClearAllOpen, setIsConfirmClearAllOpen] = useState(false);

  // Open Create
  const handleOpenCreate = () => {
    setEditingMemory(null);
    setIsEditorOpen(true);
  };

  // Open Edit
  const handleOpenEdit = (memory: MemoryRead) => {
    setEditingMemory(memory);
    setIsEditorOpen(true);
  };

  // Save handler for Create / Edit
  const handleSaveMemory = async (payload: MemoryCreate | MemoryUpdate) => {
    if (editingMemory) {
      await updateMemory(editingMemory.id, payload as MemoryUpdate);
    } else {
      await createMemory(payload as MemoryCreate);
    }
  };

  // Confirm Single Delete
  const handleConfirmSingleDelete = async () => {
    if (!deleteCandidate) return;
    try {
      await deleteMemory(deleteCandidate.id);
      setDeleteCandidate(null);
    } catch {
      // Error handled in hook
    }
  };

  // Confirm Clear Approved
  const handleConfirmClearApproved = async () => {
    try {
      await clearApprovedMemories();
      setIsConfirmClearApprovedOpen(false);
    } catch {
      // Error handled in hook
    }
  };

  // Confirm Clear All
  const handleConfirmClearAll = async () => {
    try {
      await clearAllMemories();
      setIsConfirmClearAllOpen(false);
    } catch {
      // Error handled in hook
    }
  };

  const remainingCount = Math.max(0, total - memories.length);

  return (
    <div className="main-content-pane memory-view-root">
      {/* Header */}
      <MemoryHeader
        onToggleSidebar={onToggleSidebar}
        isSidebarOpen={isSidebarOpen}
        onBackToChat={onBackToChat}
        onOpenCreateModal={handleOpenCreate}
        onRefresh={loadMemories}
        onRequestClearApproved={() => setIsConfirmClearApprovedOpen(true)}
        onRequestClearAll={() => setIsConfirmClearAllOpen(true)}
        hasApproved={stats.approved > 0}
        hasAny={stats.total > 0}
        isMutating={isMutating}
      />

      {/* Error banner */}
      <ErrorBanner message={error} onDismiss={dismissError} />

      {/* Main Scrollable Content */}
      <div className="memory-content-scrollable">
        <div className="memory-container">
          {/* Dashboard Summary with 100% accurate database counts */}
          <MemoryDashboard
            stats={stats}
            selectedCategory={selectedCategory}
            onSelectCategory={setSelectedCategory}
          />

          {/* Filters & Search Toolbar with exact total counts */}
          <MemoryFilters
            stats={stats}
            selectedStatus={selectedStatus}
            isGlobalOnly={isGlobalOnly}
            searchQuery={searchQuery}
            loadedCount={filteredMemories.length}
            totalMatching={total}
            onSelectStatus={setSelectedStatus}
            onToggleGlobalOnly={() => setIsGlobalOnly(!isGlobalOnly)}
            onSearchChange={setSearchQuery}
          />

          {/* Loading State */}
          {isLoading && (
            <div className="memory-loading-state">
              <div className="spinner-icon" />
              <span>Loading memories from database...</span>
            </div>
          )}

          {/* Empty State */}
          {!isLoading && filteredMemories.length === 0 && (
            <div className="memory-empty-state">
              <div className="empty-icon">🧠</div>
              {stats.total === 0 ? (
                <>
                  <h3>No Memories Stored Yet</h3>
                  <p>
                    Add custom instructions, user preferences, or facts so Foja AI
                    recalls them during your conversations.
                  </p>
                  <button
                    type="button"
                    className="btn btn-primary"
                    onClick={handleOpenCreate}
                  >
                    + Add Your First Memory
                  </button>
                </>
              ) : (
                <>
                  <h3>No Matching Memories</h3>
                  <p>
                    No memories found for the selected status, category, or search keywords.
                  </p>
                  <button
                    type="button"
                    className="btn btn-secondary"
                    onClick={() => {
                      setSelectedStatus('all');
                      setSelectedCategory('all');
                      setIsGlobalOnly(false);
                      setSearchQuery('');
                    }}
                  >
                    Reset Filters
                  </button>
                </>
              )}
            </div>
          )}

          {/* Memory Cards Grid */}
          {!isLoading && filteredMemories.length > 0 && (
            <div className="memory-cards-grid">
              {filteredMemories.map((mem) => (
                <MemoryCard
                  key={mem.id}
                  memory={mem}
                  isMutating={isMutating}
                  onApprove={approveMemory}
                  onReject={rejectMemory}
                  onEdit={handleOpenEdit}
                  onDelete={(m) => setDeleteCandidate(m)}
                />
              ))}
            </div>
          )}

          {/* Pagination / Load More Footer */}
          {!isLoading && hasMore && (
            <div className="memory-pagination-footer">
              <button
                type="button"
                className="btn btn-secondary btn-load-more"
                onClick={loadMore}
                disabled={isLoadingMore}
              >
                {isLoadingMore ? (
                  <>
                    <span className="spinner-icon" />
                    <span>Loading more memories...</span>
                  </>
                ) : (
                  <>
                    <span>Load More</span>
                    <span className="load-more-badge">({remainingCount} remaining in database)</span>
                  </>
                )}
              </button>
            </div>
          )}
        </div>
      </div>

      {/* Create / Edit Memory Modal */}
      <MemoryEditor
        isOpen={isEditorOpen}
        memory={editingMemory}
        isSaving={isMutating}
        onSave={handleSaveMemory}
        onClose={() => setIsEditorOpen(false)}
      />

      {/* Delete Single Memory Modal */}
      <ConfirmModal
        isOpen={deleteCandidate !== null}
        title="Delete Memory"
        message={`Are you sure you want to delete this memory? "${deleteCandidate?.content.slice(0, 100)}${(deleteCandidate?.content.length || 0) > 100 ? '...' : ''}"`}
        confirmLabel={isMutating ? 'Deleting...' : 'Delete'}
        cancelLabel="Cancel"
        isDestructive={true}
        onConfirm={handleConfirmSingleDelete}
        onCancel={() => setDeleteCandidate(null)}
      />

      {/* Clear Approved Memories Modal */}
      <ConfirmModal
        isOpen={isConfirmClearApprovedOpen}
        title="Clear Approved Memories"
        message={`Are you sure you want to delete all ${stats.approved} approved memories? Pending suggestions and rejected records will be preserved.`}
        confirmLabel={isMutating ? 'Clearing...' : 'Clear Approved'}
        cancelLabel="Cancel"
        isDestructive={true}
        onConfirm={handleConfirmClearApproved}
        onCancel={() => setIsConfirmClearApprovedOpen(false)}
      />

      {/* Clear All Memories Modal */}
      <ConfirmModal
        isOpen={isConfirmClearAllOpen}
        title="Clear All Memories"
        message={`Are you sure you want to permanently delete ALL ${stats.total} memories (approved, suggested, and rejected)? This action cannot be undone.`}
        confirmLabel={isMutating ? 'Purging All...' : 'Purge All Memories'}
        cancelLabel="Cancel"
        isDestructive={true}
        onConfirm={handleConfirmClearAll}
        onCancel={() => setIsConfirmClearAllOpen(false)}
      />
    </div>
  );
};
