export type HandoffState = 'bot' | 'pending_human' | 'human' | 'resolved'
export type DeliveryStatus = 'sent' | 'pending' | 'failed'
export type SenderType = 'customer' | 'bot' | 'agent'

export interface UserRef { id: number; name: string }
export interface BotRef { id: number; name: string }

export interface SendPolicy {
  can_send_freeform: boolean
  reason: string | null
  max_text_len: number
  supports_media: boolean
  window_closes_at: string | null
}

export interface ConversationSummary {
  id: number
  customer_name: string | null
  customer_ref: string
  provider: string
  connection_id: number
  bot: BotRef
  handoff_state: HandoffState
  escalation_reason: string | null
  assignee: UserRef | null
  last_message_at: string | null
  last_message_preview: string | null
  unread: boolean
  has_failed_delivery: boolean
}

export interface ConversationDetail extends ConversationSummary {
  send_policy: SendPolicy
}

export interface MessageOut {
  id: number
  direction: 'in' | 'out'
  sender_type: SenderType
  sender: UserRef | null
  text: string | null
  attachments: Array<Record<string, unknown>>
  provider_message_id: string | null
  delivery_status: DeliveryStatus
  error: string | null
  created_at: string
}

export interface Page<T> { items: T[]; next_cursor: string | null }

export interface ConversationCounts {
  all: number
  needs_attention: number
  mine: number
  unread: number
  resolved: number
}

export interface InboxFilters {
  state: HandoffState[]
  provider: string[]
  assignee: 'me' | 'unassigned' | null
  unread: boolean
}
