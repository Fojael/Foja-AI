export type MemoryCategory = 'preference' | 'fact' | 'project' | 'instruction' | 'personal';

export type MemoryStatus = 'suggested' | 'approved' | 'rejected';

export interface MemoryRead {
  id: string;
  owner_id: string;
  content: string;
  content_hash: string;
  category: MemoryCategory;
  status: MemoryStatus;
  importance: number;
  is_global: boolean;
  source_conversation_id?: string | null;
  created_at: string;
  updated_at: string;
}

export interface MemoryCreate {
  content: string;
  category?: MemoryCategory;
  importance?: number;
  is_global?: boolean;
}

export interface MemoryUpdate {
  content?: string;
  category?: MemoryCategory;
  importance?: number;
  is_global?: boolean;
}

export interface MemoryListResponse {
  items: MemoryRead[];
  total: number;
  limit: number;
  offset: number;
}

export interface DeleteResponse {
  success: boolean;
  id: string;
  message: string;
}

export interface BulkDeleteResponse {
  success: boolean;
  deleted_count: number;
  message: string;
}

export interface MemoryQueryParams {
  status?: MemoryStatus;
  category?: MemoryCategory;
  is_global?: boolean;
  min_importance?: number;
  max_importance?: number;
  limit?: number;
  offset?: number;
}

export interface MemoryStats {
  total: number;
  approved: number;
  suggested: number;
  rejected: number;
  globalDirectives: number;
  categories: Record<MemoryCategory, number>;
}
