/** Tailwind CSS config — compiled at image build time (dev: npm run css).
 *  Only logical RTL-safe utilities are used in templates (agent.md §11.3). */
module.exports = {
  content: [
    "./templates/**/*.html",
    "./apps/**/templates/**/*.html",
  ],
  theme: {
    extend: {},
  },
  plugins: [],
};
