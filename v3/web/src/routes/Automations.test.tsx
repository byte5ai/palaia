import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ToastProvider } from "../components/Toast";
import type { AutomationInfo, CreatedHook, HookInfo } from "../lib/api/client";
import { api, ApiError } from "../lib/api/client";
import { Automations } from "./Automations";

function mount(path = "/automations") {
  return render(
    <ToastProvider>
      <MemoryRouter initialEntries={[path]}>
        <Automations />
      </MemoryRouter>
    </ToastProvider>,
  );
}

const WEBHOOKS = "/automations?view=webhooks";
const NOT_MOUNTED = new ApiError("/api/automations", 404, undefined);

const ENABLED: AutomationInfo = {
  id: "a1",
  name: "notify me",
  trigger_event: "doctor.finding",
  condition: [],
  action: { kind: "notification", title_template: "x" },
  enabled: true,
  created_at: "2026-08-24T00:00:00Z",
};

const A_HOOK: HookInfo = {
  id: "h1",
  url: "https://example.com/hook",
  events: ["*"],
  enabled: true,
  created_at: "2026-08-24T00:00:00Z",
};

afterEach(() => {
  vi.restoreAllMocks();
});

describe("Automations (SPEC-307, issue 570)", () => {
  it("offers recipes on an empty list; one opens New automation prefilled", async () => {
    vi.spyOn(api, "listAutomations").mockResolvedValue([]);
    vi.spyOn(api, "listHooks").mockRejectedValue(NOT_MOUNTED);
    vi.spyOn(api, "listVaults").mockResolvedValue([]);

    mount();

    expect(await screen.findByText("No automations yet")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /notify me when palaia needs a review/i }));

    const dialog = screen.getByRole("dialog", { name: "New automation" });
    expect(within(dialog).getByDisplayValue(/notify me when palaia needs a review/i)).toBeInTheDocument();
  });

  it("has one primary action, and creates an automation through the dialog", async () => {
    vi.spyOn(api, "listHooks").mockRejectedValue(NOT_MOUNTED);
    vi.spyOn(api, "listVaults").mockResolvedValue([]);
    const listSpy = vi.spyOn(api, "listAutomations").mockResolvedValue([]);
    vi.spyOn(api, "createAutomation").mockResolvedValue(ENABLED);

    mount();
    await screen.findByText("No automations yet");
    expect(document.querySelectorAll(".btn--primary")).toHaveLength(1);

    fireEvent.click(screen.getByRole("button", { name: "New automation" }));
    const dialog = screen.getByRole("dialog", { name: "New automation" });
    fireEvent.change(within(dialog).getByLabelText(/^name$/i), { target: { value: "notify me" } });
    listSpy.mockResolvedValue([ENABLED]);
    fireEvent.click(within(dialog).getByRole("button", { name: /create automation/i }));

    await waitFor(() => expect(api.createAutomation).toHaveBeenCalled());
    expect(await screen.findByText("notify me")).toBeInTheDocument();
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("test-fires an automation and shows the outcome in words", async () => {
    vi.spyOn(api, "listHooks").mockRejectedValue(NOT_MOUNTED);
    vi.spyOn(api, "listAutomations").mockResolvedValue([ENABLED]);
    vi.spyOn(api, "testFireAutomation").mockResolvedValue({
      id: 1,
      automation_id: "a1",
      event_id: "test-1",
      event_name: "doctor.finding",
      status: "delivered",
      attempts: 1,
      last_error: "",
      created_at: "2026-08-24T00:00:00Z",
      test: true,
    });

    mount();
    fireEvent.click(await screen.findByRole("button", { name: /test it/i }));

    expect(await screen.findByText(/test run/i)).toHaveTextContent("Done");
  });

  it("shows the hub's reason when an automation is refused", async () => {
    vi.spyOn(api, "listHooks").mockRejectedValue(NOT_MOUNTED);
    vi.spyOn(api, "listAutomations").mockResolvedValue([]);
    vi.spyOn(api, "listVaults").mockResolvedValue([]);
    vi.spyOn(api, "createAutomation").mockRejectedValue(
      new ApiError("/api/automations", 400, {
        detail: "an automation cannot trigger on 'automation.fired' — loop guard.",
      }),
    );

    mount();
    fireEvent.click(await screen.findByRole("button", { name: "New automation" }));
    const dialog = screen.getByRole("dialog", { name: "New automation" });
    fireEvent.change(within(dialog).getByLabelText(/^name$/i), { target: { value: "x" } });
    fireEvent.click(within(dialog).getByRole("button", { name: /create automation/i }));

    expect(await within(dialog).findByText(/loop guard/i)).toBeInTheDocument();
  });

  it("says plainly when either feature is turned off on this server", async () => {
    vi.spyOn(api, "listHooks").mockRejectedValue(NOT_MOUNTED);
    vi.spyOn(api, "listAutomations").mockRejectedValue(NOT_MOUNTED);

    const { unmount } = mount();
    expect(await screen.findByText("Automations are turned off on this palaia")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "New automation" })).not.toBeInTheDocument();
    unmount();

    mount(WEBHOOKS);
    expect(
      await screen.findByText("Sending events to a server is turned off on this palaia"),
    ).toBeInTheDocument();
  });

  it("adds an address on the Webhooks tab and shows its signing key once", async () => {
    vi.spyOn(api, "listAutomations").mockResolvedValue([]);
    vi.spyOn(api, "listHooks").mockResolvedValue([]);
    const created: CreatedHook = { info: A_HOOK, secret: "shh" };
    const create = vi.spyOn(api, "createHook").mockResolvedValue(created);

    mount(WEBHOOKS);
    expect(await screen.findByText("No addresses yet")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Add address" }));
    const dialog = screen.getByRole("dialog", { name: "Send events to your server" });
    expect(dialog).toHaveTextContent("Leave empty for all events.");
    fireEvent.change(within(dialog).getByLabelText(/address/i), {
      target: { value: "https://example.com/hook" },
    });
    fireEvent.click(within(dialog).getByRole("button", { name: "Add address" }));

    // Empty events = every event: the list is left out, the hub's default.
    await waitFor(() => expect(create).toHaveBeenCalledWith({ url: "https://example.com/hook" }));
    expect(await screen.findByText(/copy its signing key now/i)).toBeInTheDocument();
    expect(screen.getByText("shh")).toBeInTheDocument();
  });

  it("keeps the chosen tab in the address", async () => {
    vi.spyOn(api, "listAutomations").mockResolvedValue([]);
    vi.spyOn(api, "listHooks").mockResolvedValue([A_HOOK]);

    mount();
    fireEvent.click(await screen.findByRole("tab", { name: "Webhooks" }));

    expect(await screen.findByText("https://example.com/hook")).toBeInTheDocument();
    expect(screen.getByText("All events")).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "Webhooks" })).toHaveAttribute("aria-selected", "true");
  });
});

describe("Automations — failures are shown, never swallowed (issues 376, 377, 378)", () => {
  it("renders the hub's own words when an address is refused, not [object Object]", async () => {
    vi.spyOn(api, "listAutomations").mockResolvedValue([]);
    vi.spyOn(api, "listHooks").mockResolvedValue([]);
    vi.spyOn(api, "createHook").mockRejectedValue(
      new ApiError("/api/hooks", 400, { detail: "The address must start with https://." }),
    );

    mount(WEBHOOKS);
    fireEvent.click(await screen.findByRole("button", { name: "Add address" }));
    const dialog = screen.getByRole("dialog");
    fireEvent.change(within(dialog).getByLabelText(/address/i), {
      target: { value: "http://example.com/hook" },
    });
    fireEvent.click(within(dialog).getByRole("button", { name: "Add address" }));

    expect(await screen.findByText(/the address must start with https/i)).toBeInTheDocument();
    expect(screen.queryByText(/\[object Object\]/)).not.toBeInTheDocument();
  });

  it("tells the person when turning an automation off is refused", async () => {
    vi.spyOn(api, "listHooks").mockRejectedValue(NOT_MOUNTED);
    vi.spyOn(api, "listAutomations").mockResolvedValue([ENABLED]);
    vi.spyOn(api, "setAutomationEnabled").mockRejectedValue(
      new ApiError("/api/automations/a1", 403, {
        detail: "Your sign-in changed in another tab — reload this page.",
      }),
    );

    mount();
    fireEvent.click(await screen.findByRole("switch", { name: "notify me" }));

    expect(await screen.findByText(/your sign-in changed/i)).toBeInTheDocument();
  });

  it("says when the automations cannot be loaded — never as an empty list — and retries", async () => {
    vi.spyOn(api, "listHooks").mockRejectedValue(NOT_MOUNTED);
    const list = vi
      .spyOn(api, "listAutomations")
      .mockRejectedValue(new ApiError("/api/automations", 500, { detail: "store is locked" }));

    mount();

    expect(await screen.findByRole("alert")).toHaveTextContent("Couldn't load your automations");
    expect(screen.getByText("store is locked")).toBeInTheDocument();
    expect(screen.queryByText("No automations yet")).not.toBeInTheDocument();
    list.mockResolvedValue([ENABLED]);
    fireEvent.click(screen.getByRole("button", { name: /try again/i }));
    expect(await screen.findByText("notify me")).toBeInTheDocument();
  });

  it("deletes an automation only after confirming", async () => {
    vi.spyOn(api, "listHooks").mockRejectedValue(NOT_MOUNTED);
    vi.spyOn(api, "listAutomations").mockResolvedValue([ENABLED]);
    const remove = vi.spyOn(api, "deleteAutomation").mockResolvedValue(undefined);

    mount();
    fireEvent.click(await screen.findByRole("button", { name: "Delete" }));
    expect(remove).not.toHaveBeenCalled();
    const dialog = screen.getByRole("dialog", { name: "Delete notify me?" });
    fireEvent.click(within(dialog).getByRole("button", { name: "Delete automation" }));

    await waitFor(() => expect(remove).toHaveBeenCalledWith("a1"));
  });
});

/**
 * SPEC-307 acceptance criterion #6: "jargon lint on all screen copy".
 * principles §0.1 — no protocol name, standard, acronym, transport or
 * implementation word in a label, heading, button, pill or option name; the
 * technical term may still live in hint text or a `title` attribute.
 */
describe("Automations copy — no jargon in the surface (system.md §3)", () => {
  const BANNED = [
    /\bwebhook\b/i,
    /\bhmac\b/i,
    /\bjson\b/i,
    /\bsqlite\b/i,
    /\basgi\b/i,
    /\brest\b/i,
    /\burl\b/i,
    /\bapi\b/i,
    /\bhttp\b/i,
    /\bnamespace\b/i,
    /\bvault\b/i,
    /\bclient\b/i,
    /\bcurator\b/i,
  ];

  function scan() {
    const controls = [
      ...screen.queryAllByRole("heading"),
      ...screen.queryAllByRole("button"),
      ...screen.queryAllByRole("option"),
      ...Array.from(document.querySelectorAll(".pill, .badge, .card__title, .card__subject, .field__label")),
    ];
    expect(controls.length).toBeGreaterThan(5);
    for (const element of controls) {
      const text = element.textContent ?? "";
      for (const pattern of BANNED) {
        expect(text).not.toMatch(pattern);
      }
    }
  }

  it("on the list, in the New automation dialog, and in every action's fields", async () => {
    vi.spyOn(api, "listAutomations").mockResolvedValue([]);
    vi.spyOn(api, "listHooks").mockResolvedValue([]);
    vi.spyOn(api, "listVaults").mockResolvedValue([]);

    mount();
    await screen.findByText("No automations yet");
    scan();

    fireEvent.click(screen.getByRole("button", { name: "New automation" }));
    const dialog = screen.getByRole("dialog");
    fireEvent.click(within(dialog).getByRole("button", { name: /add a condition/i }));
    scan();
    const then = within(dialog).getByLabelText("Then");
    for (const kind of ["memory_write", "stash_set", "notification"]) {
      fireEvent.change(then, { target: { value: kind } });
      scan();
    }
  });

  it("on the Webhooks tab and its dialog", async () => {
    vi.spyOn(api, "listAutomations").mockResolvedValue([]);
    vi.spyOn(api, "listHooks").mockResolvedValue([A_HOOK]);

    mount(WEBHOOKS);
    await screen.findByText("https://example.com/hook");
    fireEvent.click(screen.getByRole("button", { name: "Add address" }));
    scan();
  });
});
