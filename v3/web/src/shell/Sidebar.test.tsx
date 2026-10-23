import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";

import { api } from "../lib/api/client";
import type { InfoResponse } from "../lib/api/client";
import type { HubHealth } from "../lib/health";
import { MODE_LABEL } from "../lib/mode";
import { Sidebar } from "./Sidebar";

afterEach(() => {
  vi.restoreAllMocks();
});

const RUNNING: HubHealth = { tone: "ok", label: "Running" };

function mount(mode: "locked" | "cloud" | "open" | null, health: HubHealth = RUNNING) {
  vi.spyOn(api, "info").mockResolvedValue({ channel: "beta" } as unknown as InfoResponse);
  return render(
    <MemoryRouter>
      <Sidebar mode={mode} health={health} vaultChangeCount={0} />
    </MemoryRouter>,
  );
}

describe("Sidebar status (issue 343)", () => {
  it.each([
    ["locked", "Private"],
    ["cloud", "Cloud"],
    ["open", "Public"],
  ] as const)("shows the running %s mode as %s", (mode, label) => {
    mount(mode);

    const indicator = screen.getByTestId("access-mode");
    expect(indicator).toHaveTextContent(`Running · ${label}`);
    expect(indicator.querySelector(".dot")).toHaveClass("dot--ok");
    expect(MODE_LABEL[mode]).toBe(label);
  });

  it("claims no mode while it is still unknown", () => {
    mount(null);

    const indicator = screen.getByTestId("access-mode");
    expect(indicator).toHaveTextContent(/^Running$/);
  });

  it("says when palaia can't be reached, in the error colour, without a mode", () => {
    mount("locked", { tone: "error", label: "Can't reach palaia" });

    const indicator = screen.getByTestId("access-mode");
    expect(indicator).toHaveTextContent(/^Can't reach palaia$/);
    expect(indicator.querySelector(".dot")).toHaveClass("dot--error");
  });
});

describe("Sidebar destinations (#570)", () => {
  it("offers five places and Settings, in that order", () => {
    mount("locked");

    const primary = screen.getByRole("navigation", { name: "Primary" });
    const links = Array.from(primary.querySelectorAll("a")).map((a) => [
      a.textContent,
      a.getAttribute("href"),
    ]);
    expect(links).toEqual([
      ["Overview", "/"],
      ["Memories", "/memories"],
      ["AI apps", "/apps"],
      ["Add-ons", "/add-ons"],
      ["Automations", "/automations"],
      ["Settings", "/settings"],
    ]);
  });
});
