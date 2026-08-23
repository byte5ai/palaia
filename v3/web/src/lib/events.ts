/**
 * Live-state layer (SPEC-109): a React hook around the hub's
 * `/api/events` Server-Sent Events stream.
 *
 * "No refresh button anywhere in this system" (system.md §0) — this hook
 * is how a list gets to be event-driven instead of polled. The browser's
 * native `EventSource` already retries a dropped connection on its own;
 * this hook just tracks the last known state so a component can render a
 * quiet "reconnecting" indicator instead of nothing.
 */
import { useEffect, useRef, useState } from "react";

import { api } from "./api/client";

export interface HealthEventData {
  status: string;
  components?: Record<string, string>;
  [key: string]: unknown;
}

export interface VaultChangedEventData {
  count: number;
  paths: string[];
}

/** One entry of `recentChanges` — the raw event plus when it arrived, for
 * Home's activity feed (SPEC-110). */
export interface VaultChangeEntry extends VaultChangedEventData {
  ts: number;
}

/** How many `recentChanges` entries `EventStreamState` keeps — a feed, not
 * an unbounded log; older entries fall off the end. */
const RECENT_CHANGES_LIMIT = 20;

export type ConnectionState = "connecting" | "open" | "reconnecting" | "closed";

export interface EventStreamState {
  connection: ConnectionState;
  health: HealthEventData | null;
  /** Timestamp (ms) of the last received health snapshot/tick. */
  healthAt: number | null;
  /** Running count of vault_changed events seen this session — the
   * acceptance-criterion badge: "vault file touched on disk → explorer
   * badge updates without reload". */
  vaultChangeCount: number;
  lastVaultChange: VaultChangedEventData | null;
  /** The most recent `vaultChangeCount` events, newest first — Home's
   * activity feed (SPEC-110 deliverable #4: "recent activity feed
   * (SSE-live)"). Bounded to `RECENT_CHANGES_LIMIT` entries. */
  recentChanges: VaultChangeEntry[];
}

const INITIAL_STATE: EventStreamState = {
  connection: "connecting",
  health: null,
  healthAt: null,
  vaultChangeCount: 0,
  lastVaultChange: null,
  recentChanges: [],
};

/** Build an `EventSource` unless a test/story has already provided one via
 * `EventSourceCtor` — this is the seam `stories/` and any future test use
 * to inject a fake stream instead of opening a real connection. */
export function useEventStream(
  EventSourceCtor: typeof EventSource = EventSource,
): EventStreamState {
  const [state, setState] = useState<EventStreamState>(INITIAL_STATE);
  const hasConnectedOnce = useRef(false);

  useEffect(() => {
    const source = new EventSourceCtor(api.eventsUrl());

    source.addEventListener("open", () => {
      setState((prev) => ({ ...prev, connection: "open" }));
      hasConnectedOnce.current = true;
    });

    source.addEventListener("error", () => {
      setState((prev) => ({
        ...prev,
        connection: hasConnectedOnce.current ? "reconnecting" : "connecting",
      }));
    });

    source.addEventListener("health", (event: MessageEvent<string>) => {
      try {
        const payload = JSON.parse(event.data) as { data: HealthEventData; ts: number };
        setState((prev) => ({
          ...prev,
          connection: "open",
          health: payload.data,
          healthAt: payload.ts * 1000,
        }));
      } catch {
        // A malformed frame is dropped rather than crashing the shell —
        // the next tick will land moments later.
      }
    });

    source.addEventListener("vault_changed", (event: MessageEvent<string>) => {
      try {
        const payload = JSON.parse(event.data) as { data: VaultChangedEventData; ts?: number };
        const entry: VaultChangeEntry = { ...payload.data, ts: (payload.ts ?? Date.now() / 1000) * 1000 };
        setState((prev) => ({
          ...prev,
          connection: "open",
          vaultChangeCount: prev.vaultChangeCount + payload.data.count,
          lastVaultChange: payload.data,
          recentChanges: [entry, ...prev.recentChanges].slice(0, RECENT_CHANGES_LIMIT),
        }));
      } catch {
        // same as above: drop and wait for the next event
      }
    });

    return () => {
      source.close();
      setState((prev) => ({ ...prev, connection: "closed" }));
    };
  }, [EventSourceCtor]);

  return state;
}
