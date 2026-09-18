export interface BotConfig {
  id: number
  brand_id: number
  name: string
  persona: string
  llm_model_id: number | null
  escalation_max_bot_turns: number
  tool_write_mode: 'confirm_customer' | 'auto_execute'
  auditor_enabled: boolean
}

export interface BotWorker { key: string; name: string; description: string; enabled: boolean; config: Record<string, unknown> }
export interface KnowledgeDocument { id: number; bot_id: number; filename: string; status: string; embedding_model: string; chunk_count: number; error: string | null; created_at: string }

export interface ModelOption {
  id: number
  provider: string
  name: string
  model_code: string
  available: boolean
  input_credits_per_million: string
  output_credits_per_million: string
  cached_credits_per_million: string
}

export interface ChannelConnection {
  id: number
  bot_id: number
  provider: string
  external_ref: string
  username: string | null
  status: string
}

export interface CreditWallet {
  balance: string
  reserved: string
  available: string
  credits_per_usd: string
}

export interface UsageRow {
  id: number
  model: string
  provider: string
  status: string
  input_tokens: number | null
  output_tokens: number | null
  charged_credits: string
  reserved_credits: string
  created_at: string
}
