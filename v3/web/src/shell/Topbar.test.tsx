import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { api, ApiError } from "../lib/api/client";
import { Topbar } from "./Topbar";

afterEach(() => {
  vi.restoreAllMocks();
});

function mount(props: Partial<Parameters<typeof Topbar>[0]> = {}) {
  // No notification center on this hub: the bell hides itself.
  vi.spyOn(api, "unreadNotificationCount").mockRejectedValue(
    new ApiError("/api/notifications/unread_count", 404, undefined),
  );
  return render(<Topbar title="Home" health="ok" userInitials="PA" {...props} />);
}

describe("Topbar (issue 380)", () => {
  it("the search button does something: it calls back to open the search", () => {
    const onSearch = vi.fn();
    mount({ onSearch });

    fireEvent.click(screen.getByRole("button", { name: /search your memory/i }));

    expect(onSearch).toHaveBeenCalledTimes(1);
  });

  it("does not render a search button it cannot back", () => {
    mount();
    expect(screen.queryByRole("button", { name: /search your memory/i })).not.toBeInTheDocument();
  });

  it.each([
    ["ok", "badge--ok"],
    ["warn", "badge--warn"],
    ["risk", "badge--risk"],
    ["connecting", "badge--info"],
  ] as const)("the health badge's own colour follows the %s state", (health, cls) => {
    mount({ health });
    const badge = screen.getByTitle(/healthy|needs attention|broken|connecting/i);
    expect(badge).toHaveClass(cls);
    if (health !== "ok") expect(badge).not.toHaveClass("badge--ok");
  });
});
