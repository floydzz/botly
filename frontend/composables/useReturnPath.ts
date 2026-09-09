/** Where the app is sent after a successful sign-in when nothing else is asked for. */
export const DEFAULT_RETURN_PATH = '/app/inbox'

/**
 * The return path the auth guard stashed, if it is safe to obey.
 *
 * `?next=` is attacker-controllable: anyone can send a seller a link to our own
 * login page carrying any value they like. Handing it to navigateTo unchecked
 * is an open redirect -- the victim signs in on the real site, sees it work,
 * and lands on a page someone else chose, which is exactly the shape a
 * convincing credential-phishing flow needs.
 *
 * So only a same-origin absolute path is honoured. Everything else falls back.
 */
export function safeReturnPath(next: unknown): string {
  if (typeof next !== 'string' || next === '') return DEFAULT_RETURN_PATH

  // Must be rooted, and must not be protocol-relative: "//evil.example" is a
  // fully qualified URL to a browser and starts with a slash to a naive check.
  if (!next.startsWith('/') || next.startsWith('//')) return DEFAULT_RETURN_PATH

  // "/\evil.example" is treated as protocol-relative by some browsers, and a
  // backslash has no business in a path we generated.
  if (next.includes('\\')) return DEFAULT_RETURN_PATH

  // A control character can smuggle the checks above past a parser that
  // strips it later: "/\t/evil.example" reads as a path here and as a host
  // once the tab is dropped.
  // eslint-disable-next-line no-control-regex
  if (/[\u0000-\u001f\u007f]/.test(next)) return DEFAULT_RETURN_PATH

  return next
}
