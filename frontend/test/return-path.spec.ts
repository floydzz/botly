import { describe, expect, it } from 'vitest'

import { DEFAULT_RETURN_PATH, safeReturnPath } from '../composables/useReturnPath'

describe('the post-login return path', () => {
  it('lands on the dashboard when no destination was requested', () => {
    expect(DEFAULT_RETURN_PATH).toBe('/app/dashboard')
  })

  it('honours a same-origin path the guard stashed', () => {
    expect(safeReturnPath('/app/inbox/41')).toBe('/app/inbox/41')
  })

  it('keeps the query string on that path', () => {
    expect(safeReturnPath('/app/inbox?state=pending_human')).toBe(
      '/app/inbox?state=pending_human',
    )
  })

  it('falls back when nothing was asked for', () => {
    expect(safeReturnPath(undefined)).toBe(DEFAULT_RETURN_PATH)
    expect(safeReturnPath('')).toBe(DEFAULT_RETURN_PATH)
    expect(safeReturnPath(['/a', '/b'])).toBe(DEFAULT_RETURN_PATH)
  })

  it('refuses an absolute url', () => {
    // Otherwise /login?next=https://evil.example is an open redirect: the
    // seller signs in on the real site, it works, and they land somewhere
    // someone else chose.
    expect(safeReturnPath('https://evil.example/login')).toBe(DEFAULT_RETURN_PATH)
    expect(safeReturnPath('javascript:alert(1)')).toBe(DEFAULT_RETURN_PATH)
  })

  it('refuses a protocol-relative url that looks like a path', () => {
    expect(safeReturnPath('//evil.example')).toBe(DEFAULT_RETURN_PATH)
  })

  it('refuses a backslash, which some browsers read as a slash', () => {
    expect(safeReturnPath('/\\evil.example')).toBe(DEFAULT_RETURN_PATH)
  })

  it('refuses a control character used to smuggle a host past the check', () => {
    expect(safeReturnPath('/\t/evil.example')).toBe(DEFAULT_RETURN_PATH)
    expect(safeReturnPath('/\n//evil.example')).toBe(DEFAULT_RETURN_PATH)
  })
})
