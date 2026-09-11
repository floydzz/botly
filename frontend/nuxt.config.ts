export default defineNuxtConfig({
  compatibilityDate: '2026-09-09',
  devtools: { enabled: false },

  modules: ['@nuxtjs/tailwindcss', '@pinia/nuxt', '@nuxt/icon'],
  css: ['~/assets/css/fonts.css', '~/assets/css/tokens.css'],

  routeRules: {
    // Prerendered for SEO. The marketing page has no per-request state, and
    // its whole job is to be fast on a mid-range handset.
    '/': { prerender: true },
    // An authenticated inbox has nothing to gain from server rendering, and
    // getting it would mean forwarding the session cookie through Nitro to a
    // process that has no business holding one.
    '/app/**': { ssr: false },
  },

  nitro: {
    devProxy: {
      // Same-origin is a requirement, not a convenience. The session cookie is
      // httponly and samesite=lax (app/api/auth.py), so a cross-origin
      // frontend would simply not send it and every authenticated request
      // would 401. In production the same path is served by the reverse proxy.
      '/api': { target: 'http://localhost:8004', changeOrigin: false },
    },
  },

  app: {
    head: {
      htmlAttrs: { lang: 'en' },
      meta: [
        { charset: 'utf-8' },
        { name: 'viewport', content: 'width=device-width, initial-scale=1' },
        // The scene reads against dark and only against dark. A light ground
        // would need an entirely different treatment for a fraction of the
        // impact, so the page commits rather than half-supporting both.
        { name: 'color-scheme', content: 'dark' },
        { name: 'theme-color', content: '#08090B' },
      ],
    },
  },

  typescript: { strict: true, shim: false },
})
