import { useEffect, useState } from "react";
import { NavLink } from "react-router-dom";

import { api } from "../lib/api/client";
import { __version__ } from "../version";
import { NAV_GROUPS } from "./navConfig";

export function Sidebar({
  mode,
  vaultChangeCount,
}: {
  mode: "locked" | "cloud" | "open";
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
        <div className="row t-xs t-muted" style={{ gap: 8 }}>
          <span className="dot dot--ok" />
          <span>
            <strong style={{ fontWeight: 600 }}>{MODE_LABEL[mode]}</strong>
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

const MODE_LABEL: Record<"locked" | "cloud" | "open", string> = {
  locked: "Your network only",
  cloud: "Cloud",
  open: "Open",
};
