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

export function Topbar({
  title,
  subtitle,
  health,
  userInitials,
}: {
  title: ReactNode;
  subtitle?: ReactNode;
  health: HealthState;
  userInitials: string;
}) {
  return (
    <header className="topbar">
      <div>
        <h1 className="page-title">{title}</h1>
        {subtitle ? <p className="page-sub">{subtitle}</p> : null}
      </div>
      <div className="row">
        <button className="cmdk" type="button" aria-label="Search or jump to">
          <SearchIcon className="icon--sm" />
          <span>Search or jump to</span>
          <span className="kbd" style={{ marginLeft: "auto" }}>
            ⌘K
          </span>
        </button>
        <span className="badge badge--ok" title={HEALTH_LABEL[health]}>
          <span
            className={["dot", HEALTH_DOT[health]].filter(Boolean).join(" ")}
          />
          {HEALTH_LABEL[health]}
        </span>
        <NotificationBell />
        <span className="avatar" aria-hidden="true">
          {userInitials}
        </span>
      </div>
    </header>
  );
}
