import { describe, expect, it } from "vitest";

import { nextPollDelay, POLL_INITIAL_MS, POLL_MAX_MS } from "./polling";

describe("poll back-off (issue 384)", () => {
  it("grows from the first delay and stops at the cap", () => {
    const delays = [POLL_INITIAL_MS];
    for (let i = 0; i < 10; i += 1) delays.push(nextPollDelay(delays.at(-1)!));
    expect(delays[0]).toBe(3_000);
    expect(delays[1]).toBe(4_500);
    expect(delays[2]).toBe(6_750);
    for (let i = 1; i < delays.length; i += 1)
      expect(delays[i]).toBeGreaterThanOrEqual(delays[i - 1]!);
    expect(delays.at(-1)).toBe(POLL_MAX_MS);
    expect(nextPollDelay(POLL_MAX_MS)).toBe(POLL_MAX_MS);
  });
});
