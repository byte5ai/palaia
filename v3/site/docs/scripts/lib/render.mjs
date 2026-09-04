// Turns one clients.ts / skills.ts catalog entry into a Starlight page.
// Every string that reaches the page either comes straight out of the
// catalog (deliverable #2 — no retyping) or is this module's own connective
// prose, which is written jargon-free on purpose (deliverable #3): no
// protocol name outside a code span, "your memory" rather than the
// in-house word for it, "sign in" rather than the standard's name.

// A real address the wizard actually assigns by default (MASTERPLAN §9:
// mDNS puts the dashboard at http://palaia.local) — a placeholder that
// reads as genuine rather than <your-hub-address>.
export const PLACEHOLDER_ORIGIN = "http://palaia.local";
export const PLACEHOLDER_PROFILE = "default";
export const PLACEHOLDER_ISSUER = "https://palaia.example.com";

// Issue 318: the catalog renders every snippet with clients.ts's own
// `TOKEN_PLACEHOLDER` when no token is passed (this generator never has
// one — a token exists only in the dashboard, shown once). This sentence
// tells the reader what to put there; the shorter form follows the second
// and third snippet on the same page so it is never left implicit.
const TOKEN_PLACEHOLDER = "<paste-your-token>";
const TOKEN_NOTE =
  `Replace \`${TOKEN_PLACEHOLDER}\` with the token the dashboard shows when you click **Issue token** ` +
  "on its connect page — it is shown once, so copy it then. Every request needs it; without it the hub turns the tool away.";
const TOKEN_NOTE_AGAIN = `Same here: replace \`${TOKEN_PLACEHOLDER}\` with your token.`;

// A YAML comment, not an HTML one — it has to live *inside* the
// frontmatter fence, because the fence must be the first bytes of the
// file for Astro's frontmatter parser to recognize it at all.
const GENERATED_NOTE =
  "# Generated from v3/web/src/lib/clients.ts and skills.ts by " +
  "v3/site/docs/scripts/generate-connect-pages.mjs. Do not hand-edit —\n" +
  "# change the source and run `npm run gen:connect` from v3/site/docs.";

function frontmatter(title, description) {
  const esc = (s) => s.replace(/"/g, '\\"');
  return `---\n${GENERATED_NOTE}\ntitle: "${esc(title)}"\ndescription: "${esc(description)}"\n---\n`;
}

function fence(lang, text) {
  return `\`\`\`${lang}\n${text}\n\`\`\`\n`;
}

// clients.ts/skills.ts say "MCP" in a handful of their own UI strings
// (grok's subtitle, a couple of unsupported-skill explanations) — the
// dashboard's own lint allows that acronym in its copy, but this site's
// shared blocklist does not allow it outside a code span. Rather than
// retype those strings (deliverable #2 forbids that), this marks the one
// acronym as code wherever it appears in prose pulled from the catalog —
// same words, same meaning, just typeset as the term it is. Never applied
// to command/prompt/config text, which is already inside a fenced block.
function codeSpanProtocolAcronyms(text) {
  return text.replace(/\bMCP\b/g, "`MCP`");
}

function renderSkillSection(support) {
  const lines = ["## Teach it to look things up and save things on its own", ""];
  if (support.kind === "supported") {
    lines.push(support.install.headline, "");
    for (const [i, step] of support.install.steps.entries()) {
      lines.push(`${i + 1}. ${step}`);
    }
    if (support.install.command) {
      lines.push("", fence("bash", support.install.command).trimEnd());
    }
  } else if (support.kind === "unsupported") {
    lines.push(codeSpanProtocolAcronyms(support.reason));
  } else {
    lines.push(codeSpanProtocolAcronyms(support.note));
  }
  return lines.join("\n") + "\n";
}

// client.reason(mode) legitimately returns the identical string for two
// modes when the underlying condition is the same (today: cloud and open
// both just need sign-in turned on) — grouping those modes under one
// bullet keeps the page honest without repeating a sentence twice.
function modeReasonBlock(client) {
  const modes = [
    ["locked", "Locked mode"],
    ["cloud", "Cloud mode"],
    ["open", "Open mode"],
  ];
  const byReason = new Map();
  for (const [mode, label] of modes) {
    const reason = client.reason(mode);
    if (!byReason.has(reason)) byReason.set(reason, []);
    byReason.get(reason).push(label);
  }
  return [...byReason.entries()]
    .map(([reason, labels]) => `- **${labels.join(" or ")}.** ${reason}`)
    .join("\n");
}

export function renderGuidedPage(client, skillSupport) {
  const command = client.command(PLACEHOLDER_ORIGIN, PLACEHOLDER_PROFILE);
  const prompt = client.prompt(PLACEHOLDER_ORIGIN, PLACEHOLDER_PROFILE);
  const parts = [
    frontmatter(client.name, `Connect ${client.name} to your shared memory.`),
    `Time: about ${client.estimate}.`,
    "",
    "## Copy one line",
    "",
    "Paste this into a terminal where the tool is already set up. It adds the connection; nothing else changes.",
    "",
    fence("bash", command).trimEnd(),
    "",
    TOKEN_NOTE,
    "",
    "## Or just ask it",
    "",
    "If you would rather not touch a terminal, paste this to the AI itself and let it set itself up:",
    "",
    fence("text", prompt).trimEnd(),
    "",
    TOKEN_NOTE_AGAIN,
    "",
  ];
  if (client.configFile) {
    const file = client.configFile(PLACEHOLDER_ORIGIN, PLACEHOLDER_PROFILE);
    parts.push(
      "## Or save a file",
      "",
      `Some setups read this from a file instead of a command. Save it as \`${file.filename}\`:`,
      "",
      fence(file.mimeType.includes("json") ? "json" : "toml", file.content).trimEnd(),
      "",
      TOKEN_NOTE_AGAIN,
      "",
    );
  }
  parts.push(
    renderSkillSection(skillSupport),
    "",
    "## Check it worked",
    "",
    "Ask it to remember something, then ask a different connected AI whether it knows the same thing. " +
      "If both answer the same way, the connection is live — see [Your first shared memory](/first-shared-memory/) " +
      "for the full walkthrough.",
    "",
  );
  return tidy(parts.join("\n"));
}

export function renderDownloadPage(client, skillSupport) {
  const parts = [
    frontmatter(client.name, `Connect ${client.name} to your shared memory.`),
    codeSpanProtocolAcronyms(client.subtitle),
    "",
    "## Download and open it",
    "",
    "1. Open your dashboard's connect page and choose this tool — the download button builds a file addressed to your own hub, so " +
      "there is nothing to type or paste.",
    "2. Open the downloaded file. The tool recognizes it and asks you to confirm the connection.",
    "3. Confirm. You are connected.",
    "",
    renderSkillSection(skillSupport),
    "",
    "## Check it worked",
    "",
    "Ask it to remember something, then ask a different connected AI whether it knows the same thing. " +
      "If both answer the same way, the connection is live — see [Your first shared memory](/first-shared-memory/) " +
      "for the full walkthrough.",
    "",
  ];
  return tidy(parts.join("\n"));
}

export function renderNotYetPage(client, skillSupport) {
  const parts = [
    frontmatter(client.name, `Connect ${client.name} to your shared memory.`),
    codeSpanProtocolAcronyms(client.subtitle),
    "",
    "## What has to be true first",
    "",
    modeReasonBlock(client),
    "",
  ];
  if (client.oauthConnect) {
    const example = client.oauthConnect(PLACEHOLDER_ISSUER, PLACEHOLDER_PROFILE);
    parts.push(
      "## Once sign-in is on",
      "",
      example.note,
      "",
      fence("text", example.url).trimEnd(),
      "",
    );
  }
  parts.push(
    renderSkillSection(skillSupport),
    "",
    "## Check it worked",
    "",
    "Ask it to remember something, then ask a different connected AI whether it knows the same thing. " +
      "If both answer the same way, the connection is live — see [Your first shared memory](/first-shared-memory/) " +
      "for the full walkthrough.",
    "",
  );
  return tidy(parts.join("\n"));
}

/** Collapse the incidental double-blank-lines that fall out of joining a
 * section (which already ends in "\n") into an array that adds its own
 * blank-line separator. Purely cosmetic — Markdown treats any run of blank
 * lines as one, but a stray double blank reads as a generation glitch. */
function tidy(markdown) {
  return markdown.replace(/\n{3,}/g, "\n\n");
}

export function renderClientPage(client, skillSupport) {
  if (client.kind === "guided") return renderGuidedPage(client, skillSupport);
  if (client.kind === "download") return renderDownloadPage(client, skillSupport);
  return renderNotYetPage(client, skillSupport);
}

export function slugFor(client) {
  return client.id;
}

export function renderIndexPage(clients) {
  const readyNow = clients.filter((c) => c.kind !== "notYet");
  const needsSignIn = clients.filter((c) => c.kind === "notYet");
  const line = (c) => `- **[${c.name}](/connect/clients/${slugFor(c)}/)** — ${
    c.kind === "guided" ? `about ${c.estimate}` : codeSpanProtocolAcronyms(c.subtitle)
  }`;
  const parts = [
    frontmatter("Connect your AI", "Every AI tool palaia can connect to, and how to do it."),
    "Pick the tool you use. Each one takes a couple of minutes, and every tool you connect reads and writes the same memory — " +
      "connect two, and the second one already knows what the first one learned.",
    "",
    "## Works right now",
    "",
    ...readyNow.map(line),
    "",
    "## Needs one thing turned on first",
    "",
    "These connect from a company's own service rather than from your device, so they need your hub reachable from the " +
      "internet and sign-in turned on. Each page says exactly what to turn on and how.",
    "",
    ...needsSignIn.map(line),
    "",
    "Using something else? Any tool that speaks the open connector protocol works the same way — see " +
      "[Any other AI tool](/connect/clients/generic/).",
    "",
  ];
  return tidy(parts.join("\n"));
}
