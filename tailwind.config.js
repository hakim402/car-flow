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
          500: "#2F6FED",
          600: "#245ED2",
          700: "#1F4EAE",
          950: "#0C1F4A",
        },
      },
      boxShadow: {
        panel: "0 1px 2px rgba(16,24,40,.04), 0 12px 30px rgba(16,24,40,.055)",
      },
    },
  },
  plugins: [],
};
