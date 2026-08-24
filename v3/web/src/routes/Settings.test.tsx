import { render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { Settings } from "./Settings";

function mockInfoResponse(signIn: { method: string; provider_name: string | null }) {
  vi.spyOn(globalThis, "fetch").mockResolvedValue(
    new Response(
      JSON.stringify({ version: "0.0.0", mode: "cloud", uptime_seconds: 1, sign_in: signIn }),
      { status: 200, headers: { "Content-Type": "application/json" } },
    ),
  );
}

describe("Settings (SPEC-204 deliverable #4)", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("shows plain-language copy for an IdP-backed sign-in, no protocol jargon", async () => {
    mockInfoResponse({ method: "idp", provider_name: "GitHub" });
    render(<Settings />);

    expect(await screen.findByText(/sign in with github/i)).toBeInTheDocument();

    // The jargon rule (MASTERPLAN §5.5): no protocol acronym ever reaches
    // the person reading this page.
    const forbidden = ["oidc", "idp", "sso", "openid connect", "oauth"];
    const text = document.body.textContent?.toLowerCase() ?? "";
    for (const term of forbidden) {
      expect(text, `jargon leaked into settings copy: ${term}`).not.toContain(term);
    }
  });

  it("shows plain-language copy for a generic provider's display name", async () => {
    mockInfoResponse({ method: "idp", provider_name: "Example Workspace" });
    render(<Settings />);

    expect(await screen.findByText(/sign in with example workspace/i)).toBeInTheDocument();
  });

  it("shows the password door when no IdP is configured", async () => {
    mockInfoResponse({ method: "password", provider_name: null });
    render(<Settings />);

    expect(await screen.findByText(/sign in with a password/i)).toBeInTheDocument();
  });

  it("is honest when nothing is configured yet", async () => {
    mockInfoResponse({ method: "none", provider_name: null });
    render(<Settings />);

    expect(await screen.findByText(/no sign-in configured/i)).toBeInTheDocument();
  });
});
