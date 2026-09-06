import { act, renderHook, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { api } from "./api/client";
import type { InfoResponse } from "./api/client";
import { isHubMode, notifyModeChanged, resetHubModeForTests, useHubMode } from "./mode";

function info(mode: string): InfoResponse {
  return { mode } as unknown as InfoResponse;
}

afterEach(() => {
  vi.restoreAllMocks();
  resetHubModeForTests();
});

describe("useHubMode (issue 343)", () => {
  it("starts unknown and takes the mode the hub reports", async () => {
    vi.spyOn(api, "info").mockResolvedValue(info("open"));

    const { result } = renderHook(() => useHubMode());

    expect(result.current).toBeNull();
    await waitFor(() => expect(result.current).toBe("open"));
  });

  it("follows a change the Access page announces, without another fetch", async () => {
    const spy = vi.spyOn(api, "info").mockResolvedValue(info("locked"));
    const { result } = renderHook(() => useHubMode());
    await waitFor(() => expect(result.current).toBe("locked"));

    act(() => notifyModeChanged("cloud"));

    expect(result.current).toBe("cloud");
    expect(spy).toHaveBeenCalledTimes(1);
  });

  it("stays unknown when the hub cannot be reached", async () => {
    vi.spyOn(api, "info").mockRejectedValue(new Error("offline"));

    const { result } = renderHook(() => useHubMode());

    await new Promise((resolve) => setTimeout(resolve, 0));
    expect(result.current).toBeNull();
  });

  it("only accepts the three real modes", () => {
    expect(isHubMode("locked") && isHubMode("cloud") && isHubMode("open")).toBe(true);
    expect(isHubMode("public")).toBe(false);
    expect(isHubMode(undefined)).toBe(false);
  });
});
