import { describe, expect, it } from "vitest";

import { ApiError } from "./api/client";
import { describeApiError } from "./errors";

describe("describeApiError — SPEC-504 error-message audit", () => {
  it("trusts a server-sent detail as-is (every funnel-path error already names its own fix)", () => {
    const err = new ApiError("/api/vaults", 400, {
      detail: "vault 'work' is already registered. Fix: pick another name.",
    });

    expect(describeApiError(err)).toBe("vault 'work' is already registered. Fix: pick another name.");
  });

  it("an unexpected status with no detail still names something to try", () => {
    const err = new ApiError("/api/vaults", 500, undefined);

    const message = describeApiError(err);
    expect(message).toMatch(/try again/i);
  });

  it("a network failure (no response at all) names a concrete next step, not just 'could not reach the hub'", () => {
    const message = describeApiError(new TypeError("Failed to fetch"));

    expect(message).toMatch(/still running/i);
    expect(message).toMatch(/try again/i);
  });
});
