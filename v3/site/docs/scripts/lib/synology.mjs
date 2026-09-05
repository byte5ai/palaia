// Generates the Synology Container Manager walkthrough
// (`src/content/docs/install-synology.md`) — the no-terminal path for
// Synology NAS owners: open Container Manager, create a project, paste
// the compose file, choose a folder for it, start it, open the hub.
//
// The pasted compose file is never hand-typed here: it is read straight
// out of `v3/deploy/docker-compose.yml` at generation time
// (`deploy-snippets.mjs`'s `loadComposeFile()`), the same "extract, don't
// copy" rule `scripts/lib/render.mjs` already applies to the connect
// pages and `src/pages/onboarding.astro` applies to its own commands.
// Regenerate with `npm run gen:synology` after editing this file or after
// `docker-compose.yml` changes; `npm run check:generated` fails loudly if
// the two ever disagree.
import path from "node:path";
import { loadComposeFile } from "./deploy-snippets.mjs";

export const SYNOLOGY_PAGE_PATH = path.join("src", "content", "docs", "install-synology.md");

const GENERATED_NOTE =
  "# Generated from v3/deploy/docker-compose.yml by " +
  "v3/site/docs/scripts/generate-synology-page.mjs. Do not hand-edit the\n" +
  "# compose block below — change docker-compose.yml and run " +
  "`npm run gen:synology` from v3/site/docs.";

function frontmatter(title, description) {
  const esc = (s) => s.replace(/"/g, '\\"');
  return `---\n${GENERATED_NOTE}\ntitle: "${esc(title)}"\ndescription: "${esc(description)}"\n---\n`;
}

/** Collapse the incidental double-blank-lines that fall out of joining
 * sections (each already ending in "\n") — cosmetic only, Markdown treats
 * a run of blank lines as one either way. */
function tidy(markdown) {
  return markdown.replace(/\n{3,}/g, "\n\n");
}

export function renderSynologyPage() {
  const compose = loadComposeFile();

  const parts = [
    frontmatter(
      "Synology (no terminal)",
      "Run palaia on a Synology NAS through Container Manager — paste one file, nothing typed at a command line.",
    ),
    "Synology's Container Manager app runs the same container image every other install page on this site " +
      "uses — you just get there by pasting a file into a form instead of running a command. Nothing below " +
      "needs the NAS's command line.",
    "",
    "## What you need",
    "",
    "- A Synology NAS running DSM 7.2 or later, with **Container Manager** installed (Package Center → " +
      "search \"Container Manager\" → Install, if it isn't already).",
    "- A few minutes and a browser open to your NAS's own web interface — the same one you used to install " +
      "Container Manager.",
    "",
    "<!-- screenshot: Container Manager's own overview screen right after opening it, showing the left-hand " +
      "navigation (Project, Container, Image, Registry) -->",
    "",
    "## Open Container Manager and start a new project",
    "",
    "1. Open **Container Manager** from DSM's main menu.",
    "2. Go to the **Project** section in the left-hand navigation.",
    "3. Use the button that creates a new project (in current versions of Container Manager this is labeled " +
      "**Create**).",
    "4. Give it a name — `palaia` is fine, and does not need to match anything else.",
    "5. Choose or create the shared folder Container Manager should keep this project's files in. The folder " +
      "name doesn't matter either; this is just where Container Manager stores the file you paste next, not " +
      "where palaia keeps what you save in it (more on that below).",
    "",
    "## Paste the compose file",
    "",
    "Container Manager's next step asks how you want to provide the project's setup. Look for the option " +
      "that lets you type or paste a compose file directly, rather than uploading one — depending on your " +
      "version this is labeled something close to **Create docker-compose.yml**. Paste the file below into " +
      "that box exactly as it is, then continue.",
    "",
    "<!-- screenshot: the project-creation step with this page's compose file pasted into Container Manager's " +
      "text box, before continuing to the next step -->",
    "",
    "```yaml",
    compose,
    "```",
    "",
    "This is the same file the [Install it](/install/) page's Compose option uses — nothing Synology-specific " +
      "has been changed, so it stays correct as that file does.",
    "",
    // Issue #326: the compose file pins the `stable` channel, which the release
    // workflow only creates on the final tag. server/tests/test_version_drift.py
    // requires this note exactly while VERSION carries a pre-release suffix.
    "<!-- rc-channel-note -->",
    "> **Release candidate:** until `3.0.0` is final there is no `stable` image yet. Before you paste the",
    "> file above, change its `image:` line from `ghcr.io/byte5ai/palaia-hub:stable` to",
    "> `ghcr.io/byte5ai/palaia-hub:beta`.",
    "",
    "## About that shared folder, and where your memory actually lives",
    "",
    "The folder you picked two steps ago holds the project's own compose file — it is not where palaia keeps " +
      "what you save. That lives in the `palaia_home` volume the pasted file declares at its bottom, which " +
      "Docker manages on its own and keeps around even if you delete the project and recreate it later. You " +
      "don't need to do anything about this; it's mentioned here only so deleting the project folder later " +
      "doesn't look like it should have deleted your memory too — it doesn't.",
    "",
    "## Start it",
    "",
    "Continue past any remaining setup screens (Container Manager may offer to also set up quick web access " +
      "— safe to skip, it isn't needed) and finish creating the project. Container Manager pulls the image " +
      "and starts the container; the project's status shows **Running** once it has.",
    "",
    "<!-- screenshot: the finished project showing status Running, with its one container (palaia-hub) listed -->",
    "",
    "If it doesn't reach **Running**, open the container's log from Container Manager itself — the " +
      "**Container** section, select `palaia-hub`, then its **Log** (or **Details**) tab — rather than a " +
      "terminal; the same startup message [Install it](/install/) describes shows up there.",
    "",
    "## Open the hub",
    "",
    "You reached Container Manager just now through your NAS's own address in a browser — the same address, " +
      "with `:8420` instead of DSM's own port, reaches palaia:",
    "",
    "```text",
    "http://<your-NAS-address>:8420",
    "```",
    "",
    "The container also tries to advertise itself as `http://palaia.local` on your network, the same as every " +
      "other install path — whether that resolves depends on how Synology's own networking handles it, the " +
      "same caveat [Install it](/install/)'s network section covers for other setups. Either way, the address " +
      "above always works.",
    "",
    "From there, a short setup wizard takes over — see [Get palaia running](/onboarding/) for what that looks " +
      "like, or [Your first shared memory](/first-shared-memory/) for the full walkthrough once it's done.",
    "",
    "## Later: updating",
    "",
    "Open the project in Container Manager and use the action that rebuilds it from the compose file — " +
      "usually an **Action** menu or **Build** button on the project's own page. If your version doesn't pull " +
      "a fresh image on its own, delete the project and recreate it the same way as above: your memory is " +
      "untouched either way, since it lives in the separate `palaia_home` volume, not the project's folder.",
    "",
    "Something not covered here? [Troubleshooting & FAQ](/troubleshooting/) covers the issues people actually " +
      "hit, or the project's [issue tracker](https://github.com/byte5ai/palaia) for anything new.",
    "",
    // A single HTML comment: HTML comments do not nest, so this block must
    // never contain the literal four-character sequence "-->" anywhere in
    // its body (including inside this note) — that would close it early
    // and spill the rest as rendered text. Referring to the screenshot
    // markers by what they say ("screenshot: ...") rather than quoting
    // their full "<!-- ... -->" syntax keeps that true.
    "<!--",
    "Owner verification checklist (for whoever owns a real Synology device — not part of the guide above):",
    "- [ ] Walk through every numbered step on an actual Synology NAS running Container Manager, and fix any",
    "      step whose wording no longer matches what's on screen.",
    "- [ ] Confirm the compose block above still pastes cleanly into Container Manager's project editor with",
    "      no manual edits needed.",
    "- [ ] Replace each screenshot marker above (the \"screenshot: ...\" comments) with a real image,",
    "      following SHOTLIST.md's instructions, then delete that marker's row from SHOTLIST.md.",
    "- [ ] Once every marker above is replaced, delete this comment block too.",
    "-->",
    "",
  ];

  return tidy(parts.join("\n"));
}

export async function buildSynologyPages() {
  const pages = new Map();
  pages.set(SYNOLOGY_PAGE_PATH, renderSynologyPage());
  return pages;
}
