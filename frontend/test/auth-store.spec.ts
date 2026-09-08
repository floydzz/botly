import { createPinia, setActivePinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { ApiError, setApiClient, type ApiClient } from '../composables/useApi'
import { useAuthStore } from '../stores/auth'

const ANI = { id: 1, name: 'Ani', email: 'ani@example.com', merchant_id: 2 }

function stub(overrides: Partial<ApiClient>): ApiClient {
  const refuse = () => Promise.reject(new Error('not stubbed'))
  return { get: refuse, post: refuse, patch: refuse, ...overrides } as ApiClient
}

describe('the auth store', () => {
  beforeEach(() => setActivePinia(createPinia()))
  afterEach(() => setApiClient(null))

  it('holds the user a successful login returns', async () => {
    setApiClient(stub({ post: vi.fn().mockResolvedValue(ANI) }))
    const store = useAuthStore()

    await store.login('ani@example.com', 'pw')

    expect(store.user?.name).toBe('Ani')
    expect(store.signedIn).toBe(true)
  })

  it('leaves the store signed out when /auth/me answers 401', async () => {
    setApiClient(stub({ get: vi.fn().mockRejectedValue(new ApiError(401, 'not authenticated')) }))
    const store = useAuthStore()

    await store.fetchMe()

    expect(store.user).toBeNull()
    // ready is still true: a visitor is a settled answer, not a pending one,
    // and the guard must not ask again on every navigation.
    expect(store.ready).toBe(true)
  })

  it('asks the server only once for a session it already resolved', async () => {
    const get = vi.fn().mockResolvedValue(ANI)
    setApiClient(stub({ get }))
    const store = useAuthStore()

    await store.fetchMe()
    await store.fetchMe()

    expect(get).toHaveBeenCalledTimes(1)
  })

  it('signs out locally even when the server refuses the logout', async () => {
    setApiClient(
      stub({ post: vi.fn().mockRejectedValue(new ApiError(0, 'the server could not be reached')) }),
    )
    const store = useAuthStore()
    store.user = ANI

    await store.logout()

    expect(store.user).toBeNull()
  })
})
