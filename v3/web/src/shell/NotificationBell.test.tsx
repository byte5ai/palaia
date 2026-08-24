import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { api, ApiError } from "../lib/api/client";
import { NotificationBell } from "./NotificationBell";

afterEach(() => {
  vi.restoreAllMocks();
});

describe("NotificationBell (SPEC-307)", () => {
  it("hides entirely when the hub has no notification center mounted", async () => {
    vi.spyOn(api, "unreadNotificationCount").mockRejectedValue(
      new ApiError("/api/notifications/unread_count", 404, undefined),
    );

    render(<NotificationBell />);

    await waitFor(() => expect(api.unreadNotificationCount).toHaveBeenCalled());
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
  });

  it("shows the unread count and lists notifications when opened", async () => {
    vi.spyOn(api, "unreadNotificationCount").mockResolvedValue({ count: 2 });
    vi.spyOn(api, "listNotifications").mockResolvedValue([
      {
        id: 1,
        title: "Review needed: inbox/x",
        body: "reason: ambiguous",
        source: "automation",
        created_at: new Date().toISOString(),
        read: false,
      },
    ]);
    vi.spyOn(api, "markNotificationRead").mockResolvedValue({
      id: 1,
      title: "Review needed: inbox/x",
      body: "reason: ambiguous",
      source: "automation",
      created_at: new Date().toISOString(),
      read: true,
    });

    render(<NotificationBell />);
    await waitFor(() => expect(api.unreadNotificationCount).toHaveBeenCalled());

    fireEvent.click(screen.getByRole("button"));

    expect(await screen.findByText("Review needed: inbox/x")).toBeInTheDocument();
  });
});
