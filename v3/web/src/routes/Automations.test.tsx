import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ToastProvider } from "../components/Toast";
import type { AutomationInfo, CreatedHook } from "../lib/api/client";
import { api, ApiError } from "../lib/api/client";
import { Automations } from "./Automations";

function mount() {
  return render(
    <ToastProvider>
      <Automations />
    </ToastProvider>,
  );
}

const NOT_MOUNTED = new ApiError("/api/automations", 404, undefined);

afterEach(() => {
  vi.restoreAllMocks();
});

describe("Automations screen (SPEC-307)", () => {
  it("offers recipes on the empty screen and prefills the form on click", async () => {
    vi.spyOn(api, "listAutomations").mockResolvedValue([]);
    vi.spyOn(api, "listHooks").mockRejectedValue(NOT_MOUNTED);

    mount();

    const recipe = await screen.findByText(/notify me when the curator needs a review/i);
    fireEvent.click(recipe);

    expect(screen.getByDisplayValue(/notify me when the curator needs a review/i)).toBeInTheDocument();
  });

  it("creates an automation through the form and lists it", async () => {
    vi.spyOn(api, "listHooks").mockRejectedValue(NOT_MOUNTED);
    const listSpy = vi.spyOn(api, "listAutomations").mockResolvedValue([]);
    const created: AutomationInfo = {
      id: "a1",
      name: "notify me",
      trigger_event: "doctor.finding",
      condition: [],
      action: { kind: "notification", title_template: "x" },
      enabled: true,
      created_at: "2026-08-24T00:00:00Z",
    };
    vi.spyOn(api, "createAutomation").mockResolvedValue(created);

    mount();
    await screen.findByText(/try one of these/i);

    fireEvent.change(screen.getByLabelText(/^name$/i), { target: { value: "notify me" } });
    listSpy.mockResolvedValue([created]);
    fireEvent.click(screen.getByRole("button", { name: /create automation/i }));

    await waitFor(() => expect(api.createAutomation).toHaveBeenCalled());
    expect(await screen.findByText("notify me")).toBeInTheDocument();
  });

  it("test-fires an automation and shows the outcome", async () => {
    vi.spyOn(api, "listHooks").mockRejectedValue(NOT_MOUNTED);
    const automation: AutomationInfo = {
      id: "a1",
      name: "notify me",
      trigger_event: "doctor.finding",
      condition: [],
      action: { kind: "notification", title_template: "x" },
      enabled: true,
      created_at: "2026-08-24T00:00:00Z",
    };
    vi.spyOn(api, "listAutomations").mockResolvedValue([automation]);
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
    fireEvent.click(await screen.findByRole("button", { name: /test this automation/i }));

    expect(await screen.findByText(/delivered/i)).toBeInTheDocument();
  });

  it("shows a plain-language error when the trigger is loop-guarded", async () => {
    vi.spyOn(api, "listHooks").mockRejectedValue(NOT_MOUNTED);
    vi.spyOn(api, "listAutomations").mockResolvedValue([]);
    vi.spyOn(api, "createAutomation").mockRejectedValue(
      new ApiError("/api/automations", 400, {
        detail: "an automation cannot trigger on 'automation.fired' — loop guard.",
      }),
    );

    mount();
    await screen.findByText(/try one of these/i);
    fireEvent.change(screen.getByLabelText(/^name$/i), { target: { value: "x" } });
    fireEvent.click(screen.getByRole("button", { name: /create automation/i }));

    expect(await screen.findByText(/loop guard/i)).toBeInTheDocument();
  });

  it("degrades gracefully when neither surface is mounted on this hub", async () => {
    vi.spyOn(api, "listHooks").mockRejectedValue(NOT_MOUNTED);
    vi.spyOn(api, "listAutomations").mockRejectedValue(NOT_MOUNTED);

    mount();

    expect(
      await screen.findByText(/this hub has no automations store mounted/i),
    ).toBeInTheDocument();
    expect(screen.getByText(/this hub has no webhook store mounted/i)).toBeInTheDocument();
  });

  it("still shows the outside-address form once a hook is created", async () => {
    vi.spyOn(api, "listAutomations").mockResolvedValue([]);
    vi.spyOn(api, "listHooks").mockResolvedValue([]);
    const created: CreatedHook = {
      info: {
        id: "h1",
        url: "https://example.com/hook",
        events: ["*"],
        enabled: true,
        created_at: "2026-08-24T00:00:00Z",
      },
      secret: "shh",
    };
    vi.spyOn(api, "createHook").mockResolvedValue(created);

    mount();
    await screen.findByText(/try one of these/i);

    fireEvent.change(screen.getByLabelText(/address/i), {
      target: { value: "https://example.com/hook" },
    });
    fireEvent.click(screen.getByRole("button", { name: /^connect$/i }));

    expect(await screen.findByText(/copy its secret now/i)).toBeInTheDocument();
  });
});

/**
 * SPEC-307 acceptance criterion #6: "jargon lint on all screen copy".
 * system.md §3 rule 0 — no protocol name, standard, acronym, transport or
 * implementation word in a label, heading, button, badge, status line or
 * option name; the technical term may still live in hint text or a
 * `title` attribute. Scoped to exactly those control surfaces, same as
 * `Exposure.test.tsx`'s own lint.
 */
describe("Automations screen copy — no jargon in the surface (system.md §3 rule 0)", () => {
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
  ];

  it("no heading, button, badge, option, or field label uses an implementation word", async () => {
    vi.spyOn(api, "listAutomations").mockResolvedValue([]);
    vi.spyOn(api, "listHooks").mockResolvedValue([]);

    mount();
    await screen.findByText(/try one of these/i);

    const controls = [
      ...screen.queryAllByRole("heading"),
      ...screen.queryAllByRole("button"),
      ...screen.queryAllByRole("option"),
      ...Array.from(
        document.querySelectorAll(".badge, .card__title, .card__subject, .field__label"),
      ),
    ];

    expect(controls.length).toBeGreaterThan(5); // the scan actually saw real content
    for (const element of controls) {
      const text = element.textContent ?? "";
      for (const pattern of BANNED) {
        expect(text).not.toMatch(pattern);
      }
    }
  });
});
