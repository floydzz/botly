import type { Config } from 'tailwindcss'

/**
 * Tailwind reads the custom properties in assets/css/tokens.css rather than
 * holding its own copy of the palette. One definition, so a theme change is a
 * change to one file and not a search for every hex literal in the app.
 */
export default <Partial<Config>>{
  content: [
    './components/**/*.{vue,ts}',
    './layouts/**/*.vue',
    './pages/**/*.vue',
    './composables/**/*.ts',
    './content/**/*.ts',
    './app.vue',
  ],
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
        accent: {
          DEFAULT: 'var(--accent)',
          lit: 'var(--accent-lit)',
          dim: 'var(--accent-dim)',
        },
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
        display: ['Satoshi', 'Inter Tight', 'Inter', 'system-ui', 'sans-serif'],
        body: ['Satoshi', 'Inter', 'system-ui', '-apple-system', 'sans-serif'],
        mono: ['JetBrains Mono', 'ui-monospace', 'SFMono-Regular', 'monospace'],
      },
      borderRadius: {
        sm: 'var(--radius-sm)',
        md: 'var(--radius-md)',
        lg: 'var(--radius-lg)',
      },
      transitionTimingFunction: { house: 'var(--ease)' },
      transitionDuration: { state: '180ms', enter: '420ms' },
      // 4px base, named so a component says "space-3" and not "12px".
      spacing: {
        1: '4px',
        2: '8px',
        3: '12px',
        4: '16px',
        5: '20px',
        6: '24px',
        8: '32px',
        10: '40px',
        12: '48px',
        16: '64px',
        20: '80px',
        24: '96px',
        32: '128px',
      },
      maxWidth: { measure: '68ch', shell: '1200px' },
    },
  },
}
