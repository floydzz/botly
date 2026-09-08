import { describe, expect, it } from 'vitest'

import {
  DESKTOP_PARTICLES,
  MOBILE_PARTICLES,
  TABLET_PARTICLES,
  particleCountFor,
} from '../composables/useDeviceTier'

describe('the particle budget', () => {
  it('gives a desktop the full scene', () => {
    expect(particleCountFor(1920, 8)).toBe(DESKTOP_PARTICLES)
    expect(DESKTOP_PARTICLES).toBe(60_000)
  })

  it('halves it on a tablet-width screen', () => {
    expect(particleCountFor(900, 6)).toBe(TABLET_PARTICLES)
    expect(TABLET_PARTICLES).toBe(25_000)
  })

  it('drops to the mobile tier on a narrow screen', () => {
    expect(particleCountFor(390, 6)).toBe(MOBILE_PARTICLES)
    expect(MOBILE_PARTICLES).toBe(12_000)
  })

  it('drops a wide screen with few cores to the tablet tier', () => {
    // Much of this audience is on mid-range Android, where a large viewport
    // says nothing about what the GPU will do with 60k particles.
    expect(particleCountFor(1600, 2)).toBe(TABLET_PARTICLES)
  })
})
