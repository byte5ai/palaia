import { useEffect, useState } from "react";
import { Link, useOutletContext } from "react-router-dom";

import { Badge, CardFoot, CardHead, EmptyState } from "../components";
import type { FunnelStatus, InfoResponse, TokenInfo, VaultSummary } from "../lib/api/client";
import { api } from "../lib/api/client";
import type { EventStreamState, VaultChangeEntry } from "../lib/events";
import { CheckIcon, ClientsIcon, ExplorerIcon } from "../shell/icons";

interface InboxAggregate {
  count: number;
  oldestAgeSeconds: number | null;
}

/** Aggregated across every vault (SPEC-210 deliverable #3): the dashboard
 * shows one number for "how caught up is semantic search", not one tile
 * per vault — a per-vault breakdown lives on the Explorer page instead. */
interface IndexAggregate {
  totalReady: number;
  totalPending: number;
  totalFailed: number;
  /** True once every vault that reports embeddings as enabled has fully
   * drained its backlog (vaults with embeddings disabled don't count
   * against this — see `embed_summary` for why). */
  allCaughtUp: boolean;
}

function formatDuration(seconds: number): string {
  if (seconds < 3600) return `${Math.round(seconds / 60)} min`;
  if (seconds < 86400) return `${Math.round(seconds / 3600)} h`;
  return `${Math.round(seconds / 86400)} d`;
}

function formatAgo(ms: number): string {
  const seconds = Math.max(0, (Date.now() - ms) / 1000);
  if (seconds < 60) return `${Math.round(seconds)} s ago`;
  if (seconds < 3600) return `${Math.round(seconds / 60)} min ago`;
  if (seconds < 86400) return `${Math.round(seconds / 3600)} h ago`;
  return `${Math.round(seconds / 86400)} d ago`;
}

const CHANGE_VERB: Record<string, string> = {
  "memory.entry.created": "Created",
  "memory.entry.updated": "Updated",
  "memory.entry.deleted": "Deleted",
  "memory.entry.moved": "Moved",
};

function describeChange(entry: VaultChangeEntry): string {
  const verb = CHANGE_VERB[entry.event] ?? "Changed";
  const target = entry.permalink ?? entry.data.path ?? "a note";
  return `${verb} ${target}`;
}

function Tile({
  label,
  metric,
  unit,
  sub,
  attention,
  action,
}: {
  label: string;
  metric: string | number;
  unit?: string;
  sub: string;
  attention?: boolean;
  action?: React.ReactNode;
}) {
  return (
    <div className={["tile", attention ? "tile--attention" : ""].filter(Boolean).join(" ")}>
      <div>
        <span className="t-over">{label}</span>
      </div>
      <div className="tile__metric">
        {metric}
        {unit ? <span className="tile__unit"> {unit}</span> : null}
      </div>
      <div className="tile__sub">{sub}</div>
      {action ? <div className="tile__action">{action}</div> : null}
    </div>
  );
}

/** The one-glance screen (SPEC-110 deliverable #4): health tiles, an
 * SSE-live activity feed, and connected clients with last-seen — on top
 * of SPEC-109's live-state layer, which this SPEC only reads from. */
export function Home() {
  const stream = useOutletContext<EventStreamState>();
  const [info, setInfo] = useState<InfoResponse | null>(null);
  const [vaults, setVaults] = useState<VaultSummary[] | null>(null);
  const [inbox, setInbox] = useState<InboxAggregate | null>(null);
  const [tokens, setTokens] = useState<TokenInfo[] | null>(null);
  const [indexAggregate, setIndexAggregate] = useState<IndexAggregate | null>(null);
  const [funnel, setFunnel] = useState<FunnelStatus | null>(null);

  useEffect(() => {
    let cancelled = false;
    api
      .info()
      .then((value) => {
        if (!cancelled) setInfo(value);
      })
      .catch(() => {
        // health/mode already reaches the topbar via SSE; this is extra
      });
    api
      .listVaults()
      .then(async (list) => {
        if (cancelled) return;
        setVaults(list);
        const statuses = await Promise.all(
          list.map((vault) => api.inboxStatus(vault.key).catch(() => null)),
        );
        if (cancelled) return;
        let count = 0;
        let oldest: number | null = null;
        for (const status of statuses) {
          if (!status) continue;
          count += status.count;
          if (status.oldest_age_seconds != null) {
            oldest = oldest == null ? status.oldest_age_seconds : Math.max(oldest, status.oldest_age_seconds);
          }
        }
        setInbox({ count, oldestAgeSeconds: oldest });

        const indexStatuses = await Promise.all(
          list.map((vault) => api.indexStatus(vault.key).catch(() => null)),
        );
        if (cancelled) return;
        let totalReady = 0;
        let totalPending = 0;
        let totalFailed = 0;
        let allCaughtUp = true;
        for (const status of indexStatuses) {
          if (!status) continue;
          totalReady += status.embeds.ready;
          totalPending += status.embeds.pending;
          totalFailed += status.embeds.failed;
          if (status.embeds.enabled && status.embeds.pending > 0) allCaughtUp = false;
        }
        setIndexAggregate({ totalReady, totalPending, totalFailed, allCaughtUp });
      })
      .catch(() => {
        if (!cancelled) setVaults([]);
      });
    api
      .listTokens()
      .then((list) => {
        if (!cancelled) setTokens(list);
      })
      .catch(() => {
        if (!cancelled) setTokens([]);
      });
    api
      .funnelStatus()
      .then((status) => {
        if (!cancelled) setFunnel(status);
      })
      .catch(() => {
        // no funnel store reachable yet — the rest of the page still works
      });
    return () => {
      cancelled = true;
    };
  }, []);

  // SPEC-504 deliverable #3: poll for the celebration moment the same
  // "no refresh button anywhere" way ConnectPanel.tsx polls for a client's
  // first call — this tile just isn't event-stream-backed either. Stops
  // once a first memory is recorded; nothing left to wait for after that.
  useEffect(() => {
    if (funnel?.first_memory_at) return;
    const id = window.setInterval(() => {
      api
        .funnelStatus()
        .then(setFunnel)
        .catch(() => {
          // a transient fetch failure just means the next tick tries again
        });
    }, 3000);
    return () => window.clearInterval(id);
  }, [funnel?.first_memory_at]);

  const isHealthy = stream.health?.status === "ok";
  const hasVaults = (vaults?.length ?? 0) > 0;
  const totalNotes = vaults?.reduce((sum, v) => sum + v.note_count, 0) ?? 0;
  const liveClients = (tokens ?? [])
    .filter((t) => !t.revoked_at && t.last_used_at)
    .sort((a, b) => (b.last_used_at ?? "").localeCompare(a.last_used_at ?? ""));

  return (
    <div className="stack">
      <section className="verdict">
        <div>
          <p className="t-over">State of the hub</p>
          <h2 className="verdict__line">
            {stream.connection === "connecting"
              ? "Connecting to the hub…"
              : !hasVaults
                ? "Your hub is up. Nothing to remember yet."
                : isHealthy
                  ? "Everything is healthy."
                  : "The hub needs a look."}
          </h2>
          <p className="verdict__sub">
            {vaults === null
              ? "Loading vaults…"
              : hasVaults
                ? `${vaults.length} vault${vaults.length === 1 ? "" : "s"}, ${totalNotes} note${totalNotes === 1 ? "" : "s"} on disk.`
                : "No vault exists yet — the onboarding wizard's third step creates one."}
          </p>
        </div>
        <div className="verdict__aside">
          {liveClients.length === 0 ? (
            <>
              <span className="t-over">Next step</span>
              <Link className="btn btn--primary btn--lg" to="/clients">
                <ClientsIcon className="icon--sm" />
                Connect your first client
              </Link>
              <span className="t-meta">about 2 minutes</span>
            </>
          ) : (
            <>
              <span className="t-over">Connection</span>
              <Badge variant={stream.connection === "open" ? "ok" : "warn"} live={stream.connection === "open"}>
                {stream.connection}
              </Badge>
            </>
          )}
        </div>
      </section>

      {funnel?.time_to_first_memory_display ? (
        <section className="banner banner--ok" data-testid="first-memory-celebration">
          <CheckIcon className="icon icon--sm" />
          <div>
            <p className="banner__title">Your first memory is in.</p>
            <p className="t-sm t-muted">
              Set up in {funnel.time_to_first_memory_display} — from install to a client's
              first successful write, timed by the hub itself. This number never leaves this hub.
            </p>
          </div>
        </section>
      ) : null}

      <section className="tiles">
        <Tile
          label="Hub"
          metric={info?.version ? String(info.version) : "…"}
          unit={info?.mode ? String(info.mode) : undefined}
          sub={isHealthy ? "healthy" : stream.connection === "connecting" ? "connecting…" : "needs a look"}
        />
        <Tile
          label="Vaults"
          metric={vaults?.length ?? "…"}
          unit={vaults?.length === 1 ? "vault" : "vaults"}
          sub={`${totalNotes} note${totalNotes === 1 ? "" : "s"}`}
        />
        <Tile
          label="Semantic search"
          metric={
            indexAggregate === null
              ? "…"
              : indexAggregate.allCaughtUp
                ? "caught up"
                : `${indexAggregate.totalPending}`
          }
          unit={indexAggregate && !indexAggregate.allCaughtUp ? "embedding" : undefined}
          sub={
            indexAggregate === null
              ? "loading…"
              : indexAggregate.allCaughtUp
                ? "searchable now — fully caught up"
                : `searchable now — catching up (${indexAggregate.totalReady} of ` +
                  `${indexAggregate.totalReady + indexAggregate.totalPending} embedded)`
          }
          attention={Boolean(indexAggregate && indexAggregate.totalFailed > 0)}
        />
        <Tile
          label="Inbox"
          metric={inbox?.count ?? "…"}
          unit="waiting"
          sub={
            inbox && inbox.oldestAgeSeconds != null
              ? `oldest capture ${formatDuration(inbox.oldestAgeSeconds)} old`
              : "nothing captured yet"
          }
          attention={Boolean(inbox && inbox.count > 0)}
          action={
            inbox && inbox.count > 0 ? (
              <Link className="btn btn--sm" to="/inbox">
                Review now
              </Link>
            ) : undefined
          }
        />
        <Tile
          label="Clients"
          metric={liveClients.length}
          unit="connected"
          sub={tokens ? `${tokens.length} token${tokens.length === 1 ? "" : "s"} issued` : "…"}
        />
      </section>

      <section className="home-grid">
        <div className="card" style={{ display: "flex", flexDirection: "column", minHeight: 0 }}>
          <CardHead title="activity">
            <Badge variant="neutral" live={stream.connection === "open"}>
              live
            </Badge>
          </CardHead>
          <div className="feed scrollpane" style={{ maxHeight: 320 }}>
            {stream.recentChanges.length === 0 ? (
              <div style={{ padding: "var(--space-6) var(--space-4)" }}>
                <EmptyState mark={<ExplorerIcon className="icon--lg" />} title="Nothing yet.">
                  A note written, moved or deleted anywhere in a vault shows up here the moment
                  it happens — no refresh needed.
                </EmptyState>
              </div>
            ) : (
              stream.recentChanges.map((entry, index) => (
                <div className="feed__item" key={`${entry.ts}-${index}`}>
                  <span className="feed__mark">
                    <ExplorerIcon className="icon--sm" />
                  </span>
                  <div className="grow">
                    <p className="feed__text">
                      {describeChange(entry)}
                      {entry.vault ? ` in ${entry.vault}` : ""}
                    </p>
                    <div className="feed__meta">
                      {entry.data.path ? (
                        <span className="chip chip--mono">{entry.data.path}</span>
                      ) : null}
                      <span className="t-meta">{formatAgo(entry.ts)}</span>
                    </div>
                  </div>
                </div>
              ))
            )}
          </div>
        </div>

        <div className="card">
          <CardHead title="clients" meta="last seen" />
          <div>
            {(tokens ?? []).length === 0 ? (
              <div style={{ padding: "var(--space-5)" }}>
                <p className="t-sm t-muted">No client has connected yet.</p>
              </div>
            ) : (
              (tokens ?? [])
                .filter((t) => !t.revoked_at)
                .map((token) => (
                  <div className="listrow" key={token.id}>
                    <span className={["dot", token.last_used_at ? "dot--ok" : ""].filter(Boolean).join(" ")} />
                    <div className="grow">
                      <div className="listrow__title">{token.name}</div>
                      <div className="listrow__meta">profile: {token.profile}</div>
                    </div>
                    <span className="t-meta">
                      {token.last_used_at ? formatAgo(new Date(token.last_used_at).getTime()) : "waiting"}
                    </span>
                  </div>
                ))
            )}
          </div>
          <CardFoot>
            <Link className="btn btn--primary btn--sm" to="/clients">
              <ClientsIcon className="icon--sm" />
              Connect a client
            </Link>
            {inbox && inbox.count > 0 ? (
              <span className="t-meta">{inbox.count} in the inbox</span>
            ) : null}
          </CardFoot>
        </div>
      </section>
    </div>
  );
}
