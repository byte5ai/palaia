// palaia docs site (SPEC-503). Astro + Starlight: static output, no
// server, search built in (Pagefind, bundled by Starlight itself).
import starlight from "@astrojs/starlight";
import { defineConfig } from "astro/config";

const BASE = "/docs";

// Content here was authored with root-absolute internal links (e.g.
// `/install/`, `/connect/`) from when the site would have lived at a domain
// root. Served under `base`, those links must carry the `/docs` prefix or they
// point outside the docs site. Astro prefixes the base to its own generated
// links and assets and to relative Markdown links — but NOT to absolute URLs
// written by hand in Markdown. This remark plugin does that, once, for every
// content link/image, so authors can keep writing `/foo/` and stay correct.
// (`scripts/check-links.mjs` verifies the result: no `/docs/...` link is left
// dangling.)
function remarkBaseAbsoluteLinks() {
  const withBase = (url) => {
    if (typeof url !== "string" || !url.startsWith("/") || url.startsWith("//")) return url;
    if (url === BASE || url.startsWith(`${BASE}/`)) return url;
    return `${BASE}${url}`;
  };
  const walk = (node) => {
    if (!node || typeof node !== "object") return;
    if (
      (node.type === "link" || node.type === "image" || node.type === "definition") &&
      typeof node.url === "string"
    ) {
      node.url = withBase(node.url);
    }
    if (Array.isArray(node.children)) node.children.forEach(walk);
  };
  return (tree) => walk(tree);
}

export default defineConfig({
  // The docs are served as a subpath of the palaia homepage: the
  // palaia-homepage repo serves this build at palaia.byte5.ai/docs (see that
  // repo's DOCS-HOSTING.md). `base` makes every link and asset resolve under
  // /docs; `site` gives the absolute origin for sitemap/canonical URLs.
  site: "https://palaia.byte5.ai",
  base: BASE,
  markdown: { remarkPlugins: [remarkBaseAbsoluteLinks] },
  integrations: [
    starlight({
      title: "palaia docs",
      description:
        "Set up palaia and connect your AI tools to one shared memory — the user guide for 3.0.",
      social: [
        { icon: "github", label: "GitHub", href: "https://github.com/byte5ai/palaia" },
      ],
      customCss: ["./src/styles/custom.css"],
      editLink: {
        baseUrl: "https://github.com/byte5ai/palaia/edit/main/v3/site/docs/",
      },
      sidebar: [
        {
          label: "Start here",
          items: [
            { label: "What is palaia?", slug: "index" },
            // SPEC-504: the onboarding page — not a content-collection
            // entry (see src/pages/onboarding.astro's own docstring), so
            // it is linked by its literal route here rather than `slug`.
            { label: "Get palaia running", link: "/onboarding/" },
            { label: "Install it (the full version)", slug: "install" },
            // SPEC-602: generated (see scripts/lib/synology.mjs) — its
            // pasted compose block comes straight out of
            // v3/deploy/docker-compose.yml, never a hand-typed copy.
            { label: "Synology (no terminal)", slug: "install-synology" },
            { label: "Your first shared memory", slug: "first-shared-memory" },
            {
              label: "Moving from v2?",
              // The guide itself lives with the rest of the engineering docs
              // (v3/docs/), not in this site's own content — same pattern as
              // the "For developers" links below, one canonical copy.
              link: "https://github.com/byte5ai/palaia/blob/main/v3/docs/migrate-from-v2.md",
              attrs: { target: "_blank", rel: "noreferrer" },
            },
          ],
        },
        {
          label: "Connect your AI",
          items: [
            { label: "Overview", slug: "connect" },
            { label: "Every tool", items: [{ autogenerate: { directory: "connect/clients" } }] },
          ],
        },
        { label: "Your memory", slug: "memory" },
        { label: "Marketplace & tools", slug: "marketplace" },
        { label: "Profiles & access", slug: "access" },
        { label: "Agents & messages", slug: "agents-messages" },
        { label: "Automations", slug: "automations" },
        { label: "Back up & restore", slug: "backup-restore" },
        { label: "Troubleshooting & FAQ", slug: "troubleshooting" },
        { label: "For developers", slug: "developers" },
      ],
    }),
  ],
});
