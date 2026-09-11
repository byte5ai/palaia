import type { ReactNode } from "react";

import { SearchIcon } from "./icons";
import { NotificationBell } from "./NotificationBell";

export type HealthState = "ok" | "warn" | "risk" | "connecting";

const HEALTH_LABEL: Record<HealthState, string> = {
  ok: "Healthy",
  warn: "Needs attention",
  risk: "Broken",
  connecting: "Connecting…",
};

const HEALTH_DOT: Record<HealthState, string> = {
  ok: "dot--ok",
  warn: "dot--warn",
  risk: "dot--risk",
  connecting: "",
};

/** Issue 380: the badge used to be `badge--ok` whatever the state said. */
const HEALTH_BADGE: Record<HealthState, string> = {
  ok: "badge--ok",
  warn: "badge--warn",
  risk: "badge--risk",
  connecting: "badge--info",
};

export function Topbar({
  title,
  subtitle,
  health,
  userInitials,
  signedInAs,
  onSignOut,
  onSearch,
}: {
  title: ReactNode;
  subtitle?: ReactNode;
  health: HealthState;
  userInitials: string;
  /** SPEC-401 deliverable #6: the owner's name when someone is signed in on
   * this browser, `null` on a hub that asks nobody to sign in — which is
   * also when the sign-out button is left off, since there is nothing to
   * sign out of. */
  signedInAs?: string | null;
  onSignOut?: () => void;
  /** Issue 380: what the search button (and ⌘K / Ctrl+K) does — the shell
   * passes "go to the explorer's search box". Left off, the button is
   * not rendered at all rather than rendered dead. */
  onSearch?: () => void;
}) {
  return (
    <header className="topbar">
      <div>
        <h1 className="page-title">{title}</h1>
        {subtitle ? <p className="page-sub">{subtitle}</p> : null}
      </div>
      <div className="row">
        {onSearch ? (
          <button
            className="cmdk"
            type="button"
            aria-label="Search your memory"
            onClick={onSearch}
          >
            <SearchIcon className="icon--sm" />
            <span>Search your memory</span>
            <span className="kbd" style={{ marginLeft: "auto" }}>
              ⌘K
            </span>
          </button>
        ) : null}
        <span
          className={`badge ${HEALTH_BADGE[health]}`}
          title={HEALTH_LABEL[health]}
        >
          <span
            className={["dot", HEALTH_DOT[health]].filter(Boolean).join(" ")}
          />
          {HEALTH_LABEL[health]}
        </span>
        <NotificationBell />
        <span
          className="avatar"
          aria-hidden={signedInAs ? undefined : true}
          title={signedInAs ? `Signed in as ${signedInAs}` : undefined}
        >
          {userInitials}
        </span>
        {signedInAs && onSignOut ? (
          <button className="btn btn--ghost" type="button" onClick={onSignOut}>
            Sign out
          </button>
        ) : null}
      </div>
    </header>
  );
}
