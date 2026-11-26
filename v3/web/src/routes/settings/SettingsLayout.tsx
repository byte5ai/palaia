/**
 * Settings: the areas as a navigation next to the area that is open, so
 * moving between them is one click and the page uses its width. Below
 * 1024 px the navigation is a row of tabs above the area.
 */
import { NavLink, Outlet, useOutletContext } from "react-router-dom";

import type { EventStreamState } from "../../lib/events";
import "../settings.css";
import { SETTINGS_AREAS } from "./settingsAreas";

export function SettingsLayout() {
  const stream = useOutletContext<EventStreamState | undefined>();
  return (
    <div className="settings-layout">
      <nav className="settings-nav" aria-label="Settings">
        {SETTINGS_AREAS.map((area) => (
          <NavLink
            key={area.to}
            to={area.to}
            end={area.end}
            className={({ isActive }) =>
              isActive ? "settings-nav__item settings-nav__item--on" : "settings-nav__item"
            }
          >
            {area.label}
          </NavLink>
        ))}
      </nav>
      <div className="settings-layout__area">
        <Outlet context={stream} />
      </div>
    </div>
  );
}
