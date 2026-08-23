/**
 * Ladle config — the living style guide for the component library
 * (SPEC-109 deliverable #1). Ladle over Storybook: same Vite pipeline
 * as the app itself (so Tailwind v4's `@theme inline` binding to the
 * Lume tokens behaves identically here and in the real build), far
 * fewer dependencies, and no separate webpack/vite config to keep in
 * sync.
 */
export default {
  stories: "src/**/*.stories.{ts,tsx}",
  addons: {
    a11y: { enabled: true },
    theme: { enabled: true, defaultState: "light" },
    mode: { enabled: true },
    width: { enabled: true },
  },
};
