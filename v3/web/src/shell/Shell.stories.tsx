import type { Story } from "@ladle/react";
import { MemoryRouter } from "react-router-dom";

import { Sidebar } from "./Sidebar";
import { Topbar } from "./Topbar";

export default {
  title: "Navigation / Shell",
};

export const SidebarAndTopbar: Story = () => (
  <MemoryRouter>
    <div className="app" style={{ height: 560, border: "1px solid var(--border-subtle-btm)" }}>
      <Sidebar mode="locked" vaultChangeCount={3} />
      <div className="main">
        <Topbar title="Good afternoon, Christian." health="ok" userInitials="CW" />
        <div className="content">
          <p className="t-sm t-muted">Screen content renders here.</p>
        </div>
      </div>
    </div>
  </MemoryRouter>
);

export const HealthStates: Story = () => (
  <div className="stack">
    <Topbar title="Connecting" health="connecting" userInitials="CW" />
    <Topbar title="Healthy" health="ok" userInitials="CW" />
    <Topbar title="Needs attention" health="warn" userInitials="CW" />
    <Topbar title="Broken" health="risk" userInitials="CW" />
  </div>
);
