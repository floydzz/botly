<template>
  <div class="relative min-h-screen bg-ground">
    <!--
      Fixed behind the whole page, not parked in the hero. That persistence is
      what makes the page read as one continuous motion rather than a widget
      that dies after the fold.
    -->
    <LandingConvergenceCanvas />

    <!--
      A scrim between the scene and the words. Additive particles brighten
      whatever is behind them, and a paragraph read against a moving bright
      field is a paragraph nobody finishes. Weighted to the left, where the
      body column sits.
    -->
    <div
      class="pointer-events-none fixed inset-0 z-[1]"
      style="background: linear-gradient(100deg, rgba(8,9,11,0.94) 0%, rgba(8,9,11,0.78) 34%, rgba(8,9,11,0.28) 62%, rgba(8,9,11,0.12) 100%)"
      aria-hidden="true"
    />

    <div class="relative z-10">
      <header class="mx-auto flex max-w-shell items-center justify-between px-6 py-6">
        <NuxtLink to="/" class="font-display text-lg font-semibold tracking-tight">botly</NuxtLink>
        <nav class="flex items-center gap-6 text-sm">
          <a href="#channels" class="text-dim transition-colors duration-state hover:text-body">Channels</a>
          <a href="#how" class="hidden text-dim transition-colors duration-state hover:text-body sm:inline">How it works</a>
          <NuxtLink to="/login" class="text-dim transition-colors duration-state hover:text-body">Sign in</NuxtLink>
        </nav>
      </header>

      <slot />

      <footer class="mx-auto mt-24 max-w-shell border-t border-line px-6 py-10 text-[0.8125rem] text-mute">
        <p>botly — multi-channel support for Southeast Asian commerce sellers.</p>
      </footer>
    </div>
  </div>
</template>
