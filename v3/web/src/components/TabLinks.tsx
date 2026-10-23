import type { ReactNode } from "react";
import { NavLink } from "react-router-dom";

/**
 * Tabs that are addresses: each tab is a link, so a tab can be bookmarked,
 * reloaded and opened from elsewhere ("Memories › Needs review").
 */
export function TabLinks({
  label,
  items,
}: {
  /** What the tabs switch between, for screen readers. */
  label: string;
  items: { to: string; label: ReactNode; end?: boolean; count?: number }[];
}) {
  return (
    <nav className="tabbar" aria-label={label}>
      {items.map((item) => (
        <NavLink key={item.to} to={item.to} end={item.end}>
          {item.label}
          {item.count ? <span className="nav__count">{item.count}</span> : null}
        </NavLink>
      ))}
    </nav>
  );
}
