<template>
  <LandingSection eyebrow="The guarantee">
    <h2 class="type-h2 max-w-[20ch]">Facts come from tools. Never from the model.</h2>

    <div class="mt-8 grid gap-10 lg:grid-cols-[1.2fr_1fr]">
      <div>
        <p class="type-lead max-w-measure">
          Every factual claim the bot makes about an order — where it is, what it cost,
          whether it shipped — is read from your system at the moment it answers. The
          model chooses the words. It does not choose the facts.
        </p>

        <p class="type-lead mt-6 max-w-measure">
          When a tool fails, the bot does not fill the gap. It says it cannot check, and
          the conversation goes to you.
        </p>
      </div>

      <div class="rounded-lg border border-danger/30 bg-danger/5 p-6">
        <p class="type-label mb-3 text-danger">Why this is the rule</p>
        <p class="max-w-measure text-sm text-dim">
          A confident wrong answer about a refund is the single most expensive thing a
          support bot can say. It is also the thing every general-purpose model does best.
          botly is read-only against your commerce systems by design: it can tell a
          customer what happened, and it cannot take an action that costs you money.
        </p>
      </div>
    </div>
  </LandingSection>
</template>
