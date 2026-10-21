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
        'surface-elevated': 'var(--color-surface-elevated)',
        'surface-subtle': 'var(--color-surface-subtle)',
        border: 'var(--color-border)',
        'border-strong': 'var(--color-border-strong)',
        text: 'var(--color-text)',
        muted: 'var(--color-muted)',
        ok: 'var(--color-ok)',
        warn: 'var(--color-warn)',
        critical: 'var(--color-critical)',
        accent: 'var(--color-accent)',
        'accent-subtle': 'var(--color-accent-subtle)',
      },
      fontFamily: {
        sans: ['Inter', 'system-ui', '-apple-system', 'sans-serif'],
        mono: ['JetBrains Mono', 'ui-monospace', 'monospace'],
      },
      borderRadius: {
        card: '16px',
        'card-lg': '20px',
        'card-xl': '24px',
      },
      boxShadow: {
        'glass': '0 8px 32px 0 rgba(0, 0, 0, 0.36), inset 0 1px 0 0 rgba(255, 255, 255, 0.08)',
        'glow-accent': '0 0 25px -5px rgba(99, 102, 241, 0.35)',
        'glow-ok': '0 0 25px -5px rgba(20, 184, 166, 0.35)',
        'glow-warn': '0 0 25px -5px rgba(245, 158, 11, 0.35)',
        'glow-crit': '0 0 25px -5px rgba(244, 63, 94, 0.35)',
      },
      animation: {
        'pulse-subtle': 'pulseSubtle 2.5s cubic-bezier(0.4, 0, 0.6, 1) infinite',
        'ring-culprit': 'culpritRing 1.8s cubic-bezier(0, 0, 0.2, 1) infinite',
      },
      keyframes: {
        pulseSubtle: {
          '0%, 100%': { opacity: '1' },
          '50%': { opacity: '0.65' },
        },
        culpritRing: {
          '0%': { transform: 'scale(0.96)', boxShadow: '0 0 0 0 rgba(244, 63, 94, 0.7)' },
          '70%': { transform: 'scale(1.04)', boxShadow: '0 0 0 12px rgba(244, 63, 94, 0)' },
          '100%': { transform: 'scale(0.96)', boxShadow: '0 0 0 0 rgba(244, 63, 94, 0)' },
        }
      }
    },
  },
  plugins: [],
}
