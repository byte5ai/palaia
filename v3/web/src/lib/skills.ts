/**
 * The skill packages the connect page can hand a client (SPEC-207 #3).
 *
 * A memory nobody consults is a filing cabinet. The skills are what turn the
 * hub's tools into something an agent reaches for on its own, so the connect
 * flow offers them right where a client is being wired up — but only to
 * clients that can actually load one, which is what `SkillSupport` on each
 * catalog entry decides.
 *
 * The text is not restated here: both packages are imported straight from
 * `v3/clients/skills/**` with `?raw`, and the name and one-line summary shown
 * in the UI are read out of that file's own frontmatter. There is exactly one
 * copy of every word a user sees, and it is the file the agent loads — so the
 * page cannot drift from the skill, and "copy" hands over the real thing
 * rather than a paraphrase of it.
 */
import captureSource from "../../../clients/skills/palaia-capture/SKILL.md?raw";
import memorySource from "../../../clients/skills/palaia-memory/SKILL.md?raw";

export interface SkillInstall {
  /** One line: how this client takes a skill. */
  headline: string;
  /** Ordered, concrete steps. */
  steps: string[];
  /** A copyable one-liner, where the client has one. */
  command?: string;
}

export type SkillSupport =
  | { kind: "supported"; install: SkillInstall }
  | { kind: "unsupported"; reason: string }
  /** Reads SKILL.md folders in principle, but we have not verified where. */
  | { kind: "unknown"; note: string };

export interface SkillPackage {
  /** Directory name under `v3/clients/skills/`, and the skill's declared name. */
  slug: string;
  /** The skill's own `description`, read from its frontmatter. */
  summary: string;
  /** Who this one is for — the choice a user actually has to make. */
  audience: string;
  /** The SKILL.md file, verbatim. */
  source: string;
}

/** Read one scalar key out of a SKILL.md frontmatter block. */
export function frontmatterValue(source: string, key: string): string {
  const match = /^---\r?\n([\s\S]*?)\r?\n---/.exec(source);
  if (!match) return "";
  const line = match[1]!
    .split(/\r?\n/)
    .find((candidate) => candidate.startsWith(`${key}:`));
  return line ? line.slice(key.length + 1).trim() : "";
}

function pkg(source: string, audience: string): SkillPackage {
  return {
    slug: frontmatterValue(source, "name"),
    summary: frontmatterValue(source, "description"),
    audience,
    source,
  };
}

export const SKILLS: SkillPackage[] = [
  pkg(
    memorySource,
    "Start here. Teaches an agent both halves: look things up before it decides, and save what is worth keeping.",
  ),
  pkg(
    captureSource,
    "For a smaller or tightly budgeted agent: saving only, nothing about looking things up.",
  ),
];

export function skillBySlug(slug: string): SkillPackage | undefined {
  return SKILLS.find((skill) => skill.slug === slug);
}

// --- per-client support ------------------------------------------------
//
// Every claim below traces to MASTERPLAN §6 and the research dossier it
// cites (`v3/research/mcp-landscape-2026.md`): Agent Skills is an open
// standard with ~40 adopters, and the dossier names which of our matrix
// clients are among them. Where a client supports skills but we have not
// verified *where* it reads them from, the entry says so instead of
// inventing a path — a confidently wrong path costs a user more than an
// honest "check your tool's docs".

const CLAUDE_SKILLS_FOLDER: SkillInstall = {
  headline: "Save the folder, or load the whole package for one session.",
  steps: [
    "Create ~/.claude/skills/<name>/ and save SKILL.md into it — one folder per skill.",
    "Start a new session; the skill is offered from then on, and loads itself when a task needs it.",
    "Trying it out first: clone this repo and pass v3/clients as a plugin, which loads both skills for that session only.",
  ],
  command: "claude --plugin-dir /path/to/palaia/v3/clients",
};

const SKILL_SUPPORT: Record<string, SkillSupport> = {
  "claude-code-cli": { kind: "supported", install: CLAUDE_SKILLS_FOLDER },
  "claude-desktop": { kind: "supported", install: CLAUDE_SKILLS_FOLDER },
  "claude-ai": {
    kind: "supported",
    install: {
      headline: "Add it as a capability in your account settings.",
      steps: [
        "Download SKILL.md and zip its folder (the folder name must match the skill's name).",
        "In claude.ai, open Settings → Capabilities → Skills and upload the zip.",
        "It then applies to web, desktop, mobile and Cowork — the memory itself still needs the connector below.",
      ],
    },
  },
  codex: {
    kind: "supported",
    install: {
      headline: "Codex reads Agent Skills from its own skills directory.",
      steps: [
        "Save SKILL.md into a folder named after the skill.",
        "Move that folder into the skills directory Codex reads (shared with ChatGPT plugins since July 2026 — your Codex version's docs name the exact path).",
        "Start a new Codex session and the skill is available.",
      ],
    },
  },
  chatgpt: {
    kind: "supported",
    install: {
      headline: "Skills and connectors live in one plugin directory, shared with Codex.",
      steps: [
        "Save SKILL.md into a folder named after the skill.",
        "Add it to the plugin directory ChatGPT and Codex share.",
        "Write access to the memory itself is plan-gated — see the connector note for this client.",
      ],
    },
  },
  "gemini-cli": {
    kind: "supported",
    install: {
      headline: "Gemini CLI supports Agent Skills.",
      steps: [
        "Save SKILL.md into a folder named after the skill.",
        "Put that folder in the skills directory your Gemini CLI version reads (its docs name the path).",
        "Start a new session to pick it up.",
      ],
    },
  },
  grok: {
    kind: "unsupported",
    reason:
      "Grok connects custom MCP servers but does not load SKILL.md packages, so there is nothing here to install. The memory still works — the tool descriptions carry their own guidance; you just have to ask for it.",
  },
  "lm-studio": {
    kind: "unsupported",
    reason:
      "LM Studio is an MCP host, not a skill loader — it has no place to put a SKILL.md. The memory still works; put the same guidance in the model's system prompt, or ask for it directly.",
  },
  generic: {
    kind: "unknown",
    note:
      "If your tool reads SKILL.md folders (about forty do), these files work as they are: one folder per skill, SKILL.md inside it, in whichever directory your tool scans. If it does not, the memory still works without them.",
  },
};

/** What this client can do with a skill package. */
export function skillSupportFor(clientId: string): SkillSupport {
  return (
    SKILL_SUPPORT[clientId] ?? {
      kind: "unknown",
      note: "We have not checked whether this client loads SKILL.md packages.",
    }
  );
}

/** Client ids that have an entry here — used to keep the catalog honest. */
export function clientsWithSkillSupport(): string[] {
  return Object.keys(SKILL_SUPPORT);
}
