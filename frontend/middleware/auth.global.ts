/**
 * The guard on /app/**.
 *
 * Asks /auth/me once, hydrates the store, and redirects on a miss. The return
 * path travels in the query so an agent who followed a link to a specific
 * conversation lands back on that conversation, not on a generic inbox.
 */
export default defineNuxtRouteMiddleware(async (to) => {
  if (!to.path.startsWith('/app')) return

  const auth = useAuthStore()
  if (!auth.ready) await auth.fetchMe()

  if (!auth.user) {
    return navigateTo({ path: '/login', query: { next: to.fullPath } })
  }
})
