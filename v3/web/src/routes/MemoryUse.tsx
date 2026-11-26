/**
 * Do your AI apps actually use their memory? (issue 524)
 *
 * Per app, over the last seven days: how often it looked something up
 * (recall, search, read, build_context, list, recent activity), how often it
 * saved (write, edit, capture), and how many of its sessions saved before
 * looking anything up — the app that writes without reading what is already
 * there. The counts come from `GET /api/auth/tokens/usage` and survive
 * restarts; the card hides itself on a hub that does not count them.
 */
import { useEffect, useState } from "react";

import "./apps.css";

import { Card, CardHeader } from "../components/Card";
import { InlineEmpty } from "../components/EmptyState";
import { StatusPill } from "../components/StatusPill";
import type { ClientUsage } from "../lib/api/client";
import { api } from "../lib/api/client";
import { count } from "../lib/format";

const DAYS = 7;

function UsageRow({ usage }: { usage: ClientUsage }) {
  const label = usage.name ?? "An app signed in with your palaia account";
  const neverLooked = usage.lookups === 0 && usage.saves > 0;
  const habit = neverLooked
    ? "Saves without looking anything up first — install the palaia skill."
    : usage.sessions_saved_first > 0
      ? `${usage.sessions_saved_first} of ${count(usage.sessions, "session", "sessions")} saved before looking anything up.`
      : usage.sessions > 0
        ? "Looks things up before saving."
        : undefined;
  return (
    <tr data-testid={`memory-use-${usage.client_id}`}>
      <th scope="row">
        {label}
        {usage.revoked ? <span className="t-meta"> · access revoked</span> : null}
      </th>
      <td className="t-num">{usage.lookups}</td>
      <td className="t-num">{usage.saves}</td>
      <td className="table__secondary">
        <span className="row row--wrap row--tight">
          {neverLooked ? <StatusPill tone="warn">Saves without looking</StatusPill> : null}
          <span className="t-muted">{habit ?? "–"}</span>
        </span>
      </td>
    </tr>
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
        // 404: this hub does not count memory use. Anything else: the rest
        // of the page works without this card.
        if (!cancelled) setHidden(true);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  if (hidden || usage === null) return null;

  return (
    <Card data-testid="memory-use">
      <CardHeader title="How your AI apps use their memory" description={`Last ${DAYS} days`} />
      {usage.length === 0 ? (
        <InlineEmpty>No AI app looked anything up or saved anything in the last {DAYS} days.</InlineEmpty>
      ) : (
        <div className="table-wrap">
          <table className="table table--flush">
            <caption className="sr-only">How your AI apps use their memory</caption>
            <thead>
              <tr>
                <th scope="col">App</th>
                <th scope="col">Looked up</th>
                <th scope="col">Saved</th>
                <th scope="col" className="table__secondary">
                  Habit
                </th>
              </tr>
            </thead>
            <tbody>
              {usage.map((entry) => (
                <UsageRow key={entry.client_id} usage={entry} />
              ))}
            </tbody>
          </table>
        </div>
      )}
    </Card>
  );
}
