import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { SkillPanel } from "./SkillPanel";
import { ToastProvider } from "./Toast";

function mount(clientId: string, clientName = "Test Client") {
  return render(
    <ToastProvider>
      <SkillPanel clientId={clientId} clientName={clientName} />
    </ToastProvider>,
  );
}

function disclosure(summary: string): HTMLDetailsElement {
  return screen.getByText(summary, { selector: "summary" }).closest("details")!;
}

describe("SkillPanel", () => {
  it("recommends the palaia skill, collapsed, with install steps for an app that loads skills", () => {
    mount("claude-code-cli", "Claude Code CLI");

    expect(screen.getByText("Recommended: install the palaia skill")).toBeInTheDocument();
    expect(
      screen.getByText("Teaches Claude Code CLI to look things up before answering and to save decisions."),
    ).toBeInTheDocument();
    const install = disclosure("Install skill");
    expect(install.open).toBe(false);
    expect(install).toHaveTextContent("palaia-memory");
    expect(install).toHaveTextContent("--plugin-dir");
  });

  it("puts the other skills under More skills", () => {
    mount("claude-code-cli");

    const more = disclosure("More skills");
    expect(more.open).toBe(false);
    expect(more).toHaveTextContent("palaia-capture");
    expect(more).toHaveTextContent("palaia-messenger");
    expect(more).not.toHaveTextContent("palaia-memory");
    expect(screen.getAllByRole("link", { name: /download skill\.md/i })).toHaveLength(3);
  });

  it("keeps the skill's real text, frontmatter and all, one click away", () => {
    mount("claude-code-cli");

    expect(screen.getAllByText("Show the skill text", { selector: "summary" })).toHaveLength(3);
    expect(screen.getByText(/name: palaia-memory/)).toBeInTheDocument();
  });

  it("explains itself instead of offering a download an app cannot use", () => {
    mount("lm-studio", "LM Studio");

    expect(screen.getByText("Not available")).toBeInTheDocument();
    expect(screen.getByText(/not a skill loader/i)).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: /download skill\.md/i })).toBeNull();
    expect(screen.queryByText("palaia-memory")).toBeNull();
  });

  it("is honest about an app whose skill support is unverified", () => {
    mount("generic", "Any other AI tool");

    expect(screen.getByText(/if your tool reads skill\.md folders/i)).toBeInTheDocument();
    // Unverified is not unsupported: the files are still offered.
    expect(screen.getAllByRole("link", { name: /download skill\.md/i })).toHaveLength(3);
  });
});
