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
  const animations: gsap.core.Animation[] = []

  // The opening beat resolves in layers: navigation, thesis, supporting copy,
  // then the controls. Short offsets keep it intentional without holding the
  // visitor hostage behind a splash animation.
  const heroIntro = gsap.timeline({ defaults: { ease: 'power3.out' } })
    .from('.nav-shell', { y: -18, opacity: 0, duration: 0.7 })
    .from('.hero-kicker', { y: 16, opacity: 0, duration: 0.65 }, '-=0.35')
    .from('.hero-title', { y: 54, opacity: 0, rotateX: -8, transformOrigin: '50% 100%', duration: 1.1 }, '-=0.4')
    .from('.hero-copy .type-lead, .hero-orbit-copy, .hero-copy a', { y: 18, opacity: 0, duration: 0.7, stagger: 0.09 }, '-=0.55')
  animations.push(heroIntro)

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
    animations.push(scrub)
    if (scrub.scrollTrigger) triggers.push(scrub.scrollTrigger)
  }

  const words = gsap.utils.toArray<HTMLElement>('.scrub-word')
  if (words.length) {
    gsap.set(words, { opacity: 0.12 })
    const wordReveal = gsap.to(words, {
      opacity: 1,
      stagger: 0.055,
      ease: 'none',
      scrollTrigger: {
        trigger: '.scrub-statement',
        start: 'top 78%',
        end: 'bottom 34%',
        scrub: 0.45,
      },
    })
    animations.push(wordReveal)
    if (wordReveal.scrollTrigger) triggers.push(wordReveal.scrollTrigger)
  }

  const cards = gsap.utils.toArray<HTMLElement>('.stack-card')
  cards.slice(0, -1).forEach((card, index) => {
    const next = cards[index + 1]
    if (!next) return
    const stack = gsap.to(card, {
      scale: 0.92,
      opacity: 0.42,
      filter: 'blur(2px)',
      ease: 'none',
      scrollTrigger: {
        trigger: next,
        start: 'top 72%',
        end: 'top 18%',
        scrub: 0.35,
      },
    })
    animations.push(stack)
    if (stack.scrollTrigger) triggers.push(stack.scrollTrigger)
  })

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
      animations.forEach((animation) => animation.kill())
    },
  }
}
