import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";

import { api } from "../lib/api/client";
import type { InfoResponse } from "../lib/api/client";
import { MODE_LABEL } from "../lib/mode";
import { Sidebar } from "./Sidebar";

afterEach(() => {
  vi.restoreAllMocks();
});

function mount(mode: "locked" | "cloud" | "open" | null) {
  vi.spyOn(api, "info").mockResolvedValue({ channel: "beta" } as unknown as InfoResponse);
  return render(
    <MemoryRouter>
      <Sidebar mode={mode} vaultChangeCount={0} />
    </MemoryRouter>,
  );
}

describe("Sidebar access-mode indicator (issue 343)", () => {
  it.each([
    ["locked", "Your network only", "dot--ok"],
    ["cloud", "Cloud", "dot--ok"],
    ["open", "Open", "dot--warn"],
  ] as const)("shows %s as %s", (mode, label, dot) => {
    mount(mode);

    const indicator = screen.getByTestId("access-mode");
    expect(indicator).toHaveTextContent(label);
    expect(indicator.querySelector(".dot")).toHaveClass(dot);
    expect(MODE_LABEL[mode]).toBe(label);
  });

  it("claims nothing while the mode is still unknown", () => {
    mount(null);

    const indicator = screen.getByTestId("access-mode");
    expect(indicator).not.toHaveTextContent("Your network only");
    expect(indicator.querySelector(".dot")).not.toHaveClass("dot--ok");
  });
});
