/** @type {import('tailwindcss').Config} */
export default {
  content: [
    './index.html',
    './src/**/*.{js,jsx,ts,tsx}',
  ],
  darkMode: 'class',
  theme: {
    extend: {
      fontFamily: {
        sans: ['Inter', 'system-ui', 'sans-serif'],
        mono: ['JetBrains Mono', 'monospace'],
      },
      colors: {
        cmd: {
          bg:      '#05080f',
          surface: '#0a0f1e',
          card:    '#0f172a',
          border:  '#1e293b',
          muted:   '#334155',
          accent:  '#3b82f6',
        },
      },
      animation: {
        'slide-in': 'slideInDown 0.35s cubic-bezier(0.22,1,0.36,1) forwards',
        'fade-in':  'fadeIn 0.3s ease-out',
        'pulse-ring': 'pulseRing 2s ease-in-out infinite',
        'shimmer':  'shimmer 2s linear infinite',
        'count':    'countPop 0.4s ease-out',
      },
      keyframes: {
        slideInDown: {
          '0%':   { transform: 'translateY(-16px) scale(0.97)', opacity: '0' },
          '100%': { transform: 'translateY(0) scale(1)', opacity: '1' },
        },
        fadeIn: {
          '0%': { opacity: '0' }, '100%': { opacity: '1' },
        },
        pulseRing: {
          '0%,100%': { boxShadow: '0 0 0 0 rgba(59,130,246,0.4)' },
          '50%':     { boxShadow: '0 0 0 8px rgba(59,130,246,0)' },
        },
        shimmer: {
          '0%':   { backgroundPosition: '-200% 0' },
          '100%': { backgroundPosition: '200% 0' },
        },
        countPop: {
          '0%':   { color: '#60a5fa', transform: 'scale(1.15)' },
          '100%': { color: 'inherit', transform: 'scale(1)' },
        },
      },
      backgroundImage: {
        'grid-dots': 'radial-gradient(circle, rgba(148,163,184,0.08) 1px, transparent 1px)',
      },
      backgroundSize: {
        'grid-dots': '28px 28px',
      },
    },
  },
  plugins: [],
};
