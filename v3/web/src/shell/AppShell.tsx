import { Suspense, useCallback, useEffect, useState } from "react";
import { Outlet, useLocation, useMatches } from "react-router-dom";

import { PageHeader } from "../components/PageHeader";
import { useEventStream } from "../lib/events";
import { hubHealth } from "../lib/health";
import { useHubMode } from "../lib/mode";
import { useSession } from "../lib/session";
import { useFirstRunRedirect } from "../lib/setup";
import { PHONE_QUERY, useMediaQuery } from "../lib/useMediaQuery";
import { ScreenLoading } from "../routes/ScreenLoading";
import { CommandPalette } from "./CommandPalette";
import { MenuIcon, SearchIcon } from "./icons";
import { NotificationBell } from "./NotificationBell";
import { Brand, Sidebar } from "./Sidebar";
import { UpdateBanner } from "./UpdateBanner";

/** A key press in a field, or in text being edited, is typing. */
function isTyping(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return false;
  return target.isContentEditable || ["INPUT", "TEXTAREA", "SELECT"].includes(target.tagName);
}

/**
 * What a route tells the shell about its page (`handle` in the route table):
 * the title and one-line description for the page header, and for a
 * sub-page the parent it belongs to. A page that needs its own header (one
 * with a primary action) sets `ownHeader` and renders `PageHeader` itself.
 */
export interface PageHandle {
  title: string;
  description?: string;
  back?: { to: string; label: string };
  ownHeader?: boolean;
}

function isPageHandle(value: unknown): value is PageHandle {
  return typeof value === "object" && value !== null && typeof (value as PageHandle).title === "string";
}

/**
 * The app shell: sidebar (≥ 1024 px), icon rail (768–1023 px), or app bar
 * plus drawer (< 768 px); the page header from the route's handle; the
 * update banner; and the screen itself.
 */
export function AppShell() {
  const stream = useEventStream();
  const mode = useHubMode();
  // issue 559: an unfinished first-run setup opens the wizard, not Home.
  useFirstRunRedirect();
  const { session, signOut } = useSession();
  const location = useLocation();
  const matches = useMatches();
  const isPhone = useMediaQuery(PHONE_QUERY);
  // The drawer remembers the page it was opened on, so it is closed again
  // as soon as the page changes (a link, Back, a redirect).
  const [drawerPath, setDrawerPath] = useState<string | null>(null);
  const drawerOpen = drawerPath === location.pathname;
  const setDrawerOpen = useCallback(
    (open: boolean) => setDrawerPath(open ? location.pathname : null),
    [location.pathname],
  );
  const health = hubHealth(stream);

  const handle = [...matches].reverse().map((match) => match.handle).find(isPageHandle);

  useEffect(() => {
    document.title = handle ? `${handle.title} · palaia` : "palaia";
  }, [handle]);

  useEffect(() => {
    if (!drawerOpen) return;
    function onKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") setDrawerOpen(false);
    }
    document.addEventListener("keydown", onKeyDown);
    return () => document.removeEventListener("keydown", onKeyDown);
  }, [drawerOpen, setDrawerOpen]);

  // ⌘K / Ctrl+K anywhere opens the command palette and closes it again;
  // "/" opens it when nothing is being typed.
  const [paletteOpen, setPaletteOpen] = useState(false);
  const openPalette = useCallback(() => {
    setDrawerPath(null);
    setPaletteOpen(true);
  }, []);
  useEffect(() => {
    function onKeyDown(event: KeyboardEvent) {
      if ((event.metaKey || event.ctrlKey) && !event.altKey && event.key.toLowerCase() === "k") {
        event.preventDefault();
        setDrawerPath(null);
        setPaletteOpen((open) => !open);
        return;
      }
      if (event.key === "/" && !event.metaKey && !event.ctrlKey && !event.altKey && !isTyping(event.target)) {
        event.preventDefault();
        setDrawerPath(null);
        setPaletteOpen(true);
      }
    }
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, []);

  const signedInAs = session?.signed_in ? session.username : null;
  const bell = <NotificationBell />;

  return (
    <div className={["app", drawerOpen ? "app--drawer-open" : ""].filter(Boolean).join(" ")}>
      <a className="skiplink" href="#content">
        Skip to content
      </a>
      <Sidebar
        id="app-sidebar"
        mode={mode}
        health={health}
        vaultChangeCount={stream.vaultChangeCount}
        topEnd={isPhone ? null : bell}
        signedInAs={signedInAs}
        onSignOut={signOut}
        onNavigate={() => setDrawerOpen(false)}
        onSearch={openPalette}
      />
      <div className="drawer-scrim" onClick={() => setDrawerOpen(false)} aria-hidden="true" />
      <div className="main">
        {isPhone ? (
          <header className="appbar">
            <button
              type="button"
              className="iconbtn"
              aria-label="Menu"
              title="Menu"
              aria-expanded={drawerOpen}
              aria-controls="app-sidebar"
              onClick={() => setDrawerOpen(!drawerOpen)}
            >
              <MenuIcon className="icon" />
            </button>
            <Brand />
            <button type="button" className="iconbtn" aria-label="Search" title="Search" onClick={openPalette}>
              <SearchIcon className="icon" />
            </button>
            {bell}
          </header>
        ) : null}
        <main className="content" id="content" tabIndex={-1}>
          <UpdateBanner />
          {handle && !handle.ownHeader ? (
            <PageHeader title={handle.title} description={handle.description} back={handle.back} />
          ) : null}
          {/* Screens load lazily (issue 406); the shell stays put meanwhile. */}
          <Suspense fallback={<ScreenLoading />}>
            <Outlet context={stream} />
          </Suspense>
        </main>
      </div>
      <CommandPalette
        open={paletteOpen}
        onClose={() => setPaletteOpen(false)}
        onSignOut={signedInAs ? signOut : undefined}
      />
    </div>
  );
}
