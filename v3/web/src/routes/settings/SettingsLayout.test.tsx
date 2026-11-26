import { render, screen, within } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { describe, expect, it } from "vitest";

import { routes } from "../index";
import { SETTINGS_AREAS } from "./settingsAreas";
import { SettingsLayout } from "./SettingsLayout";

function mount(at: string) {
  return render(
    <MemoryRouter initialEntries={[at]}>
      <Routes>
        <Route path="/settings" element={<SettingsLayout />}>
          <Route index element={<p>general area</p>} />
          <Route path="backups" element={<p>backups area</p>} />
        </Route>
      </Routes>
    </MemoryRouter>,
  );
}

describe("Settings navigation", () => {
  it("lists every area and marks the open one", () => {
    mount("/settings/backups");

    const nav = screen.getByRole("navigation", { name: "Settings" });
    expect(within(nav).getAllByRole("link").map((link) => link.textContent)).toEqual(
      SETTINGS_AREAS.map((area) => area.label),
    );
    expect(within(nav).getByRole("link", { name: "Backups" })).toHaveAttribute("aria-current", "page");
    // "General" is /settings itself and must not read as open on a sub-page.
    expect(within(nav).getByRole("link", { name: "General" })).not.toHaveAttribute("aria-current");
    expect(screen.getByText("backups area")).toBeInTheDocument();
  });

  it("has a navigation entry for every settings route, and no entry without one", () => {
    const shell = routes.find((route) => route.path === "/")!;
    const settings = shell.children![0]!.children!.find((route) => route.path === "settings")!;
    const paths = settings.children!.map((child) => (child.index ? "/settings" : `/settings/${child.path}`));

    expect(SETTINGS_AREAS.map((area) => area.to).sort()).toEqual(paths.sort());
  });
});
