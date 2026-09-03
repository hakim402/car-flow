/** Tailwind CSS config — compiled at image build time (dev: npm run css).
 *  Only logical RTL-safe utilities are used in templates (agent.md §11.3). */
module.exports = {
  darkMode: "class",
  content: [
    "./templates/**/*.html",
    "./apps/**/templates/**/*.html",
  ],
  theme: {
    extend: {
      fontFamily: {
        sans: ["Inter", "ui-sans-serif", "system-ui"],
        dari: ["Vazirmatn", "Noto Sans Arabic", "sans-serif"],
        pashto: ["Noto Sans Arabic", "Vazirmatn", "sans-serif"],
      },
      colors: {
        brand: {
          50: "#EFF6FF",
          100: "#DBEAFE",
          200: "#BFDBFE",
          300: "#93C5FD",
          400: "#60A5FA",
          500: "#3B82F6",
          600: "#2563EB",
          700: "#1D4ED8",
          800: "#1E40AF",
          900: "#1E3A8A",
          950: "#172554",
        },
      },
      boxShadow: {
        panel: "0 1px 2px rgba(16,24,40,.04), 0 12px 30px rgba(16,24,40,.055)",
      },
    },
  },
  plugins: [],
};
