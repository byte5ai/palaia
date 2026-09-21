// The onboarding page's section headings, for Starlight's "On this page" table
// of contents. The page is a custom StarlightPage whose content is a slotted
// component (OnboardingBody), so Starlight cannot auto-extract the headings the
// way it does for Markdown — we pass them explicitly. Each `slug` matches the
// id="…" on the corresponding <h2> in OnboardingBody.astro; the `text` is
// localized from the per-locale dictionary, so the TOC reads in the page's
// language. Only the top-level sections (depth 2) are listed — the numbered
// cloud steps and the developer tab panels are deliberately left out.

interface OnboardingDict {
  ai: { h2: string };
  manual: { h2: string };
  cloud: { h2: string };
  existing: { h2: string };
  owned: { h2: string };
  dev: { h2: string };
  open: { h2: string };
  wizard: { h2: string };
}

export interface Heading {
  depth: number;
  slug: string;
  text: string;
}

export function onboardingHeadings(t: OnboardingDict): Heading[] {
  return [
    { depth: 2, slug: "let-your-ai-set-it-up", text: t.ai.h2 },
    { depth: 2, slug: "set-it-up-yourself", text: t.manual.h2 },
    { depth: 2, slug: "cloud-server", text: t.cloud.h2 },
    { depth: 2, slug: "already-have-a-server", text: t.existing.h2 },
    { depth: 2, slug: "your-own-machine", text: t.owned.h2 },
    { depth: 2, slug: "for-developers", text: t.dev.h2 },
    { depth: 2, slug: "open-your-hub", text: t.open.h2 },
    { depth: 2, slug: "the-wizard-takes-over", text: t.wizard.h2 },
  ];
}
