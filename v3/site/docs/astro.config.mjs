// palaia docs site (SPEC-503). Astro + Starlight: static output, no
// server, search built in (Pagefind, bundled by Starlight itself).
import starlight from "@astrojs/starlight";
import { defineConfig } from "astro/config";

export default defineConfig({
  // A placeholder — hosting/DNS for this site is out of this SPEC's scope
  // (SPEC-503 non-goals), and Starlight/Astro's sitemap needs *some* origin
  // to build absolute URLs against. Set this to the real domain once one
  // is chosen; nothing else in the site depends on this value being right.
  site: "https://docs.palaia.example",
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
            { label: "Install it", slug: "install" },
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
        { label: "Troubleshooting & FAQ", slug: "troubleshooting" },
        { label: "For developers", slug: "developers" },
      ],
    }),
  ],
});
