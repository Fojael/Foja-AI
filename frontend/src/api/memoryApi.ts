import { request } from './client';
import type {
  MemoryRead,
  MemoryCreate,
  MemoryUpdate,
  MemoryListResponse,
  DeleteResponse,
  BulkDeleteResponse,
  MemoryQueryParams,
  MemoryStats,
} from '../types/memory';

/**
 * Memory Management API client interacting with FastAPI backend.
 */
export const memoryApi = {
  /**
   * Fetch paginated memories with optional filters.
   */
  async fetchMemories(params?: MemoryQueryParams): Promise<MemoryListResponse> {
    const searchParams = new URLSearchParams();

    if (params) {
      if (params.status) {
        searchParams.append('status', params.status);
      }
      if (params.category) {
        searchParams.append('category', params.category);
      }
      if (typeof params.is_global === 'boolean') {
        searchParams.append('is_global', String(params.is_global));
      }
      if (typeof params.min_importance === 'number') {
        searchParams.append('min_importance', String(params.min_importance));
      }
      if (typeof params.max_importance === 'number') {
        searchParams.append('max_importance', String(params.max_importance));
      }
      if (typeof params.limit === 'number') {
        searchParams.append('limit', String(params.limit));
      }
      if (typeof params.offset === 'number') {
        searchParams.append('offset', String(params.offset));
      }
    }

    const queryStr = searchParams.toString();
    const endpoint = queryStr ? `/api/memories?${queryStr}` : '/api/memories';
    return request<MemoryListResponse>(endpoint, { method: 'GET' });
  },

  /**
   * Efficiently fetch exact global statistics across all memories in SQLite.
   * Runs lightweight count queries concurrently using limit=1.
   */
  async fetchStats(): Promise<MemoryStats> {
    const [
      totalRes,
      suggestedRes,
      approvedRes,
      rejectedRes,
      globalRes,
      factRes,
      prefRes,
      instRes,
      projRes,
      persRes,
    ] = await Promise.all([
      this.fetchMemories({ limit: 1 }),
      this.fetchMemories({ status: 'suggested', limit: 1 }),
      this.fetchMemories({ status: 'approved', limit: 1 }),
      this.fetchMemories({ status: 'rejected', limit: 1 }),
      this.fetchMemories({ is_global: true, limit: 1 }),
      this.fetchMemories({ category: 'fact', limit: 1 }),
      this.fetchMemories({ category: 'preference', limit: 1 }),
      this.fetchMemories({ category: 'instruction', limit: 1 }),
      this.fetchMemories({ category: 'project', limit: 1 }),
      this.fetchMemories({ category: 'personal', limit: 1 }),
    ]);

    return {
      total: totalRes.total,
      suggested: suggestedRes.total,
      approved: approvedRes.total,
      rejected: rejectedRes.total,
      globalDirectives: globalRes.total,
      categories: {
        fact: factRes.total,
        preference: prefRes.total,
        instruction: instRes.total,
        project: projRes.total,
        personal: persRes.total,
      },
    };
  },

  /**
   * Create a new manual memory.
   */
  async createMemory(payload: MemoryCreate): Promise<MemoryRead> {
    return request<MemoryRead>('/api/memories', {
      method: 'POST',
      body: JSON.stringify(payload),
    });
  },

  /**
   * Fetch a single memory by ID.
   */
  async getMemory(id: string): Promise<MemoryRead> {
    return request<MemoryRead>(`/api/memories/${id}`, { method: 'GET' });
  },

  /**
   * Update fields of an existing memory.
   */
  async updateMemory(id: string, payload: MemoryUpdate): Promise<MemoryRead> {
    return request<MemoryRead>(`/api/memories/${id}`, {
      method: 'PATCH',
      body: JSON.stringify(payload),
    });
  },

  /**
   * Permanently delete a single memory by ID.
   */
  async deleteMemory(id: string): Promise<DeleteResponse> {
    return request<DeleteResponse>(`/api/memories/${id}`, {
      method: 'DELETE',
    });
  },

  /**
   * Approve a memory (typically a suggestion).
   */
  async approveMemory(id: string): Promise<MemoryRead> {
    return request<MemoryRead>(`/api/memories/${id}/approve`, {
      method: 'POST',
    });
  },

  /**
   * Reject a memory (typically a suggestion).
   */
  async rejectMemory(id: string): Promise<MemoryRead> {
    return request<MemoryRead>(`/api/memories/${id}/reject`, {
      method: 'POST',
    });
  },

  /**
   * Delete all approved memories for the current owner.
   */
  async clearApprovedMemories(): Promise<BulkDeleteResponse> {
    return request<BulkDeleteResponse>('/api/memories/approved', {
      method: 'DELETE',
    });
  },

  /**
   * Completely purge all memories for the current owner.
   */
  async clearAllMemories(): Promise<BulkDeleteResponse> {
    return request<BulkDeleteResponse>('/api/memories/all', {
      method: 'DELETE',
    });
  },
};
