/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  darkMode: 'class',
  theme: {
    extend: {
      colors: {
        bg: 'var(--color-bg)',
        surface: 'var(--color-surface)',
        'surface-2': 'var(--color-surface-2)',
        'surface-subtle': 'var(--color-surface-subtle)',
        border: 'var(--color-border)',
        'border-strong': 'var(--color-border-strong)',
        text: 'var(--color-text)',
        muted: 'var(--color-muted)',
        primary: 'var(--color-primary)',
        'primary-hover': 'var(--color-primary-hover)',
        'primary-subtle': 'var(--color-primary-subtle)',
        ok: 'var(--color-ok)',
        warn: 'var(--color-warn)',
        critical: 'var(--color-critical)',
      },
      fontFamily: {
        display: ['"Sofia Sans Condensed"', '"Barlow Condensed"', 'sans-serif'],
        sans: ['Inter', 'system-ui', '-apple-system', 'sans-serif'],
        mono: ['"JetBrains Mono"', 'ui-monospace', 'monospace'],
      },
      borderRadius: {
        card: '28px',
        tile: '16px',
        pill: '9999px',
      },
      boxShadow: {
        'card': '0 8px 32px -4px rgba(0, 0, 0, 0.35)',
        'card-light': '0 8px 32px -4px rgba(94, 83, 128, 0.08)',
        'glow-violet': '0 0 40px rgba(139, 92, 246, 0.40)',
        'glow-culprit': '0 0 30px rgba(255, 79, 129, 0.45)',
      },
      animation: {
        'pulse-subtle': 'pulseSubtle 2.5s cubic-bezier(0.4, 0, 0.6, 1) infinite',
        'ring-culprit': 'culpritRing 2s cubic-bezier(0, 0, 0.2, 1) infinite',
      },
      keyframes: {
        pulseSubtle: {
          '0%, 100%': { opacity: '1' },
          '50%': { opacity: '0.7' },
        },
        culpritRing: {
          '0%': { transform: 'scale(0.97)', boxShadow: '0 0 0 0 rgba(255, 79, 129, 0.7)' },
          '70%': { transform: 'scale(1.03)', boxShadow: '0 0 0 10px rgba(255, 79, 129, 0)' },
          '100%': { transform: 'scale(0.97)', boxShadow: '0 0 0 0 rgba(255, 79, 129, 0)' },
        }
      }
    },
  },
  plugins: [],
}
