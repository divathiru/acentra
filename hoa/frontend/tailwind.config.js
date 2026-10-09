/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  darkMode: 'class',
  theme: {
    extend: {
      colors: {
        teal: {
          DEFAULT: '#14808A',
          50: '#E8F6F7',
          100: '#C5EAED',
          200: '#8DD5DB',
          300: '#55C0C9',
          400: '#2FA3AE',
          500: '#14808A',
          600: '#10666E',
          700: '#0C4D53',
          800: '#083337',
          900: '#041A1C',
        },
      },
      fontFamily: {
        sans: ['Inter', 'system-ui', 'sans-serif'],
      },
      borderRadius: {
        '2xl': '1rem',
      },
    },
  },
  plugins: [],
};
