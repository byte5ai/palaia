/**
 * Does each AI tool actually use its memory? (issue 524)
 *
 * Per client, over the last seven days: how often it looked something up
 * (recall, search, read, build_context, list, recent activity), how often it
 * saved (write, edit, capture), and how many of its sessions saved before
 * looking anything up — the agent that writes without reading what is
 * already there. The counts come from `GET /api/auth/tokens/usage` and
 * survive restarts; the card hides itself on a hub that does not count them.
 */
import { useEffect, useState } from "react";

import type { ClientUsage } from "../lib/api/client";
import { api } from "../lib/api/client";

const DAYS = 7;

function plural(count: number, one: string, many: string): string {
  return `${count} ${count === 1 ? one : many}`;
}

function UsageRow({ usage }: { usage: ClientUsage }) {
  const label = usage.name ?? "Connection without a palaia token";
  const neverLooked = usage.lookups === 0 && usage.saves > 0;
  return (
    <li
      className="stack stack--2"
      data-testid={`memory-use-${usage.client_id}`}
    >
      <span className="row--between">
        <span className="t-sm">
          <b>{label}</b>
          {usage.revoked ? (
            <span className="t-meta"> · token revoked</span>
          ) : null}
        </span>
        <span className="t-meta">
          {plural(usage.lookups, "lookup", "lookups")} ·{" "}
          {plural(usage.saves, "save", "saves")}
        </span>
      </span>
      {neverLooked ? (
        <span className="field__error">
          It saves without ever looking anything up first.
        </span>
      ) : usage.sessions_saved_first > 0 ? (
        <span className="t-xs t-subtle">
          {usage.sessions_saved_first} of{" "}
          {plural(usage.sessions, "session", "sessions")} saved before looking
          anything up.
        </span>
      ) : usage.sessions > 0 ? (
        <span className="t-xs t-subtle">
          Every session looked things up before saving.
        </span>
      ) : null}
    </li>
  );
}

export function MemoryUseCard() {
  const [usage, setUsage] = useState<ClientUsage[] | null>(null);
  const [hidden, setHidden] = useState(false);

  useEffect(() => {
    let cancelled = false;
    api
      .tokenUsage(DAYS)
      .then((list) => {
        if (!cancelled) setUsage(list);
      })
      .catch(() => {
        // 404: this hub does not count memory use. Anything else: the
        // rest of the page works without it.
        if (!cancelled) setHidden(true);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  if (hidden || usage === null) return null;

  return (
    <div className="card" data-testid="memory-use">
      <div className="card__head">
        <h3 className="card__title">memory use</h3>
        <span className="t-meta">last {DAYS} days</span>
      </div>
      <div className="card__body">
        {usage.length === 0 ? (
          <p className="t-sm t-muted">
            No AI tool has looked anything up or saved anything in the last{" "}
            {DAYS} days.
          </p>
        ) : (
          <ul
            className="stack stack--3"
            style={{ listStyle: "none", padding: 0, margin: 0 }}
          >
            {usage.map((entry) => (
              <UsageRow key={entry.client_id} usage={entry} />
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}
