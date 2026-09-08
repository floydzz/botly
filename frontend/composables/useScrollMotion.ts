import gsap from 'gsap'
import { ScrollTrigger } from 'gsap/ScrollTrigger'

import {
  CAMERA_Z_END,
  CAMERA_Z_START,
  type ConvergenceScene,
} from './useConvergenceScene'

/**
 * The page's motion.
 *
 * ONE scrubbed timeline drives the scene -- uProgress and camera z together --
 * not one ScrollTrigger per section. Several competing ScrollTriggers on one
 * camera is exactly how scroll animation becomes jittery, and the jitter only
 * shows up on the devices least able to hide it.
 *
 * Section entrances are separate and deliberately so: they are one-shot,
 * independent of the camera, and cheap.
 *
 * | progress | beat                                            |
 * |----------|-------------------------------------------------|
 * | 0.00     | hero -- nodes wide, slow drift                   |
 * | 0.20     | channels named, labels resolve                   |
 * | 0.45     | convergence tightens, flow accelerates           |
 * | 0.70     | core blooms, inbox fragment fades in over it     |
 * | 1.00     | scene recedes, CTA holds the frame               |
 */

export interface ScrollMotion {
  destroy(): void
}

export function useScrollMotion(
  scene: ConvergenceScene | null,
  options: { reducedMotion: boolean },
): ScrollMotion {
  if (options.reducedMotion) {
    // Sections still appear -- tokens.css makes .reveal visible under reduced
    // motion -- but nothing scrubs and nothing moves continuously.
    return { destroy() {} }
  }

  gsap.registerPlugin(ScrollTrigger)

  const state = { progress: 0 }
  const triggers: ScrollTrigger[] = []

  if (scene) {
    const scrub = gsap.to(state, {
      progress: 1,
      ease: 'none',
      scrollTrigger: {
        trigger: document.documentElement,
        start: 'top top',
        end: 'bottom bottom',
        // A number, not `true`: a small amount of smoothing is what stops the
        // camera snapping on a trackpad's discrete scroll events.
        scrub: 0.6,
        onUpdate(self) {
          scene.setProgress(self.progress)
          scene.setCameraZ(
            CAMERA_Z_START + (CAMERA_Z_END - CAMERA_Z_START) * self.progress,
          )
        },
      },
    })
    if (scrub.scrollTrigger) triggers.push(scrub.scrollTrigger)
  }

  // One-shot entrances. These never touch the camera, so they cannot fight the
  // timeline above.
  document.querySelectorAll<HTMLElement>('.reveal').forEach((element) => {
    triggers.push(
      ScrollTrigger.create({
        trigger: element,
        start: 'top 82%',
        once: true,
        onEnter: () => element.classList.add('is-in'),
      }),
    )
  })

  return {
    destroy() {
      triggers.forEach((trigger) => trigger.kill())
    },
  }
}
