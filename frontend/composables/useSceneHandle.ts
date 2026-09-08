import { shallowRef } from 'vue'

import type { ConvergenceScene } from './useConvergenceScene'

/**
 * The live scene, shared between the canvas that owns it and the page that
 * scrubs it.
 *
 * A module-level ref rather than provide/inject because there is exactly one
 * canvas on exactly one page, and an injection key would be ceremony around a
 * singleton.
 */
export const sceneHandle = shallowRef<ConvergenceScene | null>(null)
