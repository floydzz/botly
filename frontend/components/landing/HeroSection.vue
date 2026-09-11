<template>
  <section class="hero relative mx-auto flex min-h-[100dvh] max-w-[1440px] items-center px-6 pb-20 pt-32 md:px-10 lg:px-14">
    <div class="hero-copy relative z-10 w-full lg:w-[72%]">
      <p class="hero-kicker mb-7 flex items-center gap-3 text-sm text-dim">
        <span class="h-px w-9 bg-accent" />
        One support brain, across every channel
      </p>

      <h1 class="hero-title max-w-[12ch] text-balance">
        Every message<br />
        <span class="hero-title-accent">finds its way.</span>
      </h1>

      <div class="mt-9 grid max-w-4xl gap-8 lg:grid-cols-[minmax(0,38rem)_auto] lg:items-end">
        <p class="type-lead max-w-[59ch]">
          botly answers customers from your real order data across Telegram, WhatsApp and
          Shopee, then brings the conversations that need judgment back to a person.
        </p>

        <div class="hero-orbit-copy hidden border-l border-line pl-5 lg:block">
          <p class="font-mono text-[0.65rem] uppercase tracking-[0.18em] text-mute">Live signal</p>
          <p class="mt-2 text-sm text-body">Telegram connected</p>
          <p class="mt-1 text-xs text-dim">3 more channels converging</p>
        </div>
      </div>

      <div class="mt-11 flex flex-wrap items-center gap-5">
        <a href="#request-access"><UiButton>Request access</UiButton></a>
        <a href="#how" class="text-link group inline-flex items-center gap-3 text-sm text-body">
          Follow a message
          <span class="grid size-8 place-items-center rounded-full border border-line transition-transform duration-300 group-hover:translate-x-1">↘</span>
        </a>
      </div>
    </div>

    <div class="pointer-events-none absolute bottom-7 left-6 hidden items-center gap-3 font-mono text-[0.62rem] uppercase tracking-[0.2em] text-mute md:flex lg:left-14">
      <span class="h-7 w-px bg-line" />
      Scroll to converge
    </div>
  </section>
</template>
