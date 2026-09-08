export type ChannelStatus = 'live' | 'pending'

export interface Channel {
  id: 'telegram' | 'whatsapp' | 'shopee'
  name: string
  status: ChannelStatus
  /** What a seller can actually expect today. */
  note: string
  hue: string
}

/**
 * The channels the page is allowed to claim.
 *
 * A grid of four logos implying four working integrations is a claim the
 * product cannot honour, made to exactly the buyer who would notice. So the
 * list carries status, `docs/approvals.md` is its source of truth, and
 * test/channels.spec.ts turns that from a convention into a failing test.
 *
 * RedNote is absent on purpose. The architecture spec is explicit that it must
 * not be marketed until a legitimate API exists.
 */
export const CHANNELS: Channel[] = [
  {
    id: 'telegram',
    name: 'Telegram',
    status: 'live',
    note: 'Live today. A bot token and a webhook — there is no approval queue in front of it.',
    hue: 'var(--channel-telegram)',
  },
  {
    id: 'whatsapp',
    name: 'WhatsApp Business',
    status: 'pending',
    note: 'The adapter is built. Meta business verification has not cleared, so we are not offering it to sellers yet.',
    hue: 'var(--channel-whatsapp)',
  },
  {
    id: 'shopee',
    name: 'Shopee',
    status: 'pending',
    note: 'Waiting on Shopee Open Platform partner registration. Not available to sellers until it clears.',
    hue: 'var(--channel-shopee)',
  },
]

export const STATUS_COPY: Record<ChannelStatus, string> = {
  live: 'Available now',
  pending: 'Awaiting provider approval',
}
