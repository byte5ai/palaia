/**
 * One wording for the hub's state, used by the sidebar, the app bar and the
 * Overview, so no two places describe the same moment differently.
 */
import type { StatusTone } from "../components/StatusPill";
import type { EventStreamState } from "./events";

export interface HubHealth {
  tone: StatusTone;
  /** Short: "Running", "Can't reach palaia". */
  label: string;
}

export function hubHealth(stream: Pick<EventStreamState, "connection" | "health">): HubHealth {
  if (stream.connection === "connecting") return { tone: "neutral", label: "Connecting…" };
  if (stream.connection !== "open") return { tone: "error", label: "Can't reach palaia" };
  const status = stream.health?.status;
  if (status === "ok") return { tone: "ok", label: "Running" };
  if (status === "degraded") return { tone: "warn", label: "Needs attention" };
  if (status === "error") return { tone: "error", label: "Not working" };
  return { tone: "neutral", label: "Connecting…" };
}
