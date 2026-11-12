/**
 * Base HTTP client using native browser fetch and Vite /api proxy.
 */

export class ApiError extends Error {
  status: number;
  detail: string;

  constructor(status: number, detail: string) {
    super(detail);
    this.name = 'ApiError';
    this.status = status;
    this.detail = detail;
  }
}

export async function request<T>(endpoint: string, options: RequestInit = {}): Promise<T> {
  const url = endpoint.startsWith('/') ? endpoint : `/${endpoint}`;

  const headers = new Headers(options.headers || {});
  if (!headers.has('Content-Type') && options.body) {
    headers.set('Content-Type', 'application/json');
  }

  try {
    const response = await fetch(url, {
      ...options,
      headers,
    });

    if (!response.ok) {
      let errorMessage = `Request failed with status ${response.status}`;
      try {
        const errorData = await response.json();
        if (typeof errorData?.detail === 'string') {
          errorMessage = errorData.detail;
        } else if (Array.isArray(errorData?.detail)) {
          // Pydantic validation error format
          errorMessage = errorData.detail.map((err: { msg?: string }) => err.msg || 'Validation error').join(', ');
        }
      } catch {
        // Response wasn't JSON, fallback to status text
        if (response.statusText) {
          errorMessage = response.statusText;
        }
      }
      throw new ApiError(response.status, errorMessage);
    }

    // 204 No Content or empty body
    if (response.status === 204) {
      return {} as T;
    }

    return (await response.json()) as T;
  } catch (error) {
    if (error instanceof ApiError) {
      throw error;
    }
    if (error instanceof Error && error.name === 'AbortError') {
      throw error;
    }
    // Network or connection failure
    throw new ApiError(
      0,
      'Unable to connect to Foja AI backend. Ensure the FastAPI server is running on port 8000.'
    );
  }
}
