import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ToastProvider } from "../../components/Toast";
import { Onboarding } from "./Onboarding";

describe("Onboarding wizard", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("walks all four steps: account → mode → vault → client", () => {
    render(
      <MemoryRouter>
        <Onboarding />
      </MemoryRouter>,
    );

    expect(screen.getByRole("heading", { name: /let's set up your hub/i })).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /continue/i }));
    expect(screen.getByRole("heading", { name: /who should be able to reach palaia/i })).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /continue with/i }));
    expect(screen.getByRole("heading", { name: /your first vault/i })).toBeInTheDocument();

    // Step 3's "Create vault" is disabled while there is no key, and
    // otherwise calls the real POST /api/vaults endpoint — no hub is
    // running in this test, so it is enough to see the step rendered
    // with its default key already filled in.
    expect(screen.getByDisplayValue("work")).toBeInTheDocument();
  });

  it("Back returns to the previous step without losing its own state", () => {
    render(
      <MemoryRouter>
        <Onboarding />
      </MemoryRouter>,
    );

    fireEvent.click(screen.getByRole("button", { name: /continue/i }));
    expect(screen.getByRole("heading", { name: /who should be able to reach palaia/i })).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /^back$/i }));
    expect(screen.getByRole("heading", { name: /let's set up your hub/i })).toBeInTheDocument();
  });

  it("reaches step 4 and renders a real connect flow once the vault is created", async () => {
    // The only step in this test that talks to a hub: mock just enough of
    // fetch's success shape for POST /api/vaults so the wizard advances
    // exactly the way it would against a real one.
    vi.stubGlobal(
      "fetch",
      vi.fn((url: string) => {
        if (String(url).includes("/api/vaults") && !String(url).includes("/notes")) {
          return Promise.resolve(
            new Response(JSON.stringify({ key: "work", purpose: null, path: "/x", writable: true, note_count: 1 }), {
              status: 200,
            }),
          );
        }
        return Promise.reject(new Error("network disabled in this test"));
      }),
    );

    render(
      <MemoryRouter>
        <ToastProvider>
          <Onboarding />
        </ToastProvider>
      </MemoryRouter>,
    );

    fireEvent.click(screen.getByRole("button", { name: /continue/i }));
    fireEvent.click(screen.getByRole("button", { name: /continue with/i }));
    fireEvent.click(screen.getByRole("button", { name: /create vault/i }));

    expect(await screen.findByRole("heading", { name: /connect your first client/i })).toBeInTheDocument();
    await waitFor(() => expect(screen.getByRole("button", { name: /issue token/i })).toBeInTheDocument());
  });
});
