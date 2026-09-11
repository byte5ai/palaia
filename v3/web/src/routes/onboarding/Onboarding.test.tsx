import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ToastProvider } from "../../components/Toast";
import { Onboarding } from "./Onboarding";

/** Step 1 asks the hub how it signs in before it offers anything (issue
 * issue 342); with no hub at all it settles on "sign-in server off", whose
 * Continue is enabled. */
async function continueButton() {
  const button = await screen.findByRole("button", { name: /^continue$/i });
  await waitFor(() => expect(button).toBeEnabled());
  return button;
}

describe("Onboarding wizard", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("walks all four steps: account → mode → vault → client", async () => {
    render(
      <MemoryRouter>
        <Onboarding />
      </MemoryRouter>,
    );

    expect(screen.getByRole("heading", { name: /let's set up your hub/i })).toBeInTheDocument();

    fireEvent.click(await continueButton());
    expect(screen.getByRole("heading", { name: /who should be able to reach palaia/i })).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /continue with/i }));
    expect(screen.getByRole("heading", { name: /your first vault/i })).toBeInTheDocument();

    // Step 3's "Create vault" is disabled while there is no key, and
    // otherwise calls the real POST /api/vaults endpoint — no hub is
    // running in this test, so it is enough to see the step rendered
    // with its default key already filled in.
    expect(screen.getByDisplayValue("work")).toBeInTheDocument();
  });

  it("step 2 sends the real mode change to the Access page instead of calling it unbuilt", async () => {
    render(
      <MemoryRouter>
        <Onboarding />
      </MemoryRouter>,
    );

    fireEvent.click(await continueButton());

    expect(screen.getByRole("link", { name: /access page/i })).toHaveAttribute("href", "/exposure");
    expect(screen.queryByText(/not this wizard, yet/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/changeable later in Settings/i)).not.toBeInTheDocument();
  });

  it("Back returns to the previous step without losing its own state", async () => {
    render(
      <MemoryRouter>
        <Onboarding />
      </MemoryRouter>,
    );

    fireEvent.click(await continueButton());
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

    fireEvent.click(await continueButton());
    fireEvent.click(screen.getByRole("button", { name: /continue with/i }));
    fireEvent.click(screen.getByRole("button", { name: /create vault/i }));

    expect(await screen.findByRole("heading", { name: /connect your first client/i })).toBeInTheDocument();
    await waitFor(() => expect(screen.getByRole("button", { name: /issue token/i })).toBeInTheDocument());

    // SPEC-504 deliverable #4: the wizard's final step links the exact
    // next actions — connect a second AI, install a tool, read the docs.
    expect(screen.getByRole("link", { name: /connect a second ai/i })).toHaveAttribute(
      "href",
      "/clients",
    );
    expect(screen.getByRole("link", { name: /install a tool/i })).toHaveAttribute(
      "href",
      "/marketplace",
    );
    const docsLink = screen.getByRole("link", { name: /read the docs/i });
    expect(docsLink).toHaveAttribute("target", "_blank");
    // Issue 322: the real docs origin (astro.config.mjs's site + base),
    // never the retired placeholder domain — see lib/docs.test.ts.
    expect(docsLink.getAttribute("href")).toMatch(/^https:\/\/palaia\.byte5\.ai\/docs\//);
  });
});

function stubHub(routes: Record<string, (init?: RequestInit) => Response>) {
  vi.stubGlobal(
    "fetch",
    vi.fn((url: string, init?: RequestInit) => {
      const path = new URL(String(url), "http://hub.test").pathname;
      const handler = routes[`${(init?.method ?? "GET").toUpperCase()} ${path}`];
      if (handler) return Promise.resolve(handler(init));
      return Promise.reject(new Error(`unexpected ${init?.method ?? "GET"} ${path}`));
    }),
  );
}

const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });

describe("Onboarding step 1: the owner account (issue 342)", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("creates the owner account on a hub with password sign-in and no owner yet", async () => {
    const posted: unknown[] = [];
    stubHub({
      "GET /api/info": () => json({ mode: "locked", sign_in: { method: "password", provider_name: null } }),
      "GET /api/auth/owner": () => json({ configured: false }),
      "POST /api/auth/owner": (init) => {
        posted.push(JSON.parse(String(init?.body)));
        return json({ configured: true }, 201);
      },
    });
    render(
      <MemoryRouter>
        <Onboarding />
      </MemoryRouter>,
    );

    const username = await screen.findByPlaceholderText("owner");
    const create = screen.getByRole("button", { name: /create account/i });
    expect(create).toBeDisabled();

    fireEvent.change(username, { target: { value: "ada" } });
    const [password, confirm] = Array.from(
      document.querySelectorAll<HTMLInputElement>('input[type="password"]'),
    );
    fireEvent.change(password, { target: { value: "correct horse battery staple" } });
    fireEvent.change(confirm, { target: { value: "correct horse battery" } });
    expect(create).toBeDisabled();
    expect(screen.getByText(/the two passwords differ/i)).toBeInTheDocument();
    fireEvent.change(confirm, { target: { value: "correct horse battery staple" } });
    expect(create).toBeEnabled();

    fireEvent.click(create);

    expect(await screen.findByRole("heading", { name: /who should be able to reach palaia/i })).toBeInTheDocument();
    expect(posted).toEqual([{ username: "ada", password: "correct horse battery staple" }]);
  });

  it("says so when the account already exists and simply continues", async () => {
    stubHub({
      "GET /api/info": () => json({ mode: "cloud", sign_in: { method: "password", provider_name: null } }),
      "GET /api/auth/owner": () => json({ configured: true }),
    });
    render(
      <MemoryRouter>
        <Onboarding />
      </MemoryRouter>,
    );

    expect(await screen.findByText(/already has its owner account/i)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /create account/i })).not.toBeInTheDocument();
    fireEvent.click(await continueButton());
    expect(screen.getByRole("heading", { name: /who should be able to reach palaia/i })).toBeInTheDocument();
  });

  it("offers to turn the sign-in server on when the hub runs without one, and asks for a restart", async () => {
    const modeChanges: unknown[] = [];
    stubHub({
      "GET /api/info": () => json({ mode: "locked", sign_in: { method: "none", provider_name: null } }),
      "GET /api/auth/owner": () => json({ detail: "Not Found" }, 404),
      "POST /api/mode": (init) => {
        modeChanges.push(JSON.parse(String(init?.body)));
        return json({ active_mode: "locked", configured_mode: "locked", restart_required: true, oauth_enabled: true });
      },
    });
    render(
      <MemoryRouter>
        <Onboarding />
      </MemoryRouter>,
    );

    fireEvent.click(await screen.findByRole("button", { name: /turn on sign-in/i }));

    expect(await screen.findByText(/one restart applies it/i)).toBeInTheDocument();
    expect(modeChanges).toEqual([{ oauth_enabled: true, oauth_issuer: window.location.origin }]);
    // Nothing else in the wizard is blocked on the restart.
    fireEvent.click(await continueButton());
    expect(screen.getByRole("heading", { name: /who should be able to reach palaia/i })).toBeInTheDocument();
  });

  it("has nothing to set up when the hub signs in through a provider", async () => {
    stubHub({
      "GET /api/info": () => json({ mode: "cloud", sign_in: { method: "idp", provider_name: "GitHub" } }),
      "GET /api/auth/owner": () => json({ configured: false }),
    });
    render(
      <MemoryRouter>
        <Onboarding />
      </MemoryRouter>,
    );

    expect(await screen.findByText(/signs you in through GitHub/i)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /create account/i })).not.toBeInTheDocument();
  });
});
