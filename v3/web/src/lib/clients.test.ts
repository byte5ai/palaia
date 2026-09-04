import { describe, expect, it } from "vitest";

import { CLIENTS, CODEX_TOKEN_ENV, TOKEN_PLACEHOLDER, guidedClients } from "./clients";

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

  it("splits into guided, download, and not-yet clients, never leaving a kind unhandled", () => {
    for (const client of CLIENTS) {
      expect(["guided", "download", "notYet"]).toContain(client.kind);
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

  // Issue 318: every mounted profile refuses a tokenless call, so every
  // snippet must carry the token — in the mechanism each client really
  // uses (v3/docs/client-matrix-results.md §2.1, §3, §7.2).
  describe("guided snippets carry the token (issue 318)", () => {
    const origin = "https://palaia.ts.net";
    const profile = "coding";
    const token = "plt_test_secret";
    const url = `${origin}/mcp/${profile}`;
    const guided = (id: string) => {
      const client = CLIENTS.find((c) => c.id === id);
      if (client?.kind !== "guided") throw new Error(`expected ${id} to be guided`);
      return client;
    };

    it("Claude Code CLI attaches it with --header, the literal form the matrix ran", () => {
      expect(guided("claude-code-cli").command(origin, profile, token)).toBe(
        `claude mcp add --transport http palaia ${url} --header "Authorization: Bearer ${token}"`,
      );
    });

    it("Codex exports it to the variable bearer_token_env_var names, on the command and in the file", () => {
      const codex = guided("codex");
      const command = codex.command(origin, profile, token);
      expect(command).toContain(`export ${CODEX_TOKEN_ENV}=${token}`);
      expect(command).toContain(`codex mcp add palaia --url ${url} --bearer-token-env-var ${CODEX_TOKEN_ENV}`);
      const file = codex.configFile?.(origin, profile, token);
      expect(file?.content).toContain(`bearer_token_env_var = "${CODEX_TOKEN_ENV}"`);
      expect(file?.content).toContain(`export ${CODEX_TOKEN_ENV}=${token}`);
    });

    it("Gemini CLI and LM Studio carry it in their config's headers object", () => {
      for (const id of ["gemini-cli", "lm-studio"]) {
        const client = guided(id);
        const parsed = JSON.parse(client.configFile?.(origin, profile, token)?.content ?? "{}");
        expect(parsed.mcpServers.palaia.headers, id).toEqual({ Authorization: `Bearer ${token}` });
        // The command tab is the same object, minus the file's outer shape.
        expect(client.command(origin, profile, token), id).toContain(
          `"headers": {"Authorization": "Bearer ${token}"}`,
        );
      }
    });

    it("the generic entry and every prompt name the header outright", () => {
      expect(guided("generic").command(origin, profile, token)).toBe(
        `${url}\nAuthorization: Bearer ${token}`,
      );
      for (const client of guidedClients()) {
        expect(client.prompt(origin, profile, token), client.id).toContain(
          `"Authorization: Bearer ${token}"`,
        );
      }
    });

    it("renders the placeholder, never a tokenless snippet, when no token is known", () => {
      for (const client of guidedClients()) {
        for (const text of [
          client.command(origin, profile),
          client.prompt(origin, profile),
          client.configFile?.(origin, profile)?.content ?? TOKEN_PLACEHOLDER,
        ]) {
          expect(text, client.id).toContain(TOKEN_PLACEHOLDER);
        }
        // ...and the real token replaces the placeholder in place of it.
        expect(client.command(origin, profile, token), client.id).not.toContain(TOKEN_PLACEHOLDER);
        expect(client.prompt(origin, profile, token), client.id).not.toContain(TOKEN_PLACEHOLDER);
      }
    });
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

  it("Claude Desktop is a real one-click download, naming a real per-profile URL", () => {
    const desktop = CLIENTS.find((c) => c.id === "claude-desktop");
    if (desktop?.kind !== "download") throw new Error("expected download");
    const url = desktop.downloadUrl("https://hub.example.com", "coding");
    expect(url).toContain("https://hub.example.com/api/connect/mcpb");
    expect(url).toContain("profile=coding");
  });

  it("Codex, Gemini CLI and LM Studio each offer a real, parseable config file", () => {
    const origin = "https://hub.example.com";
    const profile = "coding";

    const codex = CLIENTS.find((c) => c.id === "codex");
    if (codex?.kind !== "guided") throw new Error("expected guided");
    const codexFile = codex.configFile?.(origin, profile);
    expect(codexFile?.filename).toMatch(/\.toml$/);
    expect(codexFile?.content).toContain("[mcp_servers.palaia]");
    expect(codexFile?.content).toContain(`${origin}/mcp/${profile}`);

    const gemini = CLIENTS.find((c) => c.id === "gemini-cli");
    if (gemini?.kind !== "guided") throw new Error("expected guided");
    const geminiFile = gemini.configFile?.(origin, profile);
    expect(geminiFile?.filename).toMatch(/\.json$/);
    const geminiParsed = JSON.parse(geminiFile?.content ?? "{}");
    expect(geminiParsed.mcpServers.palaia.httpUrl).toBe(`${origin}/mcp/${profile}`);

    const lmStudio = CLIENTS.find((c) => c.id === "lm-studio");
    if (lmStudio?.kind !== "guided") throw new Error("expected guided");
    const lmStudioFile = lmStudio.configFile?.(origin, profile);
    expect(lmStudioFile?.filename).toMatch(/\.json$/);
    const lmStudioParsed = JSON.parse(lmStudioFile?.content ?? "{}");
    expect(lmStudioParsed.mcpServers.palaia).toEqual({
      type: "streamable-http",
      url: `${origin}/mcp/${profile}`,
      headers: { Authorization: `Bearer ${TOKEN_PLACEHOLDER}` },
    });
  });

  it("no user-facing catalog string uses protocol jargon (system.md §3 rule 0)", () => {
    const BANNED = [
      /\boidc\b/i,
      /\boauth\b/i,
      /\bjwt\b/i,
      /\bpkce\b/i,
      /\bcimd\b/i,
      /\bdcr\b/i,
      /\bmcpb\b/i,
      /\bstdio\b/i,
      /\bbearer\b/i,
    ];
    // A command or prompt is not a label (system.md §3 rule 0 governs
    // labels, headings, buttons, badges, status lines and option names):
    // it is the technical text itself, shown inside a code block, and the
    // header the hub requires is literally `Authorization: Bearer …`
    // (issue 318) — the one place the word has to appear verbatim.
    const BANNED_IN_SNIPPETS = BANNED.filter((pattern) => pattern.source !== "\\bbearer\\b");
    const origin = "https://hub.example.com";
    const profile = "default";
    for (const client of CLIENTS) {
      const strings: string[] = [client.name];
      const snippets: string[] = [];
      if (client.kind === "guided") {
        strings.push(client.estimate);
        snippets.push(client.command(origin, profile), client.prompt(origin, profile));
      } else if (client.kind === "download") {
        strings.push(client.subtitle);
      } else {
        strings.push(client.subtitle, client.reason("cloud"), client.reason("locked"));
      }
      for (const text of strings) {
        for (const pattern of BANNED) {
          expect(text, `jargon ${pattern} in ${client.id}: ${text}`).not.toMatch(pattern);
        }
      }
      for (const text of snippets) {
        for (const pattern of BANNED_IN_SNIPPETS) {
          expect(text, `jargon ${pattern} in ${client.id}: ${text}`).not.toMatch(pattern);
        }
      }
    }
  });
});
