import { render, screen, waitFor } from "@testing-library/react";
import { createMemoryRouter, RouterProvider } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ToastProvider } from "../components/Toast";
import { api } from "../lib/api/client";
import { ThemeProvider } from "../lib/theme";
import { REDIRECTS, routes } from "./index";

afterEach(() => {
  vi.restoreAllMocks();
});

function mountAt(path: string) {
  const router = createMemoryRouter(routes, { initialEntries: [path] });
  render(
    <ThemeProvider>
      <ToastProvider>
        <RouterProvider router={router} />
      </ToastProvider>
    </ThemeProvider>,
  );
  return router;
}

describe("old dashboard addresses (issue 570)", () => {
  it.each(Object.entries(REDIRECTS))("%s lands on %s", async (from, to) => {
    vi.spyOn(api, "info").mockRejectedValue(new Error("no hub"));
    const router = mountAt(from);
    await waitFor(() => expect(router.state.location.pathname).toBe(to));
  });

  it("keeps the query string, so the MCP apps' install links still work", async () => {
    vi.spyOn(api, "info").mockRejectedValue(new Error("no hub"));
    const router = mountAt("/marketplace?install=palaia.fetch");
    await waitFor(() => expect(router.state.location.pathname).toBe("/add-ons"));
    expect(router.state.location.search).toBe("?install=palaia.fetch");
  });

  it("every new address renders a page inside the shell, not the not-found page", async () => {
    vi.spyOn(api, "info").mockRejectedValue(new Error("no hub"));
    for (const to of new Set(Object.values(REDIRECTS))) {
      document.body.innerHTML = "";
      mountAt(to);
      await waitFor(() =>
        expect(screen.getByRole("navigation", { name: "Primary" })).toBeInTheDocument(),
      );
      expect(screen.queryByText(/that page doesn't exist/i)).not.toBeInTheDocument();
    }
  });
});
