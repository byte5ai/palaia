import { Outlet, useOutletContext } from "react-router-dom";

import { PageHeader } from "../components/PageHeader";
import { TabLinks } from "../components/TabLinks";
import type { EventStreamState } from "../lib/events";

/** Memories: Browse (the notes) and Needs review (what palaia asks you to
 * decide). Each tab is its own address. */
export function Memories() {
  const stream = useOutletContext<EventStreamState>();
  return (
    <div className="stack">
      <PageHeader
        title="Memories"
        description="What your AI apps saved, and what palaia wants you to check."
      />
      <TabLinks
        label="Memories"
        items={[
          { to: "/memories", label: "Browse", end: true },
          { to: "/memories/review", label: "Needs review" },
        ]}
      />
      <Outlet context={stream} />
    </div>
  );
}
