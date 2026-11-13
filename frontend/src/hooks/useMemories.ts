import { useState, useEffect, useCallback, useMemo } from 'react';
import { memoryApi } from '../api/memoryApi';
import { ApiError } from '../api/client';
import type {
  MemoryRead,
  MemoryCreate,
  MemoryUpdate,
  MemoryCategory,
  MemoryStatus,
  MemoryStats,
  MemoryQueryParams,
} from '../types/memory';

const PAGE_SIZE = 25;

const INITIAL_STATS: MemoryStats = {
  total: 0,
  approved: 0,
  suggested: 0,
  rejected: 0,
  globalDirectives: 0,
  categories: {
    preference: 0,
    fact: 0,
    project: 0,
    instruction: 0,
    personal: 0,
  },
};

export function useMemories() {
  const [memories, setMemories] = useState<MemoryRead[]>([]);
  const [total, setTotal] = useState<number>(0);
  const [hasMore, setHasMore] = useState<boolean>(false);
  const [isLoading, setIsLoading] = useState<boolean>(true);
  const [isLoadingMore, setIsLoadingMore] = useState<boolean>(false);
  const [isMutating, setIsMutating] = useState<boolean>(false);
  const [error, setError] = useState<string | null>(null);

  // Accurate global statistics across the entire database
  const [stats, setStats] = useState<MemoryStats>(INITIAL_STATS);

  // Filters
  const [selectedStatus, setSelectedStatus] = useState<'all' | MemoryStatus>('all');
  const [selectedCategory, setSelectedCategory] = useState<'all' | MemoryCategory>('all');
  const [isGlobalOnly, setIsGlobalOnly] = useState<boolean>(false);
  const [searchQuery, setSearchQuery] = useState<string>('');

  /**
   * Refreshes global statistics across the database.
   */
  const refreshStats = useCallback(async () => {
    try {
      const s = await memoryApi.fetchStats();
      setStats(s);
    } catch {
      // Non-blocking for stats refresh
    }
  }, []);

  /**
   * Load the first page of memories matching the current server-side filters.
   */
  const loadMemories = useCallback(async () => {
    setIsLoading(true);
    setError(null);
    try {
      const params: MemoryQueryParams = {
        limit: PAGE_SIZE,
        offset: 0,
      };

      if (selectedStatus !== 'all') {
        params.status = selectedStatus;
      }
      if (selectedCategory !== 'all') {
        params.category = selectedCategory;
      }
      if (isGlobalOnly) {
        params.is_global = true;
      }

      const res = await memoryApi.fetchMemories(params);
      setMemories(res.items);
      setTotal(res.total);
      setHasMore(res.items.length < res.total);

      // Also refresh stats
      refreshStats();
    } catch (err) {
      if (err instanceof ApiError) {
        setError(err.detail);
      } else if (err instanceof Error) {
        setError(err.message);
      } else {
        setError('Failed to load memories from backend.');
      }
    } finally {
      setIsLoading(false);
    }
  }, [selectedStatus, selectedCategory, isGlobalOnly, refreshStats]);

  // Re-fetch when server filters change
  useEffect(() => {
    loadMemories();
  }, [loadMemories]);

  /**
   * Load the next page of memories and append them with deduplication.
   */
  const loadMore = useCallback(async () => {
    if (isLoadingMore || !hasMore) return;

    setIsLoadingMore(true);
    setError(null);
    try {
      const params: MemoryQueryParams = {
        limit: PAGE_SIZE,
        offset: memories.length,
      };

      if (selectedStatus !== 'all') {
        params.status = selectedStatus;
      }
      if (selectedCategory !== 'all') {
        params.category = selectedCategory;
      }
      if (isGlobalOnly) {
        params.is_global = true;
      }

      const res = await memoryApi.fetchMemories(params);

      setMemories((prev) => {
        const existingIds = new Set(prev.map((item) => item.id));
        const newItems = res.items.filter((item) => !existingIds.has(item.id));
        const combined = [...prev, ...newItems];
        setHasMore(combined.length < res.total);
        return combined;
      });
      setTotal(res.total);
    } catch (err) {
      if (err instanceof ApiError) {
        setError(err.detail);
      } else {
        setError('Failed to load more memories.');
      }
    } finally {
      setIsLoadingMore(false);
    }
  }, [isLoadingMore, hasMore, memories.length, selectedStatus, selectedCategory, isGlobalOnly]);

  /**
   * Filter loaded memories by keyword search.
   */
  const filteredMemories = useMemo(() => {
    const query = searchQuery.trim().toLowerCase();
    if (!query) return memories;

    return memories.filter((m) => {
      const matchesContent = m.content.toLowerCase().includes(query);
      const matchesCategory = m.category.toLowerCase().includes(query);
      return matchesContent || matchesCategory;
    });
  }, [memories, searchQuery]);

  // Approve action
  const approveMemory = useCallback(
    async (id: string) => {
      setIsMutating(true);
      setError(null);
      try {
        const updated = await memoryApi.approveMemory(id);
        setMemories((prev) =>
          prev.map((item) => (item.id === id ? updated : item))
        );
        refreshStats();
        return updated;
      } catch (err) {
        if (err instanceof ApiError) {
          setError(err.detail);
        } else {
          setError('Failed to approve memory.');
        }
        throw err;
      } finally {
        setIsMutating(false);
      }
    },
    [refreshStats]
  );

  // Reject action
  const rejectMemory = useCallback(
    async (id: string) => {
      setIsMutating(true);
      setError(null);
      try {
        const updated = await memoryApi.rejectMemory(id);
        setMemories((prev) =>
          prev.map((item) => (item.id === id ? updated : item))
        );
        refreshStats();
        return updated;
      } catch (err) {
        if (err instanceof ApiError) {
          setError(err.detail);
        } else {
          setError('Failed to reject memory.');
        }
        throw err;
      } finally {
        setIsMutating(false);
      }
    },
    [refreshStats]
  );

  // Create action
  const createMemory = useCallback(
    async (payload: MemoryCreate) => {
      setIsMutating(true);
      setError(null);
      try {
        const created = await memoryApi.createMemory(payload);
        // Prepend and increment counts
        setMemories((prev) => [created, ...prev]);
        setTotal((prev) => prev + 1);
        refreshStats();
        return created;
      } catch (err) {
        if (err instanceof ApiError) {
          setError(err.detail);
        } else {
          setError('Failed to create memory.');
        }
        throw err;
      } finally {
        setIsMutating(false);
      }
    },
    [refreshStats]
  );

  // Update action
  const updateMemory = useCallback(
    async (id: string, payload: MemoryUpdate) => {
      setIsMutating(true);
      setError(null);
      try {
        const updated = await memoryApi.updateMemory(id, payload);
        setMemories((prev) =>
          prev.map((item) => (item.id === id ? updated : item))
        );
        refreshStats();
        return updated;
      } catch (err) {
        if (err instanceof ApiError) {
          setError(err.detail);
        } else {
          setError('Failed to update memory.');
        }
        throw err;
      } finally {
        setIsMutating(false);
      }
    },
    [refreshStats]
  );

  // Delete single memory action
  const deleteMemory = useCallback(
    async (id: string) => {
      setIsMutating(true);
      setError(null);
      try {
        await memoryApi.deleteMemory(id);
        setMemories((prev) => prev.filter((item) => item.id !== id));
        setTotal((prev) => Math.max(0, prev - 1));
        refreshStats();
      } catch (err) {
        if (err instanceof ApiError) {
          setError(err.detail);
        } else {
          setError('Failed to delete memory.');
        }
        throw err;
      } finally {
        setIsMutating(false);
      }
    },
    [refreshStats]
  );

  // Clear approved memories action
  const clearApprovedMemories = useCallback(async () => {
    setIsMutating(true);
    setError(null);
    try {
      await memoryApi.clearApprovedMemories();
      loadMemories();
      refreshStats();
    } catch (err) {
      if (err instanceof ApiError) {
        setError(err.detail);
      } else {
        setError('Failed to clear approved memories.');
      }
      throw err;
    } finally {
      setIsMutating(false);
    }
  }, [loadMemories, refreshStats]);

  // Clear all memories action
  const clearAllMemories = useCallback(async () => {
    setIsMutating(true);
    setError(null);
    try {
      await memoryApi.clearAllMemories();
      setMemories([]);
      setTotal(0);
      setHasMore(false);
      refreshStats();
    } catch (err) {
      if (err instanceof ApiError) {
        setError(err.detail);
      } else {
        setError('Failed to clear all memories.');
      }
      throw err;
    } finally {
      setIsMutating(false);
    }
  }, [refreshStats]);

  const dismissError = useCallback(() => {
    setError(null);
  }, []);

  return {
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
    refreshStats,
    approveMemory,
    rejectMemory,
    createMemory,
    updateMemory,
    deleteMemory,
    clearApprovedMemories,
    clearAllMemories,
    dismissError,
  };
}
