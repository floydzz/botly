import { defineStore } from 'pinia'

import { apiClient } from '../composables/useApi'
import { useAuthStore } from './auth'
import type {
  ConversationCounts,
  ConversationDetail,
  ConversationSummary,
  InboxFilters,
  MessageOut,
  Page,
} from '../types/inbox'

interface InboxState {
  conversations: ConversationSummary[]
  nextCursor: string | null
  detail: ConversationDetail | null
  messages: MessageOut[]
  messagesCursor: string | null
  counts: ConversationCounts
  filters: InboxFilters
  listLoading: boolean
  threadLoading: boolean
  actionLoading: boolean
  error: string | null
}

const emptyCounts = (): ConversationCounts => ({
  all: 0,
  needs_attention: 0,
  mine: 0,
  unread: 0,
  resolved: 0,
})

export const useInboxStore = defineStore('inbox', {
  state: (): InboxState => ({
    conversations: [],
    nextCursor: null,
    detail: null,
    messages: [],
    messagesCursor: null,
    counts: emptyCounts(),
    filters: { state: [], provider: [], assignee: null, unread: false },
    listLoading: false,
    threadLoading: false,
    actionLoading: false,
    error: null,
  }),

  getters: {
    openId: state => state.detail?.id ?? null,
    providers: state => [...new Set(state.conversations.map(item => item.provider))].sort(),
  },

  actions: {
    query(cursor?: string | null) {
      const params = new URLSearchParams()
      this.filters.state.forEach(value => params.append('state', value))
      this.filters.provider.forEach(value => params.append('provider', value))
      if (this.filters.assignee) params.set('assignee', this.filters.assignee)
      if (this.filters.unread) params.set('unread', 'true')
      if (cursor) params.set('cursor', cursor)
      return params.toString()
    },

    async fetchList(reset = true) {
      if (!reset && !this.nextCursor) return
      this.listLoading = true
      this.error = null
      try {
        const cursor = reset ? null : this.nextCursor
        const suffix = this.query(cursor)
        const page = await apiClient().get<Page<ConversationSummary>>(
          `/conversations${suffix ? `?${suffix}` : ''}`,
        )
        this.conversations = reset
          ? page.items
          : [...this.conversations, ...page.items.filter(item => !this.conversations.some(old => old.id === item.id))]
        this.nextCursor = page.next_cursor
      } catch (error) {
        this.error = 'Conversations could not be loaded.'
        throw error
      } finally {
        this.listLoading = false
      }
    },

    async fetchCounts() {
      this.counts = await apiClient().get<ConversationCounts>('/conversations/counts')
    },

    async refresh() {
      await Promise.all([this.fetchList(true), this.fetchCounts()])
    },

    async openConversation(id: number) {
      this.threadLoading = true
      this.error = null
      try {
        const [detail, page] = await Promise.all([
          apiClient().get<ConversationDetail>(`/conversations/${id}`),
          apiClient().get<Page<MessageOut>>(`/conversations/${id}/messages`),
        ])
        this.detail = detail
        this.messages = [...page.items].reverse()
        this.messagesCursor = page.next_cursor
        await this.markRead(id)
      } catch (error) {
        this.error = 'This conversation could not be opened.'
        throw error
      } finally {
        this.threadLoading = false
      }
    },

    async loadEarlier() {
      if (!this.detail || !this.messagesCursor) return
      const page = await apiClient().get<Page<MessageOut>>(
        `/conversations/${this.detail.id}/messages?cursor=${encodeURIComponent(this.messagesCursor)}`,
      )
      this.messages = [...page.items].reverse().concat(this.messages)
      this.messagesCursor = page.next_cursor
    },

    async markRead(id: number) {
      const row = this.conversations.find(item => item.id === id)
      const wasUnread = row?.unread || this.detail?.unread || false
      await apiClient().post<void>(`/conversations/${id}/read`)
      if (row) row.unread = false
      if (this.detail?.id === id) this.detail.unread = false
      if (wasUnread && this.counts.unread > 0) this.counts.unread--
    },

    async updateAction(action: 'takeover' | 'release' | 'resolve') {
      if (!this.detail) return
      this.actionLoading = true
      this.error = null
      try {
        const updated = await apiClient().post<ConversationDetail>(
          `/conversations/${this.detail.id}/${action}`,
        )
        this.detail = updated
        this.applyConversationUpdated({ conversation: updated })
        await this.fetchCounts()
      } catch (error) {
        this.error = error instanceof Error ? error.message : 'The conversation could not be updated.'
        throw error
      } finally {
        this.actionLoading = false
      }
    },

    takeover() { return this.updateAction('takeover') },
    release() { return this.updateAction('release') },
    resolve() { return this.updateAction('resolve') },

    async send(text: string) {
      if (!this.detail) return
      const message = await apiClient().post<MessageOut>(
        `/conversations/${this.detail.id}/messages`,
        { text },
      )
      if (!this.messages.some(item => item.id === message.id)) this.messages.push(message)
      await this.fetchList(true)
      return message
    },

    applyMessageCreated(event: { conversation_id: number; message: MessageOut }) {
      if (this.detail?.id !== event.conversation_id) return
      if (!this.messages.some(item => item.id === event.message.id)) this.messages.push(event.message)
    },

    applyConversationUpdated(event: { conversation: ConversationSummary }) {
      const updated = event.conversation
      const existingIndex = this.conversations.findIndex(item => item.id === updated.id)
      const included = this.matchesFilters(updated)
      if (!included) {
        if (existingIndex >= 0) this.conversations.splice(existingIndex, 1)
        return
      }
      if (existingIndex >= 0) this.conversations.splice(existingIndex, 1)
      this.conversations.unshift(updated)
      if (this.detail?.id === updated.id) {
        this.detail = { ...this.detail, ...updated }
      }
    },

    matchesFilters(item: ConversationSummary) {
      const { state, provider, assignee, unread } = this.filters
      if (state.length && !state.includes(item.handoff_state)) return false
      if (provider.length && !provider.includes(item.provider)) return false
      if (assignee === 'me' && item.assignee?.id !== useAuthStore().user?.id) return false
      if (assignee === 'unassigned' && item.assignee !== null) return false
      if (unread && !item.unread) return false
      return true
    },

    clearThread() {
      this.detail = null
      this.messages = []
      this.messagesCursor = null
    },
  },
})
