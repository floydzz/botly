import { describe, expect, it } from 'vitest'

import { CHANNELS } from '../content/channels'

describe('the channels the landing page claims', () => {
  it('offers only what actually works today', () => {
    const live = CHANNELS.filter((channel) => channel.status === 'live').map((c) => c.id)
    expect(live).toEqual(['telegram'])
  })

  it('marks the approval-gated channels as pending rather than available', () => {
    // docs/approvals.md: as of 2026-09-05 neither WhatsApp business
    // verification nor Shopee partner registration had been started.
    const pending = CHANNELS.filter((channel) => channel.status === 'pending')
      .map((c) => c.id)
      .sort()
    expect(pending).toEqual(['shopee', 'whatsapp'])
  })

  it('does not mention rednote anywhere', () => {
    // The architecture spec is explicit: RedNote must not be marketed until a
    // legitimate API exists.
    expect(JSON.stringify(CHANNELS).toLowerCase()).not.toContain('rednote')
  })

  it('gives every channel an honest one-line status', () => {
    for (const channel of CHANNELS) {
      expect(channel.note.length).toBeGreaterThan(0)
    }
  })
})
