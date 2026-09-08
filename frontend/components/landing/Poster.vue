<script setup lang="ts">
/**
 * The scene, composed once and drawn flat.
 *
 * Shown when there is no WebGL, when a context is lost, and on the server
 * before hydration. The page is fully readable and the CTA fully usable with
 * nothing but this behind it -- which is the actual requirement; the canvas is
 * an enhancement, not the page.
 */
</script>

<template>
  <svg
    class="absolute inset-0 size-full"
    viewBox="0 0 1600 900"
    preserveAspectRatio="xMidYMid slice"
    role="presentation"
  >
    <defs>
      <radialGradient id="poster-core" cx="50%" cy="50%" r="50%">
        <stop offset="0%" stop-color="var(--accent-lit)" stop-opacity="0.55" />
        <stop offset="35%" stop-color="var(--accent)" stop-opacity="0.22" />
        <stop offset="100%" stop-color="var(--accent)" stop-opacity="0" />
      </radialGradient>

      <linearGradient id="poster-telegram" x1="0" y1="0" x2="1" y2="1">
        <stop offset="0%" stop-color="var(--channel-telegram)" stop-opacity="0.55" />
        <stop offset="100%" stop-color="var(--accent)" stop-opacity="0.1" />
      </linearGradient>
      <linearGradient id="poster-whatsapp" x1="1" y1="0" x2="0" y2="1">
        <stop offset="0%" stop-color="var(--channel-whatsapp)" stop-opacity="0.5" />
        <stop offset="100%" stop-color="var(--accent)" stop-opacity="0.1" />
      </linearGradient>
      <linearGradient id="poster-shopee" x1="0" y1="1" x2="1" y2="0">
        <stop offset="0%" stop-color="var(--channel-shopee)" stop-opacity="0.5" />
        <stop offset="100%" stop-color="var(--accent)" stop-opacity="0.1" />
      </linearGradient>
      <linearGradient id="poster-instagram" x1="1" y1="1" x2="0" y2="0">
        <stop offset="0%" stop-color="var(--channel-instagram)" stop-opacity="0.45" />
        <stop offset="100%" stop-color="var(--accent)" stop-opacity="0.1" />
      </linearGradient>
    </defs>

    <g fill="none" stroke-linecap="round">
      <path d="M120 210 C 460 250, 640 380, 800 450" stroke="url(#poster-telegram)" stroke-width="2" />
      <path d="M150 260 C 470 320, 660 400, 800 450" stroke="url(#poster-telegram)" stroke-width="1" opacity="0.6" />

      <path d="M1480 250 C 1140 290, 960 390, 800 450" stroke="url(#poster-whatsapp)" stroke-width="2" />
      <path d="M1450 300 C 1130 350, 940 410, 800 450" stroke="url(#poster-whatsapp)" stroke-width="1" opacity="0.6" />

      <path d="M140 690 C 470 640, 650 520, 800 450" stroke="url(#poster-shopee)" stroke-width="2" />
      <path d="M170 730 C 480 680, 660 540, 800 450" stroke="url(#poster-shopee)" stroke-width="1" opacity="0.6" />

      <path d="M1460 660 C 1140 620, 950 510, 800 450" stroke="url(#poster-instagram)" stroke-width="2" />
      <path d="M1430 710 C 1120 660, 940 530, 800 450" stroke="url(#poster-instagram)" stroke-width="1" opacity="0.6" />
    </g>

    <circle cx="800" cy="450" r="320" fill="url(#poster-core)" />
    <circle cx="800" cy="450" r="4" fill="var(--accent-lit)" />
  </svg>
</template>
