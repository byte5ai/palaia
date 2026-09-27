import { describe, expect, it } from "vitest";

import { CLIENTS } from "./clients";
import {
  clientsWithSkillSupport,
  frontmatterValue,
  SKILLS,
  skillBySlug,
  skillSupportFor,
} from "./skills";

// Every skill package on disk, so "every shipped package" is checked against
// the directory rather than against a list typed here.
const SHIPPED_SKILL_FILES = import.meta.glob(
  "../../../clients/skills/*/SKILL.md",
  { query: "?raw", import: "default", eager: true },
);

// Packages deliberately not offered on the connect-a-client page, each with
// the reason. Anything shipped must be in SKILLS or here — never neither.
const NOT_ON_CONNECT_PAGE: Record<string, string> = {
  // Issue 449: it sets palaia up before any hub exists; the connect page
  // belongs to a hub that is already running.
  "palaia-install": "guided install, used before a hub exists",
};

describe("skill catalog", () => {
  it("carries every shipped package, read from the shipped files", () => {
    expect(SKILLS.map((s) => s.slug)).toEqual([
      "palaia-memory",
      "palaia-capture",
      "palaia-messenger",
    ]);
  });

  it("accounts for every package on disk — offered here, or excluded with a reason", () => {
    const onDisk = Object.keys(SHIPPED_SKILL_FILES)
      .map((file) => file.split("/").at(-2)!)
      .sort();
    expect(onDisk.length).toBeGreaterThan(0);
    const accounted = [
      ...SKILLS.map((s) => s.slug),
      ...Object.keys(NOT_ON_CONNECT_PAGE),
    ].sort();
    expect(accounted).toEqual(onDisk);
    for (const slug of Object.keys(NOT_ON_CONNECT_PAGE))
      expect(skillBySlug(slug)).toBeUndefined();
  });

  it("shows the skill's own words — the page cannot drift from the file", () => {
    for (const skill of SKILLS) {
      // The summary is the SKILL.md `description`, not a restatement of it.
      expect(skill.summary).toBe(frontmatterValue(skill.source, "description"));
      expect(skill.summary.length).toBeGreaterThan(60);
      // Copy/download hand over the real file, frontmatter included.
      expect(skill.source.startsWith("---\n")).toBe(true);
      expect(skill.source).toContain(`name: ${skill.slug}`);
      expect(skill.audience.length).toBeGreaterThan(20);
    }
  });

  it("looks a package up by slug", () => {
    expect(skillBySlug("palaia-capture")?.slug).toBe("palaia-capture");
    expect(skillBySlug("nope")).toBeUndefined();
  });
});

describe("per-client skill gating", () => {
  it("decides for every client in the catalog — no silent omissions", () => {
    const covered = new Set(clientsWithSkillSupport());
    for (const client of CLIENTS) {
      expect(covered.has(client.id)).toBe(true);
    }
  });

  it("gives clients that load skills a headline and concrete steps", () => {
    for (const id of [
      "claude-code-cli",
      "claude-desktop",
      "claude-ai",
      "codex",
      "gemini-cli",
    ]) {
      const support = skillSupportFor(id);
      expect(support.kind).toBe("supported");
      if (support.kind !== "supported") return;
      expect(support.install.headline.length).toBeGreaterThan(20);
      expect(support.install.steps.length).toBeGreaterThanOrEqual(2);
      for (const step of support.install.steps)
        expect(step.length).toBeGreaterThan(20);
    }
  });

  it("tells a client with no skill loader why, and never offers it a download", () => {
    for (const id of ["grok", "lm-studio"]) {
      const support = skillSupportFor(id);
      expect(support.kind).toBe("unsupported");
      if (support.kind !== "unsupported") return;
      // Truthful and specific, and it always says the memory still works.
      expect(support.reason.length).toBeGreaterThan(80);
      expect(support.reason).toMatch(/still works|memory still/i);
    }
  });

  it("is honest about a client it has not verified", () => {
    const support = skillSupportFor("generic");
    expect(support.kind).toBe("unknown");
    expect(skillSupportFor("something-we-never-heard-of").kind).toBe("unknown");
  });
});

describe("where each Claude client reads skills from (issue 385)", () => {
  it("sends Claude Desktop to the account's skills setting, not to Claude Code's folder", () => {
    const desktop = skillSupportFor("claude-desktop");
    const cli = skillSupportFor("claude-code-cli");
    if (desktop.kind !== "supported" || cli.kind !== "supported")
      throw new Error("expected support");
    expect(desktop.install.steps.join(" ")).not.toContain("~/.claude/skills");
    expect(desktop.install.steps.join(" ")).toContain(
      "Settings → Capabilities → Skills",
    );
    expect(cli.install.steps.join(" ")).toContain("~/.claude/skills");
  });
});
