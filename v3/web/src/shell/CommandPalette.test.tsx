import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import axe from "axe-core";
import { MemoryRouter, useLocation } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import App from "../App";
import type { SearchHit, VaultSummary } from "../lib/api/client";
import { api } from "../lib/api/client";
import { matchesQuery, notePath } from "../lib/palette";
import { ThemeProvider } from "../lib/theme";
import { CommandPalette } from "./CommandPalette";

function vault(key: string): VaultSummary {
  return { key, purpose: "", path: `/${key}`, writable: true, note_count: 1 };
}

function hit(permalink: string, title: string, score: number): SearchHit {
  return { permalink, title, snippet: "", score };
}

function Where() {
  const location = useLocation();
  return <output data-testid="where">{location.pathname + location.search}</output>;
}

function mount(props: { onClose?: () => void; onSignOut?: () => void } = {}) {
  const onClose = props.onClose ?? vi.fn();
  render(
    <ThemeProvider>
      <MemoryRouter initialEntries={["/add-ons"]}>
        <Where />
        <CommandPalette open onClose={onClose} onSignOut={props.onSignOut} />
      </MemoryRouter>
    </ThemeProvider>,
  );
  return { onClose, field: screen.getByRole("combobox", { name: "Search or jump to" }) };
}

const options = () => screen.getAllByRole("option").map((option) => option.textContent);
const selected = () => screen.getByRole("option", { selected: true });

beforeEach(() => {
  vi.spyOn(api, "listVaults").mockResolvedValue([vault("work"), vault("home")]);
});

afterEach(() => {
  vi.restoreAllMocks();
  document.documentElement.removeAttribute("data-theme");
  window.localStorage.clear();
});

describe("the command palette", () => {
  it("lists the main places before anything is typed, the first one highlighted", () => {
    const { field } = mount();

    const places = within(screen.getByRole("group", { name: "Go to" })).getAllByRole("option");
    expect(places.map((option) => option.textContent)).toEqual([
      "Overview",
      "Memories",
      "Needs review",
      "AI apps",
      "Live sessions",
      "Add-ons",
      "Automations",
      "Settings",
    ]);
    expect(field).toHaveFocus();
    expect(selected()).toHaveTextContent("Overview");
    expect(field).toHaveAttribute("aria-activedescendant", selected().id);
  });

  it("moves with the arrow keys and opens the highlighted place with Enter", () => {
    const { field, onClose } = mount();

    fireEvent.keyDown(field, { key: "ArrowDown" });
    fireEvent.keyDown(field, { key: "ArrowDown" });
    fireEvent.keyDown(field, { key: "ArrowUp" });
    expect(selected()).toHaveTextContent("Memories");
    fireEvent.keyDown(field, { key: "Enter" });

    expect(screen.getByTestId("where")).toHaveTextContent("/memories");
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("finds a Settings area by what people call it", () => {
    const { field } = mount();

    fireEvent.change(field, { target: { value: "restore" } });
    expect(options()).toEqual(["Settings: Backups"]);
    fireEvent.keyDown(field, { key: "Enter" });

    expect(screen.getByTestId("where")).toHaveTextContent("/settings/backups");
  });

  it("offers to connect an AI app and opens that app's panel", () => {
    const { field } = mount();

    fireEvent.change(field, { target: { value: "connect codex" } });
    fireEvent.click(screen.getByRole("option", { name: "Connect Codex" }));

    expect(screen.getByTestId("where")).toHaveTextContent("/apps?app=codex");
  });

  it("searches the notes of every memory, best match first, and opens one in its memory", async () => {
    const search = vi.spyOn(api, "search").mockImplementation(async (memory) =>
      memory === "work"
        ? [hit("projects/billing", "Billing service", 0.4)]
        : [hit("money/billing", "Billing at home", 0.9)],
    );
    const { field } = mount();

    fireEvent.change(field, { target: { value: "billing" } });

    const notes = within(await screen.findByRole("group", { name: "Notes" })).getAllByRole("option");
    expect(notes.map((option) => option.textContent)).toEqual(["Billing at homehome", "Billing servicework"]);
    expect(search.mock.calls.map((call) => [call[0], call[1]])).toEqual([
      ["work", "billing"],
      ["home", "billing"],
    ]);

    fireEvent.click(notes[1]);
    expect(screen.getByTestId("where")).toHaveTextContent("/memories?memory=work&note=projects%2Fbilling");
  });

  it("does not search notes for a single letter", async () => {
    const search = vi.spyOn(api, "search").mockResolvedValue([]);
    const { field } = mount();

    fireEvent.change(field, { target: { value: "b" } });
    await new Promise((resolve) => setTimeout(resolve, 400));

    expect(search).not.toHaveBeenCalled();
  });

  it("says so when nothing matches, and when the notes could not be searched", async () => {
    const search = vi.spyOn(api, "search").mockResolvedValue([]);
    const { field } = mount();

    fireEvent.change(field, { target: { value: "zzzz" } });
    expect(await screen.findByText("Nothing matches “zzzz”.")).toBeInTheDocument();

    search.mockRejectedValue(new Error("the disk is on fire"));
    fireEvent.change(field, { target: { value: "zzzzy" } });
    expect(await screen.findByText(/Notes could not be searched\. Can't reach palaia/)).toBeInTheDocument();
  });

  it("switches the appearance and offers the two other modes afterwards", () => {
    const { field } = mount();

    fireEvent.change(field, { target: { value: "appearance" } });
    const actions = within(screen.getByRole("group", { name: "Actions" })).getAllByRole("option");
    expect(actions.map((option) => option.textContent)).toEqual(["Use the light appearance", "Use the dark appearance"]);
    fireEvent.click(screen.getByRole("option", { name: "Use the dark appearance" }));

    expect(document.documentElement).toHaveAttribute("data-theme", "dark");
  });

  it("offers Sign out only when someone is signed in", () => {
    const onSignOut = vi.fn();
    const { field } = mount({ onSignOut });

    fireEvent.change(field, { target: { value: "log out" } });
    fireEvent.keyDown(field, { key: "Enter" });

    expect(onSignOut).toHaveBeenCalledTimes(1);
  });

  it("closes with Escape and keeps Tab inside", () => {
    const { field, onClose } = mount();

    expect(fireEvent.keyDown(field, { key: "Tab" })).toBe(false);
    expect(onClose).not.toHaveBeenCalled();
    fireEvent.keyDown(field, { key: "Escape" });

    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("has no serious accessibility violations with results on screen", async () => {
    vi.spyOn(api, "search").mockResolvedValue([hit("projects/billing", "Billing service", 0.4)]);
    const { field } = mount();
    fireEvent.change(field, { target: { value: "se" } });
    await screen.findByRole("group", { name: "Notes" });

    const results = await axe.run(document.body, { rules: { "color-contrast": { enabled: false } } });

    expect(
      results.violations
        .filter((violation) => violation.impact === "critical" || violation.impact === "serious")
        .map((violation) => `${violation.id}: ${violation.nodes.map((node) => node.html).join(" | ")}`),
    ).toEqual([]);
  });
});

describe("matching", () => {
  it("needs every word, in the label or the keywords, in any case", () => {
    const command = { label: "Settings: Backups", keywords: "download restore" };

    expect(matchesQuery(command, "SET restore")).toBe(true);
    expect(matchesQuery(command, "restore telegram")).toBe(false);
  });

  it("encodes the memory and the note into the link", () => {
    expect(notePath("my work", "a/b c")).toBe("/memories?memory=my%20work&note=a%2Fb%20c");
  });
});

describe("opening the palette from the shell", () => {
  const palette = () => screen.queryByRole("dialog", { name: "Search or jump to" });

  it("opens and closes with Ctrl+K and with ⌘K, and gives the focus back", async () => {
    render(<App />);
    const trigger = await screen.findByRole("button", { name: "Search or jump to" });
    trigger.focus();

    fireEvent.keyDown(window, { key: "k", ctrlKey: true });
    expect(palette()).toBeInTheDocument();
    fireEvent.keyDown(window, { key: "k", metaKey: true });
    expect(palette()).not.toBeInTheDocument();
    await waitFor(() => expect(trigger).toHaveFocus());
  });

  it("opens from the sidebar field", async () => {
    render(<App />);

    fireEvent.click(await screen.findByRole("button", { name: "Search or jump to" }));

    expect(palette()).toBeInTheDocument();
  });

  it("opens with / unless the key is typed into a field", async () => {
    render(<App />);
    await screen.findByRole("button", { name: "Search or jump to" });
    const field = document.createElement("input");
    document.body.append(field);

    fireEvent.keyDown(field, { key: "/" });
    expect(palette()).not.toBeInTheDocument();
    fireEvent.keyDown(document.body, { key: "/" });
    expect(palette()).toBeInTheDocument();

    field.remove();
  });
});
