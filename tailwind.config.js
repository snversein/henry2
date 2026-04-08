/** @type {import('tailwindcss').Config} */
module.exports = {
  content: ["./templates/**/*.{html,js}"],
  theme: {
    extend: {
      colors: {
        primary: '#d4a574',
        secondary: '#8b7355',
        accent: '#e94560',
        cream: '#faf8f5',
      }
    },
  },
  plugins: [],
}
