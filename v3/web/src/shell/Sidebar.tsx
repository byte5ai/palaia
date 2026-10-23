import { type ReactNode, useEffect, useState } from "react";
import { NavLink } from "react-router-dom";

import { api } from "../lib/api/client";
import type { HubHealth } from "../lib/health";
import { type HubMode, MODE_LABEL } from "../lib/mode";
import { __version__ } from "../version";
import { PalaiaMark } from "./icons";
import { NAV_ITEMS, type NavItemConfig, SETTINGS_ITEM } from "./navConfig";

const TONE_DOT: Record<HubHealth["tone"], string> = {
  ok: "dot--ok",
  warn: "dot--warn",
  error: "dot--error",
  info: "dot--info",
  neutral: "",
};

function NavItem({ item, count, onNavigate }: { item: NavItemConfig; count?: number; onNavigate?: () => void }) {
  const Icon = item.icon;
  return (
    <NavLink
      to={item.path}
      end={item.end}
      title={item.label}
      onClick={onNavigate}
      className={({ isActive }) => ["nav__item", isActive ? "nav__item--on" : ""].filter(Boolean).join(" ")}
    >
      <Icon className="icon" />
      <span className="nav__label">{item.label}</span>
      {count ? (
        <span className="nav__count" aria-label={`${count} new`}>
          {count}
        </span>
      ) : null}
    </NavLink>
  );
}

/** The wordmark: the palaia star and "palaia" in Days One. */
export function Brand({ onNavigate }: { onNavigate?: () => void }) {
  return (
    <NavLink className="brand" to="/" aria-label="palaia, Overview" onClick={onNavigate}>
      <PalaiaMark className="brand__mark" />
      <span className="brand__name">palaia</span>
    </NavLink>
  );
}

/**
 * Sidebar (≥ 1024 px), icon rail (768–1023 px), drawer (< 768 px): the same
 * element, laid out by CSS. Five destinations, Settings below a divider,
 * and the hub's state in the footer: "Running · Private".
 */
export function Sidebar({
  mode,
  health,
  vaultChangeCount,
  topEnd,
  signedInAs,
  onSignOut,
  onNavigate,
  id,
}: {
  /** The hub's *running* access mode (issue 343) — `null` until known, so
   * the footer never names a mode the hub has not reported. */
  mode: HubMode | null;
  health: HubHealth;
  vaultChangeCount: number;
  /** Shown next to the wordmark (the notification bell). */
  topEnd?: ReactNode;
  signedInAs?: string | null;
  onSignOut?: () => void;
  /** Called after a link is followed (closes the drawer on phones). */
  onNavigate?: () => void;
  id?: string;
}) {
  // SPEC-501 #5: the hub's release channel next to the build's version.
  // Quiet failure: the line is just shorter.
  const [channel, setChannel] = useState<string | null>(null);
  useEffect(() => {
    let cancelled = false;
    api
      .info()
      .then((info) => {
        if (!cancelled && typeof info.channel === "string") setChannel(info.channel);
      })
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, []);

  const statusText = [health.label, health.tone === "ok" || health.tone === "warn" ? (mode ? MODE_LABEL[mode] : null) : null]
    .filter(Boolean)
    .join(" · ");

  return (
    <aside className="sidebar" id={id} aria-label="Main">
      <div className="sidebar__top">
        <Brand onNavigate={onNavigate} />
        {topEnd}
      </div>
      <nav className="nav" aria-label="Primary">
        {NAV_ITEMS.map((item) => (
          <NavItem
            key={item.path}
            item={item}
            count={item.liveBadge === "vaultChanges" ? vaultChangeCount : undefined}
            onNavigate={onNavigate}
          />
        ))}
        <hr className="nav__sep" />
        <NavItem item={SETTINGS_ITEM} onNavigate={onNavigate} />
      </nav>
      <div className="sidebar__foot">
        <div
          className="statusline"
          data-testid="access-mode"
          title={statusText}
          role="status"
        >
          <span className={["dot", TONE_DOT[health.tone]].filter(Boolean).join(" ")} aria-hidden="true" />
          <span className="statusline__text">{statusText}</span>
        </div>
        <div className="sidebar__meta">
          {__version__}
          {channel ? ` · ${channel}` : ""}
        </div>
        {signedInAs && onSignOut ? (
          <div className="sidebar__user">
            <span className="grow" title={`Signed in as ${signedInAs}`}>
              {signedInAs}
            </span>
            <button type="button" className="btn btn--plain btn--sm" onClick={onSignOut}>
              Sign out
            </button>
          </div>
        ) : null}
      </div>
    </aside>
  );
}
