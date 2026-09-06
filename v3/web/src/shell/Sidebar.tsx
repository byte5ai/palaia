import { useEffect, useState } from "react";
import { NavLink } from "react-router-dom";

import { api } from "../lib/api/client";
import { type HubMode, MODE_LABEL } from "../lib/mode";
import { __version__ } from "../version";
import { NAV_GROUPS } from "./navConfig";

export function Sidebar({
  mode,
  vaultChangeCount,
}: {
  /** The hub's *running* access mode (issue 343) — `null` until known, so
   * the footer never claims "Your network only" on a hub it has not asked. */
  mode: HubMode | null;
  vaultChangeCount: number;
}) {
  // SPEC-501 deliverable #5: the hub's own release channel, next to the
  // dashboard build's own version above it. Quiet failure (stays `null`,
  // the line is just shorter) — same rule as the update banner itself.
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

  return (
    <aside className="sidebar">
      <NavLink className="brand" to="/">
        <span className="brand__mark">p</span>
        <span className="brand__name">palaia</span>
        <span className="brand__ver">v3</span>
      </NavLink>
      <nav className="nav" aria-label="Primary">
        {NAV_GROUPS.map((group) => (
          <div className="nav__group" key={group.label}>
            <span className="nav__label t-over">{group.label}</span>
            {group.items.map((item) => {
              const Icon = item.icon;
              const count = item.liveBadge === "vaultChanges" ? vaultChangeCount : undefined;
              return (
                <NavLink
                  key={item.path}
                  to={item.path}
                  title={item.label}
                  className={({ isActive }) =>
                    ["nav__item", isActive ? "nav__item--on" : ""].filter(Boolean).join(" ")
                  }
                  end={item.path === "/"}
                >
                  <Icon className="icon--sm" />
                  <span>{item.label}</span>
                  {count ? <span className="nav__count">{count}</span> : null}
                </NavLink>
              );
            })}
          </div>
        ))}
      </nav>
      <div className="sidebar__foot">
        <div className="row t-xs t-muted" style={{ gap: 8 }} data-testid="access-mode">
          <span className={["dot", mode ? MODE_DOT[mode] : ""].filter(Boolean).join(" ")} />
          <span>
            <strong style={{ fontWeight: 600 }}>{mode ? MODE_LABEL[mode] : "…"}</strong>
          </span>
        </div>
        <div className="t-meta">
          v{__version__}
          {channel ? ` · ${channel}` : ""}
        </div>
      </div>
    </aside>
  );
}

/** Open puts this dashboard on the public internet — worth a warning
 * colour every time the operator looks at the footer. */
const MODE_DOT: Record<HubMode, string> = {
  locked: "dot--ok",
  cloud: "dot--ok",
  open: "dot--warn",
};
