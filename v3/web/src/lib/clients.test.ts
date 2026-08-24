import { describe, expect, it } from "vitest";

import { CLIENTS, guidedClients } from "./clients";

describe("client integration catalog", () => {
  it("has one entry per MASTERPLAN §6 client", () => {
    const names = CLIENTS.map((c) => c.name);
    expect(names).toEqual([
      "Claude Code CLI",
      "Codex",
      "Claude Code (Desktop app)",
      "claude.ai",
      "ChatGPT",
      "Antigravity / Gemini CLI",
      "Grok",
      "LM Studio",
      "Any other AI tool",
    ]);
  });

  it("splits into guided and not-yet clients, never leaving a kind unhandled", () => {
    for (const client of CLIENTS) {
      expect(["guided", "notYet"]).toContain(client.kind);
    }
    expect(guidedClients().length).toBeGreaterThan(0);
    expect(guidedClients().every((c) => c.kind === "guided")).toBe(true);
  });

  it("guided clients build a command and a prompt naming the given origin and profile", () => {
    for (const client of guidedClients()) {
      const command = client.command("https://palaia.ts.net", "coding");
      const prompt = client.prompt("https://palaia.ts.net", "coding");
      expect(command).toContain("https://palaia.ts.net/mcp/coding");
      expect(prompt).toContain("https://palaia.ts.net/mcp/coding");
    }
  });

  it("not-yet clients give a mode-aware, truthful reason — never a bare 'unavailable'", () => {
    const claudeAi = CLIENTS.find((c) => c.id === "claude-ai");
    expect(claudeAi?.kind).toBe("notYet");
    if (claudeAi?.kind !== "notYet") throw new Error("expected notYet");

    const lockedReason = claudeAi.reason("locked");
    expect(lockedReason).toMatch(/locked mode/i);
    expect(lockedReason).toMatch(/cloud|open/i);

    // SPEC-205: sign-in now genuinely exists (the OAuth server, SPEC-203)
    // — what remains is turning it on, which this reason must say plainly
    // rather than claiming the whole feature is unbuilt.
    const cloudReason = claudeAi.reason("cloud");
    expect(cloudReason).toMatch(/sign-in/i);
    expect(cloudReason).toMatch(/access mode/i);
    expect(cloudReason).not.toMatch(/phase 2/i);
    expect(cloudReason).not.toBe(lockedReason);
  });

  it("cloud connectors carry an oauthConnect fallback for once sign-in is on", () => {
    for (const id of ["claude-ai", "chatgpt", "grok"]) {
      const client = CLIENTS.find((c) => c.id === id);
      if (client?.kind !== "notYet") throw new Error(`expected ${id} to be notYet`);
      const connect = client.oauthConnect?.("https://hub.example.com", "default");
      expect(connect?.url).toBe("https://hub.example.com/mcp/default");
      expect(connect?.note).toMatch(new RegExp(client.name.replace(".", "\\."), "i"));
    }
  });

  it("Claude Desktop's reason names the MCPB bundle and does not depend on mode", () => {
    const desktop = CLIENTS.find((c) => c.id === "claude-desktop");
    if (desktop?.kind !== "notYet") throw new Error("expected notYet");
    expect(desktop.reason("locked")).toBe(desktop.reason("open"));
    expect(desktop.reason("locked")).toMatch(/mcpb/i);
  });
});
