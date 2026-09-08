/**
 * The one HTTP client.
 *
 * Always same-origin under /api, and always with credentials. The session is a
 * httponly, samesite=lax cookie set by app/api/auth.py, so a cross-origin call
 * would simply not carry it and every authenticated request would 401. The dev
 * proxy in nuxt.config.ts is what makes "same origin" true in development; a
 * reverse proxy does it in production.
 */

export class ApiError extends Error {
  constructor(
    readonly status: number,
    readonly detail: string,
  ) {
    super(detail)
    this.name = 'ApiError'
  }
}

export interface ApiClient {
  get<T>(path: string): Promise<T>
  post<T>(path: string, body?: unknown): Promise<T>
  patch<T>(path: string, body: unknown): Promise<T>
}

async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  let response: Response
  try {
    response = await fetch(`/api${path}`, {
      credentials: 'include',
      headers: { 'content-type': 'application/json', ...(options.headers ?? {}) },
      ...options,
    })
  } catch (cause) {
    // A network failure and a 500 are different things to a user: one is "try
    // again", the other is "this is broken". Status 0 says which.
    throw new ApiError(0, 'the server could not be reached')
  }

  if (!response.ok) {
    const detail = await response
      .clone()
      .json()
      .then((body) => body?.detail ?? response.statusText)
      .catch(() => response.statusText)
    throw new ApiError(response.status, typeof detail === 'string' ? detail : response.statusText)
  }

  // 204 has no body, and calling .json() on it throws.
  if (response.status === 204) return undefined as T
  return (await response.json()) as T
}

export function createApiClient(): ApiClient {
  return {
    get: <T>(path: string) => request<T>(path),
    post: <T>(path: string, body?: unknown) =>
      request<T>(path, {
        method: 'POST',
        body: body === undefined ? undefined : JSON.stringify(body),
      }),
    patch: <T>(path: string, body: unknown) =>
      request<T>(path, { method: 'PATCH', body: JSON.stringify(body) }),
  }
}

let shared: ApiClient | null = null

/**
 * The client the stores use.
 *
 * A module-level singleton rather than a field on Pinia state, because Nuxt
 * serialises the store state into the SSR payload and a function cannot be
 * serialised -- putting the client in state turns every server-rendered page
 * into a 500. Tests swap it with setApiClient.
 */
export function apiClient(): ApiClient {
  if (shared === null) shared = createApiClient()
  return shared
}

export function setApiClient(next: ApiClient | null): void {
  shared = next
}

export function useApi(): ApiClient {
  return apiClient()
}
