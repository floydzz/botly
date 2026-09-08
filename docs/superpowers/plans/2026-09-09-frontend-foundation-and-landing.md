# botly Frontend Foundation and Landing Page Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stand up the Nuxt application — design tokens, layouts, the API client, the auth store and login — and ship the marketing landing page with its scroll-driven 3D convergence scene.

**Architecture:** Nuxt 3 following the `ai-customer-support/frontend` shape: Tailwind, Pinia, `@nuxt/icon`, plus `three` and `gsap` for this project. Design tokens live in one CSS file as custom properties that the Tailwind config consumes, so a light theme later is a second `:root` block rather than a rewrite. Marketing routes are prerendered; `/app/**` is client-only. Nitro `devProxy` puts the API on the same origin, which is a requirement rather than a convenience: the session cookie is `httponly; samesite=lax`, so a cross-origin frontend would not send it and every authenticated request would 401.

**Tech Stack:** Nuxt 3, Vue 3, TypeScript, Tailwind CSS, Pinia, `@nuxt/icon`, `three`, `gsap` (ScrollTrigger), Vitest.

**Spec:** `docs/superpowers/specs/2026-09-09-frontend-and-inbox-api-design.md` — Part B, §8–§11, plus §13.

---

## Global Constraints

- **No registration.** `app/api/auth.py` has no registration endpoint, deliberately. The landing CTA is **"Request access"**, not "Sign up": a form that collects an email and does not pretend an account was created.
- **The channels section states real status.** Telegram live; WhatsApp and Shopee pending provider approval; RedNote **not offered**. Architecture spec §2 forbids marketing RedNote until a legitimate API exists, and `docs/approvals.md` records that neither WhatsApp nor Shopee verification has been started. `docs/approvals.md` is the source of truth for that section.
- **The guarantee section states architecture spec §8 plainly:** facts come from tools, never from the model; when a tool fails the bot escalates rather than guesses.
- **Fonts are self-hosted.** Inter Tight (display), Inter (body), JetBrains Mono (eyebrows, labels, ids, timestamps). A `fonts.googleapis.com` request on a landing page whose whole point is fluidity is a render-blocking round trip.
- **The page must be fully readable and the CTA fully usable with the canvas absent.** No WebGL → a poster image. `prefers-reduced-motion: reduce` → one static composed frame, no RAF loop, no scrub.
- **The canvas is never the LCP element.** It mounts after hydration.

### Design tokens, copied verbatim from the spec

```
ground        #08090B      surface     #101216      raised   #171A20
border        #23262E      border-lit  #333844
text          #F4F5F7      text-dim    #9BA1AC      text-mute #5C626D
accent        #F0A24B      accent-lit  #FFC978      accent-dim rgba(240,162,75,.14)
ok #3FD07A    warn #F0A24B    danger #E0523F

channel hues (particles and status dots)
telegram #2FA8E0   whatsapp #3FD07A   shopee #F1642E   instagram #C64BB4
```

Type scale is `clamp()`-driven: display 3.5–6rem, h2 2–3rem, body 1rem/1.6, mono-label 0.75rem with 0.14em tracking. Spacing on a 4px base. Radii 6/10/16. Motion: 180ms for state, 420ms for entrance, `cubic-bezier(.16,1,.3,1)` as the house ease.

### Performance budget — non-negotiable

- `renderer.setPixelRatio(Math.min(devicePixelRatio, 2))`
- Particle count by tier: **60k desktop, 25k tablet, 12k mobile**, chosen from screen width and `hardwareConcurrency`.
- RAF paused on `visibilitychange` and by an `IntersectionObserver` on the canvas.
- Target: 60fps desktop, ≥30fps mid-range mobile, LCP unaffected.

---

## File Structure

| File | Responsibility |
|---|---|
| `frontend/package.json`, `frontend/nuxt.config.ts`, `frontend/tsconfig.json` | Project, modules, `routeRules`, `devProxy` |
| `frontend/tailwind.config.ts` | Tailwind reading the CSS custom properties |
| `frontend/assets/css/tokens.css` | The token block above, as custom properties |
| `frontend/assets/css/fonts.css` | `@font-face` for the three self-hosted families |
| `frontend/app.vue` | Root shell |
| `frontend/layouts/marketing.vue` | Fixed canvas behind, content over |
| `frontend/layouts/app.vue` | Authenticated shell (nav + slot) |
| `frontend/composables/useApi.ts` | One `$fetch` wrapper: same-origin `/api`, 401 handling |
| `frontend/stores/auth.ts` | `me`, `login`, `logout`, `fetchMe` |
| `frontend/middleware/auth.global.ts` | Guards `/app/**` |
| `frontend/pages/login.vue` | The only way in |
| `frontend/pages/index.vue` | The marketing page |
| `frontend/components/ui/*` | `Button`, `Field`, `StatusDot`, `Panel` |
| `frontend/composables/useDeviceTier.ts` | Particle-count tier and reduced-motion detection |
| `frontend/composables/useConvergenceScene.ts` | three.js scene, shaders, RAF governor |
| `frontend/composables/useScrollMotion.ts` | The single scrubbed GSAP timeline + section reveals |
| `frontend/components/landing/ConvergenceCanvas.vue` | Client-only canvas mount, poster fallback |
| `frontend/components/landing/*Section.vue` | Hero, Problem, Channels, HowItWorks, Handoff, Guarantee, RequestAccess |
| `frontend/content/channels.ts` | Channel status, sourced from `docs/approvals.md` |
| `frontend/test/*.spec.ts` | Vitest over the tier logic and the channel-status data rule |

---

### Task 1: The Nuxt project

**Files:**
- Create: `frontend/package.json`, `frontend/nuxt.config.ts`, `frontend/tsconfig.json`, `frontend/app.vue`, `frontend/.gitignore`
- Modify: `.gitignore` (repo root — ignore `frontend/node_modules`, `frontend/.nuxt`, `frontend/.output`)

**Interfaces:**
- Produces: a dev server on `:3000` proxying `/api` → `http://localhost:8000`, marketing routes prerendered, `/app/**` with `ssr: false`.

- [ ] **Step 1: Scaffold**

```bash
cd frontend && npm init -y
npm install nuxt vue vue-router
npm install -D typescript @nuxt/icon @pinia/nuxt pinia @nuxtjs/tailwindcss tailwindcss vitest @vue/test-utils happy-dom
npm install three gsap
```

- [ ] **Step 2: Write `frontend/nuxt.config.ts`**

```ts
export default defineNuxtConfig({
  compatibilityDate: '2026-09-09',
  modules: ['@nuxtjs/tailwindcss', '@pinia/nuxt', '@nuxt/icon'],
  css: ['~/assets/css/fonts.css', '~/assets/css/tokens.css'],

  routeRules: {
    // Prerendered for SEO. The marketing page has no per-request state.
    '/': { prerender: true },
    // An authenticated inbox has nothing to gain from server rendering, and
    // getting it would mean forwarding the session cookie through Nitro.
    '/app/**': { ssr: false },
  },

  nitro: {
    devProxy: {
      // Same-origin is a requirement, not a convenience: the session cookie is
      // httponly and samesite=lax, so a cross-origin frontend would not send
      // it and every authenticated request would 401. In production the same
      // path is served by the reverse proxy.
      '/api': { target: 'http://localhost:8000', changeOrigin: false },
    },
  },

  app: {
    head: {
      htmlAttrs: { lang: 'en' },
      meta: [{ name: 'color-scheme', content: 'dark' }],
    },
  },
})
```

- [ ] **Step 3: Write `frontend/app.vue`**

```vue
<template>
  <NuxtLayout>
    <NuxtPage />
  </NuxtLayout>
</template>
```

- [ ] **Step 4: Verify it boots**

```bash
cd frontend && npx nuxi build
```
Expected: a clean build.

- [ ] **Step 5: Commit**

```bash
git add frontend .gitignore
git commit -m "chore: nuxt project with a same-origin api proxy and prerendered marketing routes"
```

---

### Task 2: Tokens, fonts and Tailwind

**Files:**
- Create: `frontend/assets/css/tokens.css`, `frontend/assets/css/fonts.css`, `frontend/tailwind.config.ts`, `frontend/public/fonts/` (the woff2 files)

**Interfaces:**
- Produces: Tailwind utilities `bg-ground`, `bg-surface`, `bg-raised`, `border-line`, `border-lit`, `text-body`, `text-dim`, `text-mute`, `text-accent`, `bg-accent`, `text-ok/warn/danger`, and the channel hues under `channel-*`; plus `font-display`, `font-body`, `font-mono`.

- [ ] **Step 1: Write `frontend/assets/css/tokens.css`**

Custom properties on `:root`, with the Tailwind config reading them. Structured so a light theme later is a second `:root` block rather than a rewrite.

```css
:root {
  --ground: #08090B;
  --surface: #101216;
  --raised: #171A20;
  --border: #23262E;
  --border-lit: #333844;

  --text: #F4F5F7;
  --text-dim: #9BA1AC;
  --text-mute: #5C626D;

  --accent: #F0A24B;
  --accent-lit: #FFC978;
  --accent-dim: rgba(240, 162, 75, 0.14);

  --ok: #3FD07A;
  --warn: #F0A24B;
  --danger: #E0523F;

  /* Channel hues. Used by the particle shader and by status dots, so the two
     cannot drift apart. */
  --channel-telegram: #2FA8E0;
  --channel-whatsapp: #3FD07A;
  --channel-shopee: #F1642E;
  --channel-instagram: #C64BB4;

  --radius-sm: 6px;
  --radius-md: 10px;
  --radius-lg: 16px;

  /* 180ms for state, 420ms for entrance. One house ease. */
  --ease: cubic-bezier(0.16, 1, 0.3, 1);
  --dur-state: 180ms;
  --dur-enter: 420ms;
}

html { background: var(--ground); color-scheme: dark; }
body { background: var(--ground); color: var(--text); }

/* clamp()-driven, so there is no breakpoint at which the display type is
   momentarily the wrong size. */
.type-display { font-size: clamp(3.5rem, 7vw, 6rem); line-height: 0.98; letter-spacing: -0.03em; }
.type-h2 { font-size: clamp(2rem, 4vw, 3rem); line-height: 1.08; letter-spacing: -0.02em; }
.type-body { font-size: 1rem; line-height: 1.6; }
.type-label { font-size: 0.75rem; letter-spacing: 0.14em; text-transform: uppercase; }

@media (prefers-reduced-motion: reduce) {
  *, *::before, *::after {
    animation-duration: 0.01ms !important;
    transition-duration: 0.01ms !important;
  }
}
```

- [ ] **Step 2: Write `frontend/assets/css/fonts.css`** with `@font-face` blocks pointing at `/fonts/*.woff2`, each with `font-display: swap` and a real fallback stack in the Tailwind config.

- [ ] **Step 3: Write `frontend/tailwind.config.ts`** mapping the custom properties into the theme.

```ts
import type { Config } from 'tailwindcss'

export default <Partial<Config>>{
  content: ['./components/**/*.vue', './layouts/**/*.vue', './pages/**/*.vue', './app.vue'],
  theme: {
    extend: {
      colors: {
        ground: 'var(--ground)',
        surface: 'var(--surface)',
        raised: 'var(--raised)',
        line: 'var(--border)',
        lit: 'var(--border-lit)',
        body: 'var(--text)',
        dim: 'var(--text-dim)',
        mute: 'var(--text-mute)',
        accent: { DEFAULT: 'var(--accent)', lit: 'var(--accent-lit)', dim: 'var(--accent-dim)' },
        ok: 'var(--ok)',
        warn: 'var(--warn)',
        danger: 'var(--danger)',
        channel: {
          telegram: 'var(--channel-telegram)',
          whatsapp: 'var(--channel-whatsapp)',
          shopee: 'var(--channel-shopee)',
          instagram: 'var(--channel-instagram)',
        },
      },
      fontFamily: {
        display: ['Inter Tight', 'Inter', 'system-ui', 'sans-serif'],
        body: ['Inter', 'system-ui', 'sans-serif'],
        mono: ['JetBrains Mono', 'ui-monospace', 'SFMono-Regular', 'monospace'],
      },
      borderRadius: { sm: 'var(--radius-sm)', md: 'var(--radius-md)', lg: 'var(--radius-lg)' },
      transitionTimingFunction: { house: 'var(--ease)' },
    },
  },
}
```

- [ ] **Step 4: Build and commit**

```bash
cd frontend && npx nuxi build
git add frontend/assets frontend/tailwind.config.ts frontend/public/fonts
git commit -m "feat: dark design tokens, self-hosted type and the tailwind bridge"
```

---

### Task 3: The API client, the auth store and the guard

**Files:**
- Create: `frontend/composables/useApi.ts`, `frontend/stores/auth.ts`, `frontend/middleware/auth.global.ts`, `frontend/layouts/app.vue`
- Test: `frontend/test/auth-store.spec.ts`

**Interfaces:**
- Produces:
  - `useApi()` → `{ get, post, patch, del }`, each `(<T>path: string, options?) => Promise<T>`, base `/api`, `credentials: 'include'`, throwing `ApiError { status, detail }`.
  - `useAuthStore()` → `{ user: User | null, ready: boolean, fetchMe(), login(email, password), logout() }`.

- [ ] **Step 1: Write the failing test** — `frontend/test/auth-store.spec.ts`

```ts
import { describe, expect, it, beforeEach, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { useAuthStore } from '../stores/auth'

describe('the auth store', () => {
  beforeEach(() => setActivePinia(createPinia()))

  it('holds the user a successful login returns', async () => {
    const store = useAuthStore()
    store.$api = { post: vi.fn().mockResolvedValue({ id: 1, name: 'Ani', email: 'a@b.c', merchant_id: 2 }) }

    await store.login('a@b.c', 'pw')

    expect(store.user?.name).toBe('Ani')
  })

  it('clears the user when /auth/me answers 401', async () => {
    const store = useAuthStore()
    store.user = { id: 1, name: 'Ani', email: 'a@b.c', merchant_id: 2 }
    store.$api = { get: vi.fn().mockRejectedValue({ status: 401 }) }

    await store.fetchMe()

    expect(store.user).toBeNull()
    expect(store.ready).toBe(true)
  })

  it('asks the server only once for a session it already has', async () => {
    const store = useAuthStore()
    const get = vi.fn().mockResolvedValue({ id: 1, name: 'Ani', email: 'a@b.c', merchant_id: 2 })
    store.$api = { get }

    await store.fetchMe()
    await store.fetchMe()

    expect(get).toHaveBeenCalledTimes(1)
  })
})
```

- [ ] **Step 2: Run and watch fail**

```bash
cd frontend && npx vitest run test/auth-store.spec.ts
```
Expected: FAIL — the module does not exist.

- [ ] **Step 3: Write `frontend/composables/useApi.ts`**

```ts
export class ApiError extends Error {
  constructor(readonly status: number, readonly detail: string) {
    super(detail)
  }
}

/**
 * One client for the whole app.
 *
 * Always same-origin under /api, and always with credentials: the session is a
 * httponly, samesite=lax cookie, so a cross-origin call would simply not carry
 * it and every request would 401.
 */
export function useApi() {
  async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
    const response = await fetch(`/api${path}`, {
      credentials: 'include',
      headers: { 'content-type': 'application/json', ...(options.headers ?? {}) },
      ...options,
    })
    if (!response.ok) {
      const detail = await response
        .json()
        .then((b) => b.detail ?? response.statusText)
        .catch(() => response.statusText)
      throw new ApiError(response.status, String(detail))
    }
    return response.status === 204 ? (undefined as T) : ((await response.json()) as T)
  }

  return {
    get: <T>(path: string) => request<T>(path),
    post: <T>(path: string, body?: unknown) =>
      request<T>(path, { method: 'POST', body: body === undefined ? undefined : JSON.stringify(body) }),
    patch: <T>(path: string, body: unknown) =>
      request<T>(path, { method: 'PATCH', body: JSON.stringify(body) }),
    del: <T>(path: string) => request<T>(path, { method: 'DELETE' }),
  }
}
```

- [ ] **Step 4: Write `frontend/stores/auth.ts`** with an injectable `$api` so the store is testable without a server, and `fetchMe` guarded by `ready` so the global middleware calls `/auth/me` once rather than on every navigation.

- [ ] **Step 5: Write `frontend/middleware/auth.global.ts`**

```ts
export default defineNuxtRouteMiddleware(async (to) => {
  if (!to.path.startsWith('/app')) return

  const auth = useAuthStore()
  if (!auth.ready) await auth.fetchMe()

  if (!auth.user) {
    // Carry the return path: an agent who followed a link to a conversation
    // should land back on that conversation, not on a generic inbox.
    return navigateTo({ path: '/login', query: { next: to.fullPath } })
  }
})
```

- [ ] **Step 6: Run the tests and commit**

```bash
cd frontend && npx vitest run
git add frontend/composables/useApi.ts frontend/stores/auth.ts frontend/middleware frontend/layouts/app.vue frontend/test
git commit -m "feat: same-origin api client, auth store and the /app guard"
```

---

### Task 4: UI primitives and the login page

**Files:**
- Create: `frontend/components/ui/Button.vue`, `Field.vue`, `StatusDot.vue`, `Panel.vue`, `frontend/pages/login.vue`

**Interfaces:**
- `Button` props: `variant: 'primary' | 'ghost' | 'danger'`, `size: 'sm' | 'md'`, `loading?: boolean`, `disabled?: boolean`.
- `Field` props: `label: string`, `modelValue: string`, `type?: string`, `error?: string | null`, `hint?: string`.
- `StatusDot` props: `tone: 'ok' | 'warn' | 'danger' | 'mute'`, `label?: string`.
- `Panel` props: `title?: string`, `tight?: boolean`.

- [ ] **Step 1: Write the four primitives.** Each is small, uses only the token utilities from Task 2, and has a visible `:focus-visible` ring — an inbox is worked with a keyboard.

- [ ] **Step 2: Write `frontend/pages/login.vue`**

Sign-in only. There is no registration endpoint, so the page carries no "create an account" affordance — the marketing CTA is Request access, and offering a sign-up link here that goes nowhere is worse than offering nothing. On success, redirect to `route.query.next` when present, otherwise `/app/inbox`.

- [ ] **Step 3: Verify by hand** with the backend running

```bash
.venv/bin/python -m uvicorn app.main:app --port 8000   # terminal 1
cd frontend && npx nuxi dev                            # terminal 2
```
Sign in with a seeded user; confirm the cookie is set and `/app/inbox` no longer redirects.

- [ ] **Step 4: Commit**

```bash
git add frontend/components/ui frontend/pages/login.vue
git commit -m "feat: ui primitives and the login page"
```

---

### Task 5: Device tier and reduced motion

The budget is the reason this is its own unit: the tier decision must be testable without a GPU.

**Files:**
- Create: `frontend/composables/useDeviceTier.ts`
- Test: `frontend/test/device-tier.spec.ts`

**Interfaces:**
- Produces: `particleCountFor(width: number, cores: number): number` and `useDeviceTier(): { particles: number, reducedMotion: boolean, webgl: boolean }`.

- [ ] **Step 1: Write the failing test**

```ts
import { describe, expect, it } from 'vitest'
import { particleCountFor } from '../composables/useDeviceTier'

describe('the particle budget', () => {
  it('gives a desktop the full scene', () => {
    expect(particleCountFor(1920, 8)).toBe(60_000)
  })

  it('halves it on a tablet', () => {
    expect(particleCountFor(900, 6)).toBe(25_000)
  })

  it('drops to the mobile tier on a narrow screen', () => {
    expect(particleCountFor(390, 6)).toBe(12_000)
  })

  it('drops a wide screen with few cores to the tablet tier', () => {
    // Much of this audience is on mid-range Android, where a large viewport
    // says nothing about what the GPU will do with 60k particles.
    expect(particleCountFor(1600, 2)).toBe(25_000)
  })
})
```

- [ ] **Step 2: Run it and watch it fail**, then implement:

```ts
export const DESKTOP = 60_000
export const TABLET = 25_000
export const MOBILE = 12_000

/**
 * Screen width *and* core count, because much of this audience is on
 * mid-range Android, where a large viewport says nothing about what the GPU
 * will do with 60k particles.
 */
export function particleCountFor(width: number, cores: number): number {
  if (width < 640) return MOBILE
  if (width < 1280 || cores <= 4) return TABLET
  return DESKTOP
}
```

- [ ] **Step 3: Add `useDeviceTier`** reading `window.innerWidth`, `navigator.hardwareConcurrency ?? 4`, `matchMedia('(prefers-reduced-motion: reduce)')`, and a WebGL probe that creates and immediately discards a context.

- [ ] **Step 4: Run and commit**

```bash
cd frontend && npx vitest run
git add frontend/composables/useDeviceTier.ts frontend/test/device-tier.spec.ts
git commit -m "feat: device-tier particle budget and reduced-motion detection"
```

---

### Task 6: The convergence scene

One `THREE.Points` of N particles, one `ShaderMaterial`, one draw call. Per-particle attributes `aChannel` (0–3), `aPhase`, `aSpeed`, `aSpread`. The vertex shader evaluates a cubic Bézier from the particle's channel node to the core at `t = fract(uTime * aSpeed + aPhase)`, with control points bowed outward so paths arc rather than converge as straight spokes; curl-noise displacement scaled by `aSpread * (1.0 - t)` decays to zero at arrival. Positions are never computed on the CPU. The fragment shader draws a soft radial falloff and lerps the channel hue toward `--accent` as `t → 1`, so colour convergence and spatial convergence are the same gesture.

No `UnrealBloomPass`: full postprocessing costs extra render targets for an effect a well-authored additive sprite delivers at a fraction of the cost, and it is the first thing that collapses on a mid-range Android. The core is a separate additive glow quad driven by arrival density.

**Files:**
- Create: `frontend/composables/useConvergenceScene.ts`, `frontend/components/landing/ConvergenceCanvas.vue`, `frontend/public/poster-convergence.webp`

**Interfaces:**
- Produces: `useConvergenceScene(canvas: HTMLCanvasElement, options: { particles: number; reducedMotion: boolean })` → `{ setProgress(value: number): void, renderOnce(): void, start(): void, stop(): void, dispose(): void }`.

- [ ] **Step 1: Write the scene composable.** Structure, in order:
  1. `WebGLRenderer({ canvas, antialias: false, alpha: true })`, `setPixelRatio(Math.min(devicePixelRatio, 2))`.
  2. Four channel node positions on a wide arc; `BufferGeometry` with the four attributes; `ShaderMaterial` with `uniforms: { uTime, uProgress, uCameraZ, uAccent, uChannelColors }`, `blending: AdditiveBlending`, `depthWrite: false`.
  3. The core glow: one additive quad whose opacity uniform is a function of `uProgress`.
  4. RAF governor: a single loop, started only when both the `IntersectionObserver` says the canvas is on screen and `document.visibilityState === 'visible'`.
  5. `reducedMotion: true` → `setProgress(0.5)`, `renderOnce()`, and **never** start the loop.
  6. `dispose()` disposing geometry, material and renderer, and disconnecting the observer.

- [ ] **Step 2: Write `ConvergenceCanvas.vue`.** `<ClientOnly>`, `position: fixed; inset: 0; z-index: 0; pointer-events: none`. When `useDeviceTier().webgl` is false, render the poster `<img>` instead — the page must be fully readable and the CTA fully usable with the canvas absent. Also listen for `webglcontextlost` and swap to the poster.

- [ ] **Step 3: Verify the budget by hand.** With the dev server running, check in DevTools:
  - 60fps on desktop at the top of the page and mid-scroll;
  - the RAF loop stops when the tab is hidden and when the canvas is scrolled past;
  - `prefers-reduced-motion: reduce` (DevTools rendering panel) draws one frame and no more;
  - WebGL disabled shows the poster and the CTA still works.

- [ ] **Step 4: Commit**

```bash
git add frontend/composables/useConvergenceScene.ts frontend/components/landing/ConvergenceCanvas.vue frontend/public/poster-convergence.webp
git commit -m "feat: the convergence scene, one draw call with a tiered particle budget"
```

---

### Task 7: Scroll motion

**Files:**
- Create: `frontend/composables/useScrollMotion.ts`, `frontend/layouts/marketing.vue`

**Interfaces:**
- Produces: `useScrollMotion(scene: ReturnType<typeof useConvergenceScene>, options: { reducedMotion: boolean })`.

**One** scrubbed timeline over the whole page, driving `uProgress` and camera z from 9.0 to 3.2 — not one ScrollTrigger per section. Several competing ScrollTriggers on one camera is how scroll animation becomes jittery.

| progress | beat |
|---|---|
| 0.00 | hero — nodes wide, slow drift |
| 0.20 | channels named, labels resolve |
| 0.45 | convergence tightens, flow accelerates |
| 0.70 | core blooms, inbox UI fragment fades in over it |
| 1.00 | scene recedes, CTA holds the frame |

- [ ] **Step 1: Implement the single timeline**, plus a separate, cheap set of one-shot `ScrollTrigger` reveals for section entrances (these are independent of the camera and may be per-section).

- [ ] **Step 2: Honour reduced motion** — when set, register no scrub and no camera tween; section reveals become instant `opacity: 1`. Sections still fade in on scroll but nothing moves continuously.

- [ ] **Step 3: Write `frontend/layouts/marketing.vue`** — `<ConvergenceCanvas />` fixed behind, `<slot />` in a `relative z-10` column, so sections scroll over one continuous scene rather than a hero widget that dies after the fold.

- [ ] **Step 4: Commit**

```bash
git add frontend/composables/useScrollMotion.ts frontend/layouts/marketing.vue
git commit -m "feat: one scrubbed timeline driving the scene across the whole page"
```

---

### Task 8: Channel status as data

The channels section is the single most likely place for the product to make a claim it cannot honour, so its content is data with a test, not markup.

**Files:**
- Create: `frontend/content/channels.ts`
- Test: `frontend/test/channels.spec.ts`

- [ ] **Step 1: Write the failing test**

```ts
import { describe, expect, it } from 'vitest'
import { CHANNELS } from '../content/channels'

describe('the channels the landing page claims', () => {
  it('offers only what actually works today', () => {
    const live = CHANNELS.filter((c) => c.status === 'live').map((c) => c.id)
    expect(live).toEqual(['telegram'])
  })

  it('marks the approval-gated channels as pending rather than available', () => {
    // docs/approvals.md: as of 2026-09-05 neither WhatsApp business
    // verification nor Shopee partner registration has been started.
    const pending = CHANNELS.filter((c) => c.status === 'pending').map((c) => c.id)
    expect(pending.sort()).toEqual(['shopee', 'whatsapp'])
  })

  it('does not mention rednote at all', () => {
    // Architecture spec §2: RedNote must not be marketed until a legitimate
    // API exists.
    expect(JSON.stringify(CHANNELS).toLowerCase()).not.toContain('rednote')
  })

  it('gives every channel an honest one-line status', () => {
    for (const channel of CHANNELS) expect(channel.note.length).toBeGreaterThan(0)
  })
})
```

- [ ] **Step 2: Run and watch fail**, then write `frontend/content/channels.ts`

```ts
export type ChannelStatus = 'live' | 'pending'

export interface Channel {
  id: 'telegram' | 'whatsapp' | 'shopee'
  name: string
  status: ChannelStatus
  /** What a seller can actually expect today. Sourced from docs/approvals.md. */
  note: string
  hue: string
}

/**
 * A grid of four logos implying four working integrations is a claim the
 * product cannot honour, made to exactly the buyer who would notice. So this
 * list carries status, and docs/approvals.md is its source of truth.
 */
export const CHANNELS: Channel[] = [
  {
    id: 'telegram',
    name: 'Telegram',
    status: 'live',
    note: 'Live today. A bot token and a webhook — no approval queue.',
    hue: 'var(--channel-telegram)',
  },
  {
    id: 'whatsapp',
    name: 'WhatsApp Business',
    status: 'pending',
    note: 'Built, waiting on Meta business verification. Not yet available to sellers.',
    hue: 'var(--channel-whatsapp)',
  },
  {
    id: 'shopee',
    name: 'Shopee',
    status: 'pending',
    note: 'Waiting on Shopee Open Platform partner registration. Not yet available to sellers.',
    hue: 'var(--channel-shopee)',
  },
]
```

- [ ] **Step 3: Run and commit**

```bash
cd frontend && npx vitest run
git add frontend/content/channels.ts frontend/test/channels.spec.ts
git commit -m "feat: channel status as tested data, so the page cannot overclaim"
```

---

### Task 9: The landing page

Sections, in order: hero; the problem; channels; how it works; the handoff; the facts-from-tools guarantee; request access.

**Files:**
- Create: `frontend/components/landing/HeroSection.vue`, `ProblemSection.vue`, `ChannelsSection.vue`, `HowItWorksSection.vue`, `HandoffSection.vue`, `GuaranteeSection.vue`, `RequestAccessSection.vue`
- Create: `frontend/pages/index.vue`

- [ ] **Step 1: Write the sections.** Content rules that are requirements, not copy suggestions:
  - **Channels** renders `CHANNELS` with a `StatusDot` per row and the `note` visible. Nothing implies a channel works before it does.
  - **How it works** names the four real stages: ingress → brain → dispatcher → inbox.
  - **Guarantee** states architecture spec §8 plainly: facts come from tools, never from the model; when a tool fails the bot escalates rather than guesses. For a seller weighing a bot against refund disputes this is the strongest thing the page has to say, so it gets a section, not a bullet.
  - **Handoff** shows the escalation reason travelling to the agent — the product's actual differentiator.
  - **Request access** is a form that collects an email and says plainly that access is granted manually. It must not read as a sign-up.

- [ ] **Step 2: Write `frontend/pages/index.vue`** with `definePageMeta({ layout: 'marketing' })`, the sections in order, and `useScrollMotion` wired in `onMounted`.

- [ ] **Step 3: Check the page without the scene** — disable WebGL and confirm every section is readable and the CTA works.

- [ ] **Step 4: Commit**

```bash
git add frontend/components/landing frontend/pages/index.vue
git commit -m "feat: the landing page, with honest channel status and the tools guarantee"
```

---

### Task 10: Phase 1 verification

- [ ] **Step 1: Build and test**

```bash
cd frontend && npx vitest run && npx nuxi build
```

- [ ] **Step 2: Walk the manual checklist** — the 3D scene is not unit-tested, because its correctness is visual and a test asserting that a shader compiled tells you nothing about whether it looks right.

| Check | Pass |
|---|---|
| 60fps desktop, top of page and mid-scroll | |
| ≥30fps on a real mid-range Android handset, not a throttled desktop | |
| Tablet tier renders 25k, mobile tier 12k | |
| RAF stops on tab hide and when the canvas leaves the viewport | |
| `prefers-reduced-motion` draws one frame, no scrub | |
| WebGL disabled shows the poster; CTA still works | |
| LCP is a text element, not the canvas | |

- [ ] **Step 3: Commit the checklist result** in the plan file and move to Phase 3 once Phase 2 has landed.
