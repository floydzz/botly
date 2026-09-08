/**
 * How much scene this device can afford.
 *
 * The budget is a correctness requirement rather than an optimisation: a
 * landing page that stutters undermines the exact claim it is making, and much
 * of this audience is on mid-range Android.
 *
 * Split out from the scene itself so the decision is testable without a GPU.
 */

export const DESKTOP_PARTICLES = 60_000
export const TABLET_PARTICLES = 25_000
export const MOBILE_PARTICLES = 12_000

/**
 * Width *and* core count. A large viewport says nothing about what the GPU
 * will do with 60k particles -- a cheap 1080p Android tablet reports a wide
 * screen and then drops to eight frames a second.
 */
export function particleCountFor(width: number, cores: number): number {
  if (width < 640) return MOBILE_PARTICLES
  if (width < 1280 || cores <= 4) return TABLET_PARTICLES
  return DESKTOP_PARTICLES
}

export function prefersReducedMotion(): boolean {
  if (typeof window === 'undefined' || !window.matchMedia) return false
  return window.matchMedia('(prefers-reduced-motion: reduce)').matches
}

export function supportsWebgl(): boolean {
  if (typeof document === 'undefined') return false
  try {
    const probe = document.createElement('canvas')
    const context =
      probe.getContext('webgl2') ??
      probe.getContext('webgl') ??
      probe.getContext('experimental-webgl')
    // Release it immediately. Browsers cap live contexts, and holding a probe
    // open costs the real canvas one of them.
    const lose = (context as WebGLRenderingContext | null)?.getExtension('WEBGL_lose_context')
    lose?.loseContext()
    return context !== null
  } catch {
    return false
  }
}

export interface DeviceTier {
  particles: number
  reducedMotion: boolean
  webgl: boolean
}

export function useDeviceTier(): DeviceTier {
  if (typeof window === 'undefined') {
    // Server render: assume the cautious tier. The canvas is client-only
    // anyway, so this value is never used to draw anything.
    return { particles: MOBILE_PARTICLES, reducedMotion: true, webgl: false }
  }
  return {
    particles: particleCountFor(window.innerWidth, navigator.hardwareConcurrency ?? 4),
    reducedMotion: prefersReducedMotion(),
    webgl: supportsWebgl(),
  }
}
