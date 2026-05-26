import type { Config } from 'tailwindcss'

const config: Config = {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      fontFamily: {
        sans: ['Plus Jakarta Sans', 'system-ui', '-apple-system', 'BlinkMacSystemFont', 'Helvetica Neue', 'sans-serif'],
      },
      colors: {
        site: {
          bg:       '#080b12',
          surface:  '#0d1117',
          card:     '#111827',
          accent:   '#0ea5e9',
          accent2:  '#38bdf8',
          text:     '#f1f5f9',
          muted:    '#94a3b8',
          subtle:   '#475569',
          green:    '#10b981',
          green2:   '#34d399',
          amber:    '#f59e0b',
          purple:   '#7c3aed',
          purple2:  '#c4b5fd',
          cyan:     '#06b6d4',
        },
      },
      borderColor: {
        DEFAULT: 'rgba(100,130,200,0.10)',
        strong:  'rgba(100,130,200,0.18)',
      },
      animation: {
        'path-flow': 'pathFlow 20s linear infinite',
      },
    },
  },
  plugins: [],
}

export default config
