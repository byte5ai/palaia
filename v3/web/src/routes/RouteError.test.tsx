import { render, screen } from "@testing-library/react";
import { createMemoryRouter, RouterProvider } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ToastProvider } from "../components/Toast";
import { api } from "../lib/api/client";
import { routes } from "./index";
import { RouteError } from "./RouteError";

function mountAt(path: string) {
  const router = createMemoryRouter(routes, { initialEntries: [path] });
  return render(
    <ToastProvider>
      <RouterProvider router={router} />
    </ToastProvider>,
  );
}

afterEach(() => {
  vi.restoreAllMocks();
});

describe("routing errors (issue 379)", () => {
  it("shows a branded not-found page inside the shell for a URL nothing matches", async () => {
    vi.spyOn(api, "info").mockRejectedValue(new Error("no hub"));
    mountAt("/explorer/typo");

    expect(await screen.findByText(/that page doesn't exist/i)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /back to home/i })).toHaveAttribute("href", "/");
    // Still inside the shell: the navigation is there to leave by.
    expect(screen.getByRole("link", { name: /^explorer$/i })).toBeInTheDocument();
    expect(screen.queryByText(/unexpected application error/i)).not.toBeInTheDocument();
  });

  it("shows a branded page when a screen throws while rendering", async () => {
    function Broken(): never {
      throw new Error("the explorer tripped over itself");
    }
    const router = createMemoryRouter(
      [{ path: "/", element: <Broken />, errorElement: <RouteError /> }],
      { initialEntries: ["/"] },
    );
    render(<RouterProvider router={router} />);

    expect(await screen.findByText(/this screen ran into a problem/i)).toBeInTheDocument();
    expect(screen.getByText(/tripped over itself/i)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /back to home/i })).toHaveAttribute("href", "/");
  });
});
