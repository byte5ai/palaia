import type { Story } from "@ladle/react";
import { MemoryRouter } from "react-router-dom";

import { PageHeader } from "../components/PageHeader";
import type { HubHealth } from "../lib/health";
import { Sidebar } from "./Sidebar";

export default {
  title: "Navigation / Shell",
};

const RUNNING: HubHealth = { tone: "ok", label: "Running" };

export const SidebarAndContent: Story = () => (
  <MemoryRouter initialEntries={["/memories"]}>
    <div className="app" style={{ height: 600, border: "1px solid var(--border)" }}>
      <Sidebar
        mode="locked"
        health={RUNNING}
        vaultChangeCount={3}
        signedInAs="owner"
        onSignOut={() => {}}
      />
      <div className="main">
        <main className="content">
          <PageHeader
            title="Memories"
            description="What your AI apps saved, and what palaia wants you to check."
          />
          <p className="t-muted">Screen content renders here.</p>
        </main>
      </div>
    </div>
  </MemoryRouter>
);

export const HealthStates: Story = () => (
  <MemoryRouter>
    <div className="row" style={{ alignItems: "stretch", gap: 16 }}>
      {(
        [
          { tone: "neutral", label: "Connecting…" },
          RUNNING,
          { tone: "warn", label: "Needs attention" },
          { tone: "error", label: "Can't reach palaia" },
        ] as HubHealth[]
      ).map((health) => (
        <div key={health.label} style={{ height: 420, width: 248 }}>
          <Sidebar mode="cloud" health={health} vaultChangeCount={0} />
        </div>
      ))}
    </div>
  </MemoryRouter>
);
