import { Outlet, useOutletContext } from "react-router-dom";

import { TabLinks } from "../components/TabLinks";
import type { EventStreamState } from "../lib/events";

/** Memories: Browse (the notes) and Needs review (what palaia asks you to
 * decide). Each tab is its own address. */
export function Memories() {
  const stream = useOutletContext<EventStreamState>();
  return (
    <div className="stack">
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
