import { describe, expect, it } from "vitest";

import { CLIENTS } from "./clients";
import {
  clientsWithSkillSupport,
  frontmatterValue,
  SKILLS,
  skillBySlug,
  skillSupportFor,
} from "./skills";

describe("skill catalog", () => {
  it("carries both SPEC-207 packages, read from the shipped files", () => {
    expect(SKILLS.map((s) => s.slug)).toEqual(["palaia-memory", "palaia-capture"]);
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
    for (const id of ["claude-code-cli", "claude-desktop", "claude-ai", "codex", "gemini-cli"]) {
      const support = skillSupportFor(id);
      expect(support.kind).toBe("supported");
      if (support.kind !== "supported") return;
      expect(support.install.headline.length).toBeGreaterThan(20);
      expect(support.install.steps.length).toBeGreaterThanOrEqual(2);
      for (const step of support.install.steps) expect(step.length).toBeGreaterThan(20);
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
