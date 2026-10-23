import { Outlet, useOutletContext } from "react-router-dom";

import { PageHeader } from "../components/PageHeader";
import { TabLinks } from "../components/TabLinks";
import type { EventStreamState } from "../lib/events";

/** AI apps: the apps you connect, and the live sessions of agents that
 * registered with palaia. Each tab is its own address. */
export function AiApps() {
  const stream = useOutletContext<EventStreamState>();
  return (
    <div className="stack">
      <PageHeader
        title="AI apps"
        description="Connect the apps you use, and see which ones are working."
      />
      <TabLinks
        label="AI apps"
        items={[
          { to: "/apps", label: "Apps", end: true },
          { to: "/apps/sessions", label: "Live sessions" },
        ]}
      />
      <Outlet context={stream} />
    </div>
  );
}
