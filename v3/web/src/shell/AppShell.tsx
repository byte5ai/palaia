import { Suspense, useCallback, useEffect } from "react";
import { Outlet, useLocation, useMatches, useNavigate } from "react-router-dom";

import { useEventStream } from "../lib/events";
import { useHubMode } from "../lib/mode";
import { initialsFor, useSession } from "../lib/session";
import { ScreenLoading } from "../routes/ScreenLoading";
import { NAV_GROUPS } from "./navConfig";
import { Sidebar } from "./Sidebar";
import { type HealthState, Topbar } from "./Topbar";
import { UpdateBanner } from "./UpdateBanner";

/** Where the topbar's search lands: the explorer, search box focused. */
export const EXPLORER_SEARCH_PATH = "/explorer?focus=search";

function currentPageTitle(pathname: string): string {
  for (const group of NAV_GROUPS) {
    for (const item of group.items) {
      if (item.path === pathname) return item.label;
    }
  }
  return "palaia";
}

function healthStateFrom(
  status: string | undefined,
  connection: string,
): HealthState {
  if (connection !== "open") return "connecting";
  if (status === "ok") return "ok";
  if (status === "degraded") return "warn";
  if (status === "error") return "risk";
  return "connecting";
}

/** The app shell: sidebar navigation, health-aware topbar, and the
 * content outlet — SPEC-109's deliverable #2. Feature screens (SPEC-110)
 * render inside `<Outlet />`; this SPEC's own routes are placeholders
 * that prove the shell, live-state layer and component library compose
 * (system.md's non-goal: "no React implementation" was SPEC-005's;
 * SPEC-110's non-goal here is "feature screens", not "no shell content
 * at all"). */
export function AppShell() {
  const stream = useEventStream();
  const mode = useHubMode();
  const { session, signOut } = useSession();
  const location = useLocation();
  const matches = useMatches();
  const navigate = useNavigate();
  const title = currentPageTitle(location.pathname);
  const subtitle = matches.at(-1)?.handle as string | undefined;

  // Issue 380: the topbar's search used to be a button with no handler.
  // It, and ⌘K / Ctrl+K anywhere in the shell, open the explorer with its
  // search box focused — the one full-text search the dashboard has.
  const openSearch = useCallback(
    () => navigate(EXPLORER_SEARCH_PATH),
    [navigate],
  );
  useEffect(() => {
    function onKeyDown(event: KeyboardEvent) {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        openSearch();
      }
    }
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [openSearch]);

  return (
    <div className="app">
      <Sidebar mode={mode} vaultChangeCount={stream.vaultChangeCount} />
      <div className="main">
        <Topbar
          title={title}
          subtitle={subtitle}
          health={healthStateFrom(stream.health?.status, stream.connection)}
          userInitials={initialsFor(session?.username ?? null)}
          signedInAs={session?.signed_in ? session.username : null}
          onSignOut={signOut}
          onSearch={openSearch}
        />
        <div className="content">
          <UpdateBanner />
          {/* Screens load lazily (issue 406); the shell stays put meanwhile. */}
          <Suspense fallback={<ScreenLoading />}>
            <Outlet context={stream} />
          </Suspense>
        </div>
      </div>
    </div>
  );
}
