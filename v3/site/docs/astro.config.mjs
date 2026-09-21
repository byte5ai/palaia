// palaia docs site (SPEC-503). Astro + Starlight: static output, no
// server, search built in (Pagefind, bundled by Starlight itself).
import { unified } from "@astrojs/markdown-remark";
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
  // Astro 7 deprecated the top-level `markdown.remarkPlugins`; the plugin
  // rides on the configured processor instead (issue 399). `scripts/
  // check-links.mjs` is what would catch this plugin ever silently dropping.
  markdown: { processor: unified({ remarkPlugins: [remarkBaseAbsoluteLinks] }) },
  integrations: [
    starlight({
      title: "palaia docs",
      description:
        "Set up palaia and connect your AI tools to one shared memory — the user guide for 3.0.",
      // Default to dark, matching palaia.ai (which is dark-only), while
      // keeping Starlight's toggle. This runs in the <head> just before
      // Starlight's own theme script and, only when the reader has made no
      // explicit choice yet, seeds the stored theme to dark — so Starlight
      // reads "dark" instead of falling back to the OS preference, the theme
      // picker stays consistent ("Dark", not "Auto"), and there is no flash.
      // A later explicit Light/Auto choice overwrites this and is respected.
      // (custom.css's dark palette is the palaia.ai key.)
      head: [
        {
          tag: "script",
          content:
            "try{if(!localStorage.getItem('starlight-theme'))localStorage.setItem('starlight-theme','dark')}catch(e){}",
        },
      ],
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
        { label: "Edit in Obsidian", slug: "edit-in-obsidian" },
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
