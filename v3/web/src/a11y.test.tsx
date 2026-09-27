/**
 * Accessibility scan for the app shell (SPEC-109 acceptance criterion:
 * "axe-core a11y scan: no critical violations on the shell").
 *
 * Runs axe-core directly against the shell as rendered in jsdom. jsdom
 * has no real layout engine, so checks that need actual painted layout
 * (color-contrast chief among them) do not run reliably here — axe-core
 * itself detects this and skips them rather than producing false
 * positives; what it does check in this environment (landmark
 * structure, labelling, ARIA usage, list/table semantics, duplicate
 * ids, etc.) still covers real structural mistakes in the shell. A full
 * rendered-browser contrast check is a follow-up for a Playwright-backed
 * run once this SPEC has one.
 */
import { render, waitFor } from "@testing-library/react";
import axe from "axe-core";
import { createMemoryRouter, RouterProvider } from "react-router-dom";
import { afterEach, describe, expect, it } from "vitest";

import App from "./App";
import { ToastProvider } from "./components";
import { ThemeProvider } from "./lib/theme";
import { routes } from "./routes";

async function expectNoSeriousViolations(): Promise<void> {
  const results = await axe.run(document.body, {
    rules: { "color-contrast": { enabled: false } },
  });
  const seriousOrWorse = results.violations.filter(
    (violation) =>
      violation.impact === "critical" || violation.impact === "serious",
  );
  if (seriousOrWorse.length > 0) {
    const details = seriousOrWorse
      .map(
        (violation) =>
          `${violation.id} (${violation.impact}): ${violation.help}\n  ` +
          violation.nodes.map((node) => node.html).join("\n  "),
      )
      .join("\n");
    throw new Error(`axe-core found violations:\n${details}`);
  }
  expect(seriousOrWorse).toHaveLength(0);
}

describe("app shell accessibility", () => {
  afterEach(() => {
    document.body.innerHTML = "";
  });

  it("has no critical or serious axe-core violations", async () => {
    render(<App />);

    const results = await axe.run(document.body, {
      // Contrast checks are unreliable without a real layout engine
      // (see module docstring) — everything else stays on.
      rules: { "color-contrast": { enabled: false } },
    });

    const seriousOrWorse = results.violations.filter(
      (violation) =>
        violation.impact === "critical" || violation.impact === "serious",
    );

    if (seriousOrWorse.length > 0) {
      const details = seriousOrWorse
        .map(
          (violation) =>
            `${violation.id} (${violation.impact}): ${violation.help}`,
        )
        .join("\n");
      throw new Error(`axe-core found violations:\n${details}`);
    }

    expect(seriousOrWorse).toHaveLength(0);
  });
});

/**
 * Issue 383: the scan used to cover the shell and Home only; the screens
 * with real forms — where an unlabelled select or a button pretending to be
 * a radio hides — were never checked. No hub answers in jsdom, so each
 * screen renders its no-data/empty state plus whatever form it always
 * shows; that is exactly where the findings were.
 */
describe("feature screens accessibility (issue 383)", () => {
  afterEach(() => {
    document.body.innerHTML = "";
  });

  it.each([
    "/explorer",
    "/clients",
    "/automations",
    "/marketplace",
    "/agents",
    "/telegram",
    "/tools",
    "/exposure",
    "/settings",
    "/review-queue",
    "/backups",
    "/onboarding",
    "/no-such-page",
  ])("has no critical or serious axe-core violations at %s", async (path) => {
    const router = createMemoryRouter(routes, { initialEntries: [path] });
    render(
      <ThemeProvider>
        <ToastProvider>
          <RouterProvider router={router} />
        </ToastProvider>
      </ThemeProvider>,
    );
    // Let the screen settle on its answered/failed state before scanning.
    await waitFor(() =>
      expect(document.body.textContent?.length ?? 0).toBeGreaterThan(0),
    );
    // Screens load lazily (issue 406): scan the screen, not its placeholder.
    await waitFor(() =>
      expect(document.body.textContent).not.toContain("Loading this screen"),
    );
    await new Promise((resolve) => setTimeout(resolve, 50));

    await expectNoSeriousViolations();
  });
});
