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
import { render } from "@testing-library/react";
import axe from "axe-core";
import { afterEach, describe, expect, it } from "vitest";

import App from "./App";

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
      (violation) => violation.impact === "critical" || violation.impact === "serious",
    );

    if (seriousOrWorse.length > 0) {
      const details = seriousOrWorse
        .map((violation) => `${violation.id} (${violation.impact}): ${violation.help}`)
        .join("\n");
      throw new Error(`axe-core found violations:\n${details}`);
    }

    expect(seriousOrWorse).toHaveLength(0);
  });
});
