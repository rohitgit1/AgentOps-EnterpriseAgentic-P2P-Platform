/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        ink: {
          950: '#080b14', 900: '#0c1120', 850: '#111832', 800: '#161f3d',
          700: '#1e2a4f', 600: '#2b3a66', 500: '#3d4f80',
        },
        accent: { DEFAULT: '#4f8ef7', soft: '#7aa9fa', deep: '#2c62c9' },
        mint: '#2fbf87', amber: '#f0a93b', rose: '#f0546a', violet: '#9b7bf5',
      },
      fontFamily: {
        sans: ['Inter', 'ui-sans-serif', 'system-ui', '-apple-system', 'Segoe UI', 'Roboto', 'sans-serif'],
        mono: ['ui-monospace', 'SFMono-Regular', 'Menlo', 'monospace'],
      },
      boxShadow: {
        panel: '0 1px 2px rgba(0,0,0,.35), 0 8px 28px -12px rgba(0,0,0,.55)',
        lift: '0 18px 45px -18px rgba(0,0,0,.75)',
      },
      keyframes: {
        'fade-up': { '0%': { opacity: 0, transform: 'translateY(6px)' }, '100%': { opacity: 1, transform: 'none' } },
        pulseRing: { '0%,100%': { opacity: .35 }, '50%': { opacity: 1 } },
      },
      animation: { 'fade-up': 'fade-up .28s ease-out both', ping2: 'pulseRing 2s ease-in-out infinite' },
    },
  },
  plugins: [],
}
