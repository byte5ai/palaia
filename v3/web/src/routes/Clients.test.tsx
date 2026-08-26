import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ToastProvider } from "../components/Toast";
import { Clients } from "./Clients";

describe("Clients (connect-a-client)", () => {
  it("lists every §6-matrix client and explains a not-yet one when selected", async () => {
    render(
      <MemoryRouter>
        <ToastProvider>
          <Clients />
        </ToastProvider>
      </MemoryRouter>,
    );

    expect(screen.getByRole("button", { name: /claude code cli/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /^chatgpt/i })).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /^chatgpt/i }));

    // A not-yet client never dead-ends: it gets a truthful, specific reason.
    expect(await screen.findByText(/not available yet/i)).toBeInTheDocument();
  });

  it("selects a guided client by default and offers to issue it a token", async () => {
    render(
      <MemoryRouter>
        <ToastProvider>
          <Clients />
        </ToastProvider>
      </MemoryRouter>,
    );

    expect(await screen.findByRole("button", { name: /issue token/i })).toBeInTheDocument();
  });

  describe("Claude Desktop — the one-click download (SPEC-306)", () => {
    afterEach(() => {
      vi.unstubAllGlobals();
    });

    it("downloads a real bundle on click, no copy/paste step", async () => {
      const fetchMock = vi.fn().mockResolvedValue({
        ok: true,
        blob: async () => new Blob(["fake mcpb bytes"]),
      });
      vi.stubGlobal("fetch", fetchMock);
      const clickSpy = vi.fn();
      const originalClick = HTMLAnchorElement.prototype.click;
      HTMLAnchorElement.prototype.click = clickSpy;

      render(
        <MemoryRouter>
          <ToastProvider>
            <Clients />
          </ToastProvider>
        </MemoryRouter>,
      );

      fireEvent.click(screen.getByRole("button", { name: /claude code \(desktop app\)/i }));
      const downloadButton = await screen.findByRole("button", { name: /download bundle/i });
      fireEvent.click(downloadButton);

      // The dashboard's own mount-time calls (mode/listTokens) share this
      // same mocked `fetch` — the assertion is that *a* call named the
      // bundle endpoint, not that it was the only call.
      await waitFor(() => {
        const urls = fetchMock.mock.calls.map((call) => String(call[0]));
        expect(urls.some((url) => url.includes("/api/connect/mcpb"))).toBe(true);
      });
      await waitFor(() => expect(clickSpy).toHaveBeenCalledTimes(1));

      HTMLAnchorElement.prototype.click = originalClick;
    });

    it("shows the hub's own error instead of a dead end when it cannot build one", async () => {
      vi.stubGlobal(
        "fetch",
        vi.fn().mockResolvedValue({
          ok: false,
          status: 501,
          json: async () => ({ detail: "no client-authentication method is configured" }),
        }),
      );

      render(
        <MemoryRouter>
          <ToastProvider>
            <Clients />
          </ToastProvider>
        </MemoryRouter>,
      );

      fireEvent.click(screen.getByRole("button", { name: /claude code \(desktop app\)/i }));
      fireEvent.click(await screen.findByRole("button", { name: /download bundle/i }));

      expect(
        await screen.findByText(/no client-authentication method is configured/i),
      ).toBeInTheDocument();
    });
  });
});
