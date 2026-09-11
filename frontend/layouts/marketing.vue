<template>
  <div class="site-shell relative min-h-screen overflow-x-hidden bg-ground">
    <a class="skip-link" href="#main-content">Skip to content</a>
    <LandingConvergenceCanvas />

    <div class="scene-scrim pointer-events-none fixed inset-0 z-[1]" aria-hidden="true" />
    <div class="noise pointer-events-none fixed inset-0 z-[2]" aria-hidden="true" />

    <div class="relative z-10">
      <header class="fixed inset-x-0 top-0 z-30 px-4 pt-4 md:px-8 md:pt-6">
        <div class="nav-shell mx-auto flex max-w-[1376px] items-center justify-between px-4 py-3 md:px-5">
          <NuxtLink to="/" class="group flex items-center gap-2 font-display text-lg font-semibold tracking-[-0.04em]">
            <span class="brand-mark relative size-5 rounded-full border border-accent/60">
              <span class="absolute left-1/2 top-1/2 size-1.5 -translate-x-1/2 -translate-y-1/2 rounded-full bg-accent" />
            </span>
            botly
          </NuxtLink>
          <nav class="flex items-center gap-5 text-[0.8125rem] md:gap-7" aria-label="Main navigation">
            <a href="#channels" class="hidden text-dim transition-colors duration-state hover:text-body sm:inline">Channels</a>
            <a href="#how" class="hidden text-dim transition-colors duration-state hover:text-body sm:inline">How it works</a>
            <NuxtLink to="/login" class="nav-login">Sign in <span aria-hidden="true">↗</span></NuxtLink>
          </nav>
        </div>
      </header>

      <main id="main-content" class="w-full max-w-full overflow-x-hidden"><slot /></main>

      <footer class="mx-auto flex max-w-[1376px] flex-col gap-5 border-t border-line px-6 py-10 text-[0.75rem] text-mute md:flex-row md:items-center md:justify-between md:px-10">
        <p>botly — support infrastructure for Southeast Asian commerce.</p>
        <div class="flex gap-5">
          <a href="mailto:hello@botly.app" class="hover:text-body">hello@botly.app</a>
          <NuxtLink to="/login" class="hover:text-body">Seller sign in</NuxtLink>
        </div>
      </footer>
    </div>
  </div>
</template>
