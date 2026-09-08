<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref, shallowRef } from 'vue'

import { useConvergenceScene, type NodeScreenPosition } from '~/composables/useConvergenceScene'
import { useDeviceTier } from '~/composables/useDeviceTier'
import { sceneHandle } from '~/composables/useSceneHandle'

const canvas = ref<HTMLCanvasElement | null>(null)
const labels = shallowRef<NodeScreenPosition[]>([])
/**
 * Starts true so the poster is what server-renders and what a visitor without
 * WebGL keeps. The canvas has to earn its place; the page never waits for it.
 */
const fallback = ref(true)

let labelFrame = 0

onMounted(() => {
  const tier = useDeviceTier()
  if (!tier.webgl || !canvas.value) return

  let scene
  try {
    scene = useConvergenceScene(canvas.value, {
      particles: tier.particles,
      reducedMotion: tier.reducedMotion,
    })
  } catch (cause) {
    // A driver that reports WebGL and then refuses to compile a shader is a
    // real thing on older Android. The poster is still correct -- but say so
    // out loud, because a silently blank scene is close to undebuggable.
    console.warn('[botly] the convergence scene could not start; showing the poster', cause)
    return
  }

  sceneHandle.value = scene
  fallback.value = false
  scene.start()

  // Labels are projected on their own modest loop rather than inside the
  // render loop, so DOM writes never sit between two GPU frames. Under reduced
  // motion the scene is one static frame, so one projection is enough.
  const project = () => {
    labels.value = scene.nodeScreenPositions()
    if (!tier.reducedMotion) labelFrame = requestAnimationFrame(project)
  }
  project()

  canvas.value.addEventListener('webglcontextlost', (event) => {
    event.preventDefault()
    scene.stop()
    fallback.value = true
  })
})

onBeforeUnmount(() => {
  cancelAnimationFrame(labelFrame)
  sceneHandle.value?.dispose()
  sceneHandle.value = null
})
</script>

<template>
  <div class="pointer-events-none fixed inset-0 z-0" aria-hidden="true">
    <!--
      Not wrapped in ClientOnly: an empty <canvas> renders identically on both
      sides, and ClientOnly would defer the element past this component's own
      onMounted, leaving the ref null and the scene never started.
    -->
    <canvas
      ref="canvas"
      class="size-full transition-opacity duration-enter ease-house"
      :class="fallback && 'opacity-0'"
    />

    <!--
      The poster. Inline SVG rather than a raster file: it is a fifth of the
      bytes, never blurs, and costs no extra request on the render path of a
      page whose whole argument is that it is fast.
    -->
    <LandingPoster v-if="fallback" />

    <span
      v-for="label in labels"
      v-show="label.visible"
      :key="label.id"
      class="type-label absolute -translate-x-1/2 -translate-y-1/2 whitespace-nowrap text-dim transition-opacity duration-enter"
      :style="{ left: `${label.x}px`, top: `${label.y}px` }"
    >
      {{ label.label }}
    </span>
  </div>
</template>
