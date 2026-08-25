/**
 * The shell's sign-out control (SPEC-401 deliverable #6).
 *
 * Rendered against the real `useSession` hook and a stubbed API, so the test
 * covers the decision the shell actually makes: show the control only when
 * somebody is signed in on this browser, and hand them back to the hub's
 * sign-in page when they use it.
 */
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { api, ApiError } from "../lib/api/client";
import { initialsFor, useSession } from "../lib/session";
import { Topbar } from "./Topbar";

function Shell() {
  const { session, signOut } = useSession();
  return (
    <Topbar
      title="Memory"
      health="ok"
      userInitials={initialsFor(session?.username ?? null)}
      signedInAs={session?.signed_in ? session.username : null}
      onSignOut={signOut}
    />
  );
}

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

describe("initials", () => {
  it("reads a name, and falls back rather than rendering an empty circle", () => {
    expect(initialsFor("Ada Lovelace")).toBe("AL");
    expect(initialsFor("ada.lovelace")).toBe("AL");
    expect(initialsFor("owner")).toBe("OW");
    expect(initialsFor(null)).toBe("PA");
  });
});

describe("the sign-out control", () => {
  it("appears once the hub says who is signed in", async () => {
    vi.spyOn(api, "session").mockResolvedValue({
      signed_in: true,
      username: "ada",
      required: true,
      sign_in_url: "/oauth/login",
      session_ttl_seconds: 43200,
    });
    vi.spyOn(api, "signOut").mockResolvedValue(undefined);
    const assign = vi.fn();
    vi.stubGlobal("location", { pathname: "/", search: "", assign });

    render(<Shell />);

    const button = await screen.findByRole("button", { name: "Sign out" });
    fireEvent.click(button);

    await waitFor(() => expect(api.signOut).toHaveBeenCalled());
    expect(assign).toHaveBeenCalledWith("/oauth/login");
  });

  it("stays away on a hub that asks nobody to sign in", async () => {
    vi.spyOn(api, "session").mockResolvedValue({
      signed_in: false,
      username: null,
      required: false,
      sign_in_url: "/oauth/login",
      session_ttl_seconds: 43200,
    });

    render(<Shell />);

    await waitFor(() => expect(api.session).toHaveBeenCalled());
    expect(screen.queryByRole("button", { name: "Sign out" })).not.toBeInTheDocument();
  });

  it("stays away on a hub with no sign-in server at all", async () => {
    vi.spyOn(api, "session").mockRejectedValue(new ApiError("/api/session", 404, undefined));

    render(<Shell />);

    await waitFor(() => expect(api.session).toHaveBeenCalled());
    expect(screen.queryByRole("button", { name: "Sign out" })).not.toBeInTheDocument();
  });
});
