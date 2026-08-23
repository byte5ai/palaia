import { useOutletContext } from "react-router-dom";

import { Badge, CardBody, CardFoot, CardHead } from "../components";
import type { EventStreamState } from "../lib/events";

/** The one-glance screen (SPEC-005 mockups/home.html). Feature content —
 * the tiles, the activity feed, the tool surface — is SPEC-110's; this
 * SPEC proves the shell, the live-state layer and the component library
 * by rendering the one card that is entirely this SPEC's own data: the
 * hub's health, straight off the SSE stream, updating without reload. */
export function Home() {
  const stream = useOutletContext<EventStreamState>();
  const isHealthy = stream.health?.status === "ok";

  return (
    <section className="card" style={{ maxWidth: 640 }}>
      <CardHead title="state of the hub" meta={stream.connection} />
      <CardBody>
        <h2 className="page-title" style={{ marginBottom: 8 }}>
          {stream.connection === "connecting"
            ? "Connecting to the hub…"
            : isHealthy
              ? "Everything is healthy."
              : "The hub needs a look."}
        </h2>
        <p className="t-lead">
          This card is live: it comes straight off <code className="t-mono">/api/events</code>{" "}
          and updates without reloading the page.
        </p>
      </CardBody>
      <CardFoot>
        <Badge variant={isHealthy ? "ok" : "warn"} live={stream.connection === "open"}>
          {stream.connection === "open" ? "live" : stream.connection}
        </Badge>
        {stream.healthAt ? (
          <span className="t-meta">
            last update {new Date(stream.healthAt).toLocaleTimeString()}
          </span>
        ) : null}
      </CardFoot>
    </section>
  );
}
