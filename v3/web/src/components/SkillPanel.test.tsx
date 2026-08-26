import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { ToastProvider } from "./Toast";
import { SkillPanel } from "./SkillPanel";

function mount(clientId: string, clientName = "Test Client") {
  return render(
    <ToastProvider>
      <SkillPanel clientId={clientId} clientName={clientName} />
    </ToastProvider>,
  );
}

describe("SkillPanel", () => {
  it("offers every skill with install steps to a client that loads them", () => {
    mount("claude-code-cli", "Claude Code CLI");

    expect(screen.getByText(/teaching it to use the memory/i)).toBeInTheDocument();
    expect(screen.getByText("palaia-memory")).toBeInTheDocument();
    expect(screen.getByText("palaia-capture")).toBeInTheDocument();
    expect(screen.getByText("palaia-messenger")).toBeInTheDocument();
    expect(screen.getAllByRole("link", { name: /download skill\.md/i })).toHaveLength(3);
    expect(screen.getByText(/--plugin-dir/)).toBeInTheDocument();
  });

  it("shows the skill's real text on request, frontmatter and all", () => {
    mount("claude-code-cli");

    fireEvent.click(screen.getAllByRole("button", { name: /read it first/i })[0]!);
    expect(screen.getByText(/name: palaia-memory/)).toBeInTheDocument();
  });

  it("explains itself instead of offering a download a client cannot use", () => {
    mount("lm-studio", "LM Studio");

    expect(screen.getByText(/not applicable/i)).toBeInTheDocument();
    expect(screen.getByText(/not a skill loader/i)).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: /download skill\.md/i })).toBeNull();
    expect(screen.queryByText("palaia-memory")).toBeNull();
  });

  it("is honest about a client whose skill support is unverified", () => {
    mount("generic", "Any other AI tool");

    expect(screen.getByText(/if your tool reads skill\.md folders/i)).toBeInTheDocument();
    // Unverified is not unsupported: the files are still offered.
    expect(screen.getAllByRole("link", { name: /download skill\.md/i })).toHaveLength(3);
  });
});
