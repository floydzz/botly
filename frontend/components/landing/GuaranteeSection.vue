<template>
  <LandingSection eyebrow="The non-negotiable">
    <h2 class="type-h2 max-w-[18ch]">The model writes the sentence. Your tools supply every fact.</h2>

    <div class="proof-grid mt-16 grid grid-flow-dense grid-cols-1 gap-2 md:grid-cols-12">
      <article class="proof-card min-h-[25rem] overflow-hidden rounded-[1.5rem] border border-line bg-surface/75 p-7 backdrop-blur-xl md:col-span-7 md:p-10">
        <div class="flex h-full flex-col justify-between">
          <div class="tool-flow relative h-40">
            <span class="tool-node left-0 top-4">Order record</span>
            <span class="tool-node right-0 top-20">Shipping scan</span>
            <span class="tool-node bottom-0 left-[35%]">Payment state</span>
            <span class="absolute left-1/2 top-1/2 grid size-20 -translate-x-1/2 -translate-y-1/2 place-items-center rounded-full border border-accent/40 bg-accent-dim font-display text-sm text-accent">answer</span>
          </div>
          <div>
            <h3 class="font-display text-3xl font-medium tracking-[-0.04em]">Read at the moment of reply.</h3>
            <p class="mt-4 max-w-[48ch] text-sm leading-relaxed text-dim">Location, price and shipping state come directly from your connected systems—not model memory.</p>
          </div>
        </div>
      </article>

      <article class="proof-card min-h-[25rem] rounded-[1.5rem] border border-line bg-[#151316]/80 p-7 backdrop-blur-xl md:col-span-5 md:p-10">
        <div class="flex h-full flex-col justify-between">
          <p class="font-mono text-xs uppercase tracking-[0.16em] text-danger">If the tool fails</p>
          <div>
            <div class="mb-8 font-display text-[clamp(4rem,8vw,7rem)] leading-none tracking-[-0.06em] text-danger">No guess.</div>
            <p class="text-sm leading-relaxed text-dim">The conversation moves to a person with the failure recorded in the thread.</p>
          </div>
        </div>
      </article>

      <article class="proof-card min-h-[18rem] rounded-[1.5rem] border border-line bg-surface/75 p-7 backdrop-blur-xl md:col-span-5 md:p-10">
        <p class="font-mono text-xs uppercase tracking-[0.16em] text-mute">Commerce access</p>
        <div class="mt-16 flex items-end justify-between gap-5">
          <h3 class="font-display text-4xl font-medium tracking-[-0.045em]">Read only<br />by design.</h3>
          <span class="lock-glyph grid size-14 place-items-center rounded-full border border-line text-accent">⌁</span>
        </div>
      </article>

      <article class="proof-card min-h-[18rem] rounded-[1.5rem] border border-line bg-accent p-7 text-[#15100a] md:col-span-7 md:p-10">
        <div class="flex h-full flex-col justify-between gap-12">
          <p class="font-mono text-xs uppercase tracking-[0.16em] text-[#15100a]/60">The operating rule</p>
          <p class="max-w-[24ch] font-display text-[clamp(2rem,3.5vw,3.8rem)] font-medium leading-[1.02] tracking-[-0.045em]">Confidence never outranks evidence.</p>
        </div>
      </article>
    </div>
  </LandingSection>
</template>
