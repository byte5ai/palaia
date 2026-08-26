/**
 * Live-state layer: a React hook around the hub's `/api/events`
 * Server-Sent Events stream, carrying the SPEC-201 public event envelope
 * (see `v3/docs/events.md`).
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

/** The SSE frame names this hook listens for beyond `health` — SPEC-201's
 * `memory.entry.*` vocabulary, superseding SPEC-109's raw `vault_changed`
 * disk-watcher batches (one real vault event, not a debounced file-count). */
const MEMORY_ENTRY_EVENTS = [
  "memory.entry.created",
  "memory.entry.updated",
  "memory.entry.deleted",
  "memory.entry.moved",
] as const;

export interface MemoryEntryEventData {
  path?: string;
  previous_path?: string;
  checksum?: string;
  previous_checksum?: string;
  external?: boolean;
  kind?: string;
  [key: string]: unknown;
}

/** One entry of `recentChanges` — the envelope's identifying fields plus
 * when it arrived, for Home's activity feed (SPEC-110/SPEC-201). */
export interface VaultChangeEntry {
  ts: number;
  event: string;
  vault: string | null;
  permalink: string | null;
  data: MemoryEntryEventData;
}

/** How many `recentChanges` entries `EventStreamState` keeps — a feed, not
 * an unbounded log; older entries fall off the end. */
const RECENT_CHANGES_LIMIT = 20;

/** SPEC-405's directory + messenger events (SPEC-201/402/403's public
 * vocabulary) — the Agents screen's live-update signal. This hook does not
 * decode their payloads (the directory/messenger REST mirrors are the
 * source of truth for that, per SPEC-405 deliverable #1: "no polling
 * loop" means the Agents screen refetches *on* one of these arriving, not
 * that it parses the event itself). */
const AGENT_ACTIVITY_EVENTS = [
  "session.registered",
  "session.updated",
  "session.idle",
  "session.stale",
  "session.deregistered",
  "message.sent",
  "message.received",
  "message.expired",
] as const;

export type ConnectionState = "connecting" | "open" | "reconnecting" | "closed";

export interface EventStreamState {
  connection: ConnectionState;
  health: HealthEventData | null;
  /** Timestamp (ms) of the last received health snapshot/tick. */
  healthAt: number | null;
  /** Running count of memory.entry.* events seen this session — the
   * acceptance-criterion badge: "vault file touched on disk → explorer
   * badge updates without reload". */
  vaultChangeCount: number;
  lastVaultChange: VaultChangeEntry | null;
  /** The most recent `vaultChangeCount` events, newest first — Home's
   * activity feed (SPEC-110 deliverable #4: "recent activity feed
   * (SSE-live)"). Bounded to `RECENT_CHANGES_LIMIT` entries. */
  recentChanges: VaultChangeEntry[];
  /** Running count of `AGENT_ACTIVITY_EVENTS` seen this session (SPEC-405
   * deliverable #1: "live updates ... no polling loop") — the Agents
   * screen watches this number and refetches the directory/message flows
   * whenever it changes, the same "count as a change signal" shape
   * `vaultChangeCount` already established for the explorer badge. */
  agentActivityCount: number;
}

const INITIAL_STATE: EventStreamState = {
  connection: "connecting",
  health: null,
  healthAt: null,
  vaultChangeCount: 0,
  lastVaultChange: null,
  recentChanges: [],
  agentActivityCount: 0,
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

    const onMemoryEntryEvent = (event: MessageEvent<string>) => {
      try {
        const payload = JSON.parse(event.data) as {
          event: string;
          vault?: string | null;
          permalink?: string | null;
          data: MemoryEntryEventData;
          ts?: number;
        };
        const entry: VaultChangeEntry = {
          ts: (payload.ts ?? Date.now() / 1000) * 1000,
          event: payload.event,
          vault: payload.vault ?? null,
          permalink: payload.permalink ?? null,
          data: payload.data,
        };
        setState((prev) => ({
          ...prev,
          connection: "open",
          vaultChangeCount: prev.vaultChangeCount + 1,
          lastVaultChange: entry,
          recentChanges: [entry, ...prev.recentChanges].slice(0, RECENT_CHANGES_LIMIT),
        }));
      } catch {
        // same as above: drop and wait for the next event
      }
    };
    for (const eventName of MEMORY_ENTRY_EVENTS) {
      source.addEventListener(eventName, onMemoryEntryEvent);
    }

    const onAgentActivityEvent = () => {
      setState((prev) => ({
        ...prev,
        connection: "open",
        agentActivityCount: prev.agentActivityCount + 1,
      }));
    };
    for (const eventName of AGENT_ACTIVITY_EVENTS) {
      source.addEventListener(eventName, onAgentActivityEvent);
    }

    return () => {
      source.close();
      setState((prev) => ({ ...prev, connection: "closed" }));
    };
  }, [EventSourceCtor]);

  return state;
}
