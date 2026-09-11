import { render, screen, waitFor } from "@testing-library/react";
import { createMemoryRouter, RouterProvider } from "react-router-dom";
import { describe, expect, it } from "vitest";

import { ToastProvider } from "../components/Toast";
import { ThemeProvider } from "../lib/theme";
import { routes } from "./index";

describe("screens load on demand (issue 406)", () => {
  it("shows the shell at once and the screen once its code arrived", async () => {
    const router = createMemoryRouter(routes, {
      initialEntries: ["/settings"],
    });
    render(
      <ThemeProvider>
        <ToastProvider>
          <RouterProvider router={router} />
        </ToastProvider>
      </ThemeProvider>,
    );
    // The navigation is part of the entry chunk and renders immediately,
    // with the placeholder where the screen will be…
    expect(
      screen.getByRole("link", { name: /^explorer$/i }),
    ).toBeInTheDocument();
    expect(screen.getByText(/loading this screen/i)).toBeInTheDocument();
    // …until the screen's own chunk arrives and replaces it.
    await waitFor(() =>
      expect(
        screen.queryByText(/loading this screen/i),
      ).not.toBeInTheDocument(),
    );
    expect(document.querySelector(".content")?.textContent).toMatch(/\S/);
  });
});
