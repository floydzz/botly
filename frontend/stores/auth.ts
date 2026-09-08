import { defineStore } from 'pinia'

import { ApiError, apiClient } from '../composables/useApi'

export interface AuthUser {
  id: number
  email: string
  name: string
  merchant_id: number
}

interface AuthState {
  user: AuthUser | null
  /** Whether /auth/me has been asked once. Guards the global middleware from
   *  hitting the server on every navigation. */
  ready: boolean
}

export const useAuthStore = defineStore('auth', {
  state: (): AuthState => ({
    user: null,
    ready: false,
  }),

  getters: {
    signedIn: (state) => state.user !== null,
  },

  actions: {
    async fetchMe(): Promise<void> {
      if (this.ready) return
      try {
        this.user = await apiClient().get<AuthUser>('/auth/me')
      } catch (error) {
        // 401 is the expected answer for a visitor, not an error worth
        // surfacing. Anything else is also "not signed in" as far as the guard
        // is concerned; the page that needed data will report its own failure.
        this.user = null
      } finally {
        this.ready = true
      }
    },

    async login(email: string, password: string): Promise<void> {
      this.user = await apiClient().post<AuthUser>('/auth/login', { email, password })
      this.ready = true
    },

    async logout(): Promise<void> {
      try {
        await apiClient().post<void>('/auth/logout')
      } catch (error) {
        // Whatever the server said, this browser is done with the session.
        if (!(error instanceof ApiError)) throw error
      }
      this.user = null
      this.ready = true
    },

    /** Called by the API layer on a 401 from any authenticated request. */
    clear(): void {
      this.user = null
      this.ready = true
    },
  },
})
