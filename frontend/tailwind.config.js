/** @type {import('tailwindcss').Config} */
module.exports = {
  content: [
    './src/pages/**/*.{js,ts,jsx,tsx,mdx}',
    './src/components/**/*.{js,ts,jsx,tsx,mdx}',
    './src/app/**/*.{js,ts,jsx,tsx,mdx}',
  ],
  theme: {
    extend: {
      colors: {
        brand: {
          50: '#f0f4ff',
          100: '#e0e9ff',
          200: '#c7d5fe',
          300: '#a5b8fc',
          400: '#8196f8',
          500: '#6272f3',
          600: '#4a52e7',
          700: '#3d43ce',
          800: '#3239a6',
          900: '#2e3483',
          950: '#1c1f4f',
        },
        surface: {
          0: '#0d0e1a',
          1: '#13152b',
          2: '#1a1d38',
          3: '#222645',
          4: '#2a2f54',
        },
        muted: '#8b92b8',
        border: '#2e3460',
      },
      fontFamily: {
        sans: ['Inter', 'system-ui', 'sans-serif'],
        mono: ['JetBrains Mono', 'monospace'],
      },
      backgroundImage: {
        'gradient-radial': 'radial-gradient(var(--tw-gradient-stops))',
        'gradient-brand': 'linear-gradient(135deg, #6272f3 0%, #a855f7 100%)',
        'gradient-dark': 'linear-gradient(135deg, #0d0e1a 0%, #1a1d38 100%)',
      },
      boxShadow: {
        'glow-sm': '0 0 10px rgba(98, 114, 243, 0.15)',
        'glow': '0 0 20px rgba(98, 114, 243, 0.25)',
        'glow-lg': '0 0 40px rgba(98, 114, 243, 0.35)',
      },
      animation: {
        'fade-in': 'fadeIn 0.3s ease-out',
        'slide-up': 'slideUp 0.4s ease-out',
        'pulse-slow': 'pulse 3s cubic-bezier(0.4, 0, 0.6, 1) infinite',
        'spin-slow': 'spin 3s linear infinite',
      },
      keyframes: {
        fadeIn: {
          '0%': { opacity: '0' },
          '100%': { opacity: '1' },
        },
        slideUp: {
          '0%': { opacity: '0', transform: 'translateY(16px)' },
          '100%': { opacity: '1', transform: 'translateY(0)' },
        },
      },
    },
  },
  plugins: [],
}
