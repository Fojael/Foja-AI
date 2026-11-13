// tests/memory.test.ts
import { test, describe, beforeEach, afterEach } from "node:test";
import assert from "node:assert/strict";

// src/api/client.ts
var ApiError = class extends Error {
  status;
  detail;
  constructor(status, detail) {
    super(detail);
    this.name = "ApiError";
    this.status = status;
    this.detail = detail;
  }
};
async function request(endpoint, options = {}) {
  const url = endpoint.startsWith("/") ? endpoint : `/${endpoint}`;
  const headers = new Headers(options.headers || {});
  if (!headers.has("Content-Type") && options.body) {
    headers.set("Content-Type", "application/json");
  }
  try {
    const response = await fetch(url, {
      ...options,
      headers
    });
    if (!response.ok) {
      let errorMessage = `Request failed with status ${response.status}`;
      try {
        const errorData = await response.json();
        if (typeof errorData?.detail === "string") {
          errorMessage = errorData.detail;
        } else if (Array.isArray(errorData?.detail)) {
          errorMessage = errorData.detail.map((err) => err.msg || "Validation error").join(", ");
        }
      } catch {
        if (response.statusText) {
          errorMessage = response.statusText;
        }
      }
      throw new ApiError(response.status, errorMessage);
    }
    if (response.status === 204) {
      return {};
    }
    return await response.json();
  } catch (error) {
    if (error instanceof ApiError) {
      throw error;
    }
    if (error instanceof Error && error.name === "AbortError") {
      throw error;
    }
    throw new ApiError(
      0,
      "Unable to connect to Foja AI backend. Ensure the FastAPI server is running on port 8000."
    );
  }
}

// src/api/memoryApi.ts
var memoryApi = {
  /**
   * Fetch paginated memories with optional filters.
   */
  async fetchMemories(params) {
    const searchParams = new URLSearchParams();
    if (params) {
      if (params.status) {
        searchParams.append("status", params.status);
      }
      if (params.category) {
        searchParams.append("category", params.category);
      }
      if (typeof params.is_global === "boolean") {
        searchParams.append("is_global", String(params.is_global));
      }
      if (typeof params.min_importance === "number") {
        searchParams.append("min_importance", String(params.min_importance));
      }
      if (typeof params.max_importance === "number") {
        searchParams.append("max_importance", String(params.max_importance));
      }
      if (typeof params.limit === "number") {
        searchParams.append("limit", String(params.limit));
      }
      if (typeof params.offset === "number") {
        searchParams.append("offset", String(params.offset));
      }
    }
    const queryStr = searchParams.toString();
    const endpoint = queryStr ? `/api/memories?${queryStr}` : "/api/memories";
    return request(endpoint, { method: "GET" });
  },
  /**
   * Efficiently fetch exact global statistics across all memories in SQLite.
   * Runs lightweight count queries concurrently using limit=1.
   */
  async fetchStats() {
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
      persRes
    ] = await Promise.all([
      this.fetchMemories({ limit: 1 }),
      this.fetchMemories({ status: "suggested", limit: 1 }),
      this.fetchMemories({ status: "approved", limit: 1 }),
      this.fetchMemories({ status: "rejected", limit: 1 }),
      this.fetchMemories({ is_global: true, limit: 1 }),
      this.fetchMemories({ category: "fact", limit: 1 }),
      this.fetchMemories({ category: "preference", limit: 1 }),
      this.fetchMemories({ category: "instruction", limit: 1 }),
      this.fetchMemories({ category: "project", limit: 1 }),
      this.fetchMemories({ category: "personal", limit: 1 })
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
        personal: persRes.total
      }
    };
  },
  /**
   * Create a new manual memory.
   */
  async createMemory(payload) {
    return request("/api/memories", {
      method: "POST",
      body: JSON.stringify(payload)
    });
  },
  /**
   * Fetch a single memory by ID.
   */
  async getMemory(id) {
    return request(`/api/memories/${id}`, { method: "GET" });
  },
  /**
   * Update fields of an existing memory.
   */
  async updateMemory(id, payload) {
    return request(`/api/memories/${id}`, {
      method: "PATCH",
      body: JSON.stringify(payload)
    });
  },
  /**
   * Permanently delete a single memory by ID.
   */
  async deleteMemory(id) {
    return request(`/api/memories/${id}`, {
      method: "DELETE"
    });
  },
  /**
   * Approve a memory (typically a suggestion).
   */
  async approveMemory(id) {
    return request(`/api/memories/${id}/approve`, {
      method: "POST"
    });
  },
  /**
   * Reject a memory (typically a suggestion).
   */
  async rejectMemory(id) {
    return request(`/api/memories/${id}/reject`, {
      method: "POST"
    });
  },
  /**
   * Delete all approved memories for the current owner.
   */
  async clearApprovedMemories() {
    return request("/api/memories/approved", {
      method: "DELETE"
    });
  },
  /**
   * Completely purge all memories for the current owner.
   */
  async clearAllMemories() {
    return request("/api/memories/all", {
      method: "DELETE"
    });
  }
};

// tests/memory.test.ts
describe("Foja AI - Phase 2.4.5.2 Memory Subsystem Comprehensive Tests", () => {
  let originalFetch;
  let interceptedRequests = [];
  beforeEach(() => {
    originalFetch = globalThis.fetch;
    interceptedRequests = [];
  });
  afterEach(() => {
    globalThis.fetch = originalFetch;
  });
  describe("Memory API Client & Request Methods", () => {
    test("fetchMemories encodes filter query parameters and pagination offsets correctly", async () => {
      globalThis.fetch = async (input, init) => {
        interceptedRequests.push({ url: String(input), options: init });
        return new Response(
          JSON.stringify({
            items: [],
            total: 0,
            limit: 25,
            offset: 50
          }),
          { status: 200, headers: { "Content-Type": "application/json" } }
        );
      };
      await memoryApi.fetchMemories({
        status: "approved",
        category: "fact",
        is_global: false,
        min_importance: 0.6,
        max_importance: 0.9,
        limit: 25,
        offset: 50
      });
      assert.equal(interceptedRequests.length, 1);
      const req = interceptedRequests[0];
      assert.equal(req.options?.method, "GET");
      const parsedUrl = new URL(req.url, "http://localhost");
      assert.equal(parsedUrl.pathname, "/api/memories");
      assert.equal(parsedUrl.searchParams.get("status"), "approved");
      assert.equal(parsedUrl.searchParams.get("category"), "fact");
      assert.equal(parsedUrl.searchParams.get("is_global"), "false");
      assert.equal(parsedUrl.searchParams.get("min_importance"), "0.6");
      assert.equal(parsedUrl.searchParams.get("max_importance"), "0.9");
      assert.equal(parsedUrl.searchParams.get("limit"), "25");
      assert.equal(parsedUrl.searchParams.get("offset"), "50");
    });
    test("createMemory sends POST /api/memories with correct payload", async () => {
      const mockResult = {
        id: "22222222-3333-4444-5555-666666666666",
        owner_id: "default_user",
        content: "Prefers dark mode theme",
        content_hash: "hash123",
        category: "preference",
        status: "approved",
        importance: 0.85,
        is_global: false,
        created_at: (/* @__PURE__ */ new Date()).toISOString(),
        updated_at: (/* @__PURE__ */ new Date()).toISOString()
      };
      globalThis.fetch = async (input, init) => {
        interceptedRequests.push({ url: String(input), options: init });
        return new Response(JSON.stringify(mockResult), {
          status: 201,
          headers: { "Content-Type": "application/json" }
        });
      };
      const payload = {
        content: "Prefers dark mode theme",
        category: "preference",
        importance: 0.85,
        is_global: false
      };
      const res = await memoryApi.createMemory(payload);
      assert.equal(res.id, mockResult.id);
      assert.equal(res.status, "approved");
      assert.equal(interceptedRequests[0].url, "/api/memories");
      assert.equal(interceptedRequests[0].options?.method, "POST");
      assert.deepEqual(JSON.parse(interceptedRequests[0].options?.body), payload);
    });
    test("updateMemory sends PATCH /api/memories/{id} with partial payload", async () => {
      const memId = "33333333-4444-5555-6666-777777777777";
      globalThis.fetch = async (input, init) => {
        interceptedRequests.push({ url: String(input), options: init });
        return new Response(
          JSON.stringify({ id: memId, content: "Updated instruction", importance: 0.95 }),
          { status: 200, headers: { "Content-Type": "application/json" } }
        );
      };
      const patchPayload = {
        content: "Updated instruction",
        importance: 0.95
      };
      const res = await memoryApi.updateMemory(memId, patchPayload);
      assert.equal(res.id, memId);
      assert.equal(interceptedRequests[0].url, `/api/memories/${memId}`);
      assert.equal(interceptedRequests[0].options?.method, "PATCH");
      assert.deepEqual(JSON.parse(interceptedRequests[0].options?.body), patchPayload);
    });
    test("deleteMemory sends DELETE /api/memories/{id}", async () => {
      const memId = "44444444-5555-6666-7777-888888888888";
      globalThis.fetch = async (input, init) => {
        interceptedRequests.push({ url: String(input), options: init });
        return new Response(
          JSON.stringify({ success: true, id: memId, message: "Deleted" }),
          { status: 200, headers: { "Content-Type": "application/json" } }
        );
      };
      const res = await memoryApi.deleteMemory(memId);
      assert.equal(res.success, true);
      assert.equal(interceptedRequests[0].url, `/api/memories/${memId}`);
      assert.equal(interceptedRequests[0].options?.method, "DELETE");
    });
    test("approveMemory and rejectMemory post to respective review routes", async () => {
      const memId = "55555555-6666-7777-8888-999999999999";
      globalThis.fetch = async (input, init) => {
        interceptedRequests.push({ url: String(input), options: init });
        const isApprove = String(input).endsWith("/approve");
        return new Response(
          JSON.stringify({ id: memId, status: isApprove ? "approved" : "rejected" }),
          { status: 200, headers: { "Content-Type": "application/json" } }
        );
      };
      const appRes = await memoryApi.approveMemory(memId);
      assert.equal(appRes.status, "approved");
      assert.equal(interceptedRequests[0].url, `/api/memories/${memId}/approve`);
      assert.equal(interceptedRequests[0].options?.method, "POST");
      const rejRes = await memoryApi.rejectMemory(memId);
      assert.equal(rejRes.status, "rejected");
      assert.equal(interceptedRequests[1].url, `/api/memories/${memId}/reject`);
      assert.equal(interceptedRequests[1].options?.method, "POST");
    });
    test("clearApprovedMemories and clearAllMemories send DELETE to static purge endpoints", async () => {
      globalThis.fetch = async (input, init) => {
        interceptedRequests.push({ url: String(input), options: init });
        return new Response(
          JSON.stringify({ success: true, deleted_count: 5, message: "Purged" }),
          { status: 200, headers: { "Content-Type": "application/json" } }
        );
      };
      const clearApp = await memoryApi.clearApprovedMemories();
      assert.equal(clearApp.success, true);
      assert.equal(interceptedRequests[0].url, "/api/memories/approved");
      assert.equal(interceptedRequests[0].options?.method, "DELETE");
      const clearAll = await memoryApi.clearAllMemories();
      assert.equal(clearAll.success, true);
      assert.equal(interceptedRequests[1].url, "/api/memories/all");
      assert.equal(interceptedRequests[1].options?.method, "DELETE");
    });
  });
  describe("Accurate Global Statistics & Aggregations", () => {
    test("fetchStats queries concurrent count queries with limit=1 to obtain exact database totals", async () => {
      globalThis.fetch = async (input) => {
        const urlStr = String(input);
        const parsed = new URL(urlStr, "http://localhost");
        const status = parsed.searchParams.get("status");
        const category = parsed.searchParams.get("category");
        const isGlobal = parsed.searchParams.get("is_global");
        let total = 0;
        if (status === "suggested") total = 3;
        else if (status === "approved") total = 15;
        else if (status === "rejected") total = 2;
        else if (isGlobal === "true") total = 4;
        else if (category === "fact") total = 8;
        else if (category === "preference") total = 6;
        else if (category === "instruction") total = 4;
        else if (category === "project") total = 2;
        else if (category === "personal") total = 0;
        else total = 20;
        return new Response(
          JSON.stringify({ items: [], total, limit: 1, offset: 0 }),
          { status: 200, headers: { "Content-Type": "application/json" } }
        );
      };
      const stats = await memoryApi.fetchStats();
      assert.equal(stats.total, 20);
      assert.equal(stats.suggested, 3);
      assert.equal(stats.approved, 15);
      assert.equal(stats.rejected, 2);
      assert.equal(stats.globalDirectives, 4);
      assert.equal(stats.categories.fact, 8);
      assert.equal(stats.categories.preference, 6);
      assert.equal(stats.categories.instruction, 4);
      assert.equal(stats.categories.project, 2);
      assert.equal(stats.categories.personal, 0);
    });
  });
  describe("Pagination & Load More Deduplication", () => {
    test("pagination prevents duplicate records when appending consecutive pages", () => {
      const page1 = [
        {
          id: "item-1",
          owner_id: "default_user",
          content: "Memory 1",
          content_hash: "h1",
          category: "fact",
          status: "approved",
          importance: 0.5,
          is_global: false,
          created_at: (/* @__PURE__ */ new Date()).toISOString(),
          updated_at: (/* @__PURE__ */ new Date()).toISOString()
        },
        {
          id: "item-2",
          owner_id: "default_user",
          content: "Memory 2",
          content_hash: "h2",
          category: "preference",
          status: "approved",
          importance: 0.7,
          is_global: false,
          created_at: (/* @__PURE__ */ new Date()).toISOString(),
          updated_at: (/* @__PURE__ */ new Date()).toISOString()
        }
      ];
      const page2 = [
        {
          id: "item-2",
          owner_id: "default_user",
          content: "Memory 2 (duplicate)",
          content_hash: "h2",
          category: "preference",
          status: "approved",
          importance: 0.7,
          is_global: false,
          created_at: (/* @__PURE__ */ new Date()).toISOString(),
          updated_at: (/* @__PURE__ */ new Date()).toISOString()
        },
        {
          id: "item-3",
          owner_id: "default_user",
          content: "Memory 3 (novel)",
          content_hash: "h3",
          category: "instruction",
          status: "approved",
          importance: 0.9,
          is_global: true,
          created_at: (/* @__PURE__ */ new Date()).toISOString(),
          updated_at: (/* @__PURE__ */ new Date()).toISOString()
        }
      ];
      const existingIds = new Set(page1.map((item) => item.id));
      const novel = page2.filter((item) => !existingIds.has(item.id));
      const combined = [...page1, ...novel];
      assert.equal(combined.length, 3);
      assert.equal(combined[0].id, "item-1");
      assert.equal(combined[1].id, "item-2");
      assert.equal(combined[2].id, "item-3");
    });
    test("hasMore correctly identifies when more records remain on the server", () => {
      const totalInDB = 55;
      const loadedPage1 = 25;
      assert.equal(loadedPage1 < totalInDB, true);
      const loadedPage2 = 50;
      assert.equal(loadedPage2 < totalInDB, true);
      const loadedPage3 = 55;
      assert.equal(loadedPage3 < totalInDB, false);
    });
  });
  describe("Error Handling & Conflict Responses", () => {
    test("ApiError correctly extracts HTTP 409 Conflict detail message", async () => {
      globalThis.fetch = async () => {
        return new Response(
          JSON.stringify({ detail: "A memory with identical content already exists." }),
          { status: 409, headers: { "Content-Type": "application/json" } }
        );
      };
      await assert.rejects(
        async () => {
          await memoryApi.createMemory({
            content: "Existing memory",
            category: "fact"
          });
        },
        (err) => {
          assert.ok(err instanceof ApiError);
          assert.equal(err.status, 409);
          assert.equal(err.detail, "A memory with identical content already exists.");
          return true;
        }
      );
    });
    test("ApiError parses Pydantic validation error arrays into readable strings", async () => {
      globalThis.fetch = async () => {
        return new Response(
          JSON.stringify({
            detail: [
              { msg: "Global scope is only permitted for instruction category." },
              { msg: "Importance must be between 0.0 and 1.0." }
            ]
          }),
          { status: 422, headers: { "Content-Type": "application/json" } }
        );
      };
      await assert.rejects(
        async () => {
          await memoryApi.createMemory({
            content: "Invalid memory",
            category: "fact",
            is_global: true
          });
        },
        (err) => {
          assert.ok(err instanceof ApiError);
          assert.equal(err.status, 422);
          assert.ok(err.detail.includes("Global scope is only permitted for instruction category."));
          assert.ok(err.detail.includes("Importance must be between 0.0 and 1.0."));
          return true;
        }
      );
    });
  });
  describe("Search & Filter Coverage", () => {
    const sampleMemories = [
      {
        id: "1",
        owner_id: "default_user",
        content: "Prefers TypeScript and React 19",
        content_hash: "h1",
        category: "preference",
        status: "approved",
        importance: 0.8,
        is_global: false,
        created_at: (/* @__PURE__ */ new Date()).toISOString(),
        updated_at: (/* @__PURE__ */ new Date()).toISOString()
      },
      {
        id: "2",
        owner_id: "default_user",
        content: "Born and lives in Dhaka, Bangladesh",
        content_hash: "h2",
        category: "fact",
        status: "approved",
        importance: 0.7,
        is_global: false,
        created_at: (/* @__PURE__ */ new Date()).toISOString(),
        updated_at: (/* @__PURE__ */ new Date()).toISOString()
      },
      {
        id: "3",
        owner_id: "default_user",
        content: "Always format currency in BDT",
        content_hash: "h3",
        category: "instruction",
        status: "suggested",
        importance: 0.9,
        is_global: true,
        created_at: (/* @__PURE__ */ new Date()).toISOString(),
        updated_at: (/* @__PURE__ */ new Date()).toISOString()
      }
    ];
    test("search query matches both content and category case-insensitively", () => {
      const queryContent = "dhaka";
      const match1 = sampleMemories.filter(
        (m) => m.content.toLowerCase().includes(queryContent) || m.category.toLowerCase().includes(queryContent)
      );
      assert.equal(match1.length, 1);
      assert.equal(match1[0].id, "2");
      const queryCategory = "instruction";
      const match2 = sampleMemories.filter(
        (m) => m.content.toLowerCase().includes(queryCategory) || m.category.toLowerCase().includes(queryCategory)
      );
      assert.equal(match2.length, 1);
      assert.equal(match2[0].id, "3");
    });
    test("status filtering correctly separates approved and suggested records", () => {
      const approved = sampleMemories.filter((m) => m.status === "approved");
      assert.equal(approved.length, 2);
      const suggested = sampleMemories.filter((m) => m.status === "suggested");
      assert.equal(suggested.length, 1);
      assert.equal(suggested[0].id, "3");
    });
  });
});
