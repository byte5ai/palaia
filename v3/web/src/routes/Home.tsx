/**
 * Overview: is palaia running, and what needs me?
 *
 * The verdict first ("palaia is running", "Finish setting up palaia",
 * "Can't reach palaia"), a few pills that summarise the state, the one next
 * action when there is one, then a card per area — each linking to its
 * detail — and the live activity feed. The health words are the sidebar's
 * (`lib/health.ts`), so the two never disagree.
 */
import { type ReactNode, useEffect, useState } from "react";
import { Link, useOutletContext } from "react-router-dom";

import {
  Button,
  Callout,
  Card,
  CardHeader,
  Disclosure,
  InlineEmpty,
  LinkButton,
  ListRow,
  LoadingState,
  PageHeader,
  RestartCallout,
  StatusPill,
} from "../components";
import type {
  BackupTargetsResponse,
  FunnelStatus,
  RecentChange,
  SetupStatus,
  TokenInfo,
  VaultSummary,
} from "../lib/api/client";
import { api, ApiError } from "../lib/api/client";
import { buildFeed } from "../lib/activityFeed";
import { describeApiError } from "../lib/errors";
import type { EventStreamState } from "../lib/events";
import { count, exactTime, spokenDuration, timeAgo } from "../lib/format";
import { hubHealth } from "../lib/health";
import { nextPollDelay, POLL_INITIAL_MS } from "../lib/polling";
import {
  ClientsIcon,
  ErrorIcon,
  ExplorerIcon,
  InfoIcon,
  ReviewIcon,
  VaultsIcon,
  WarningIcon,
} from "../shell/icons";

interface IndexProgress {
  ready: number;
  pending: number;
}

type BackupState = BackupTargetsResponse | "needs-sign-in" | null | undefined;

const CELEBRATION_KEY = "palaia.overview.first-note-seen";

function readFlag(key: string): boolean {
  try {
    return window.localStorage.getItem(key) === "1";
  } catch {
    return false;
  }
}

function writeFlag(key: string): void {
  try {
    window.localStorage.setItem(key, "1");
  } catch {
    // a per-viewer convenience: it just shows again next time
  }
}

function lastBackup(state: BackupState): { tone: "ok" | "warn" | "neutral" | "error"; line: string } {
  if (state === undefined) return { tone: "neutral", line: "Loading…" };
  if (state === "needs-sign-in") {
    return { tone: "warn", line: "Turn on dashboard sign-in to download backups." };
  }
  if (state === null) return { tone: "neutral", line: "Download a copy of your memories and settings." };
  const runs = state.targets
    .map((target) => target.last_run)
    .filter((run): run is NonNullable<typeof run> => Boolean(run));
  if (runs.length === 0) {
    return state.targets.length > 0
      ? { tone: "neutral", line: "No backup written yet." }
      : { tone: "neutral", line: "No automatic backups. Download one any time." };
  }
  const newest = runs.reduce((a, b) => (a.finished_at > b.finished_at ? a : b));
  if (!newest.ok) return { tone: "error", line: `Last automatic backup failed ${timeAgo(newest.finished_at * 1000)}.` };
  return { tone: "ok", line: `Last backup ${timeAgo(newest.finished_at * 1000)}.` };
}

function VerdictIcon({ tone }: { tone: "ok" | "warn" | "error" | "info" | "neutral" }) {
  const Icon = tone === "ok" ? ReviewIcon : tone === "error" ? ErrorIcon : tone === "warn" ? WarningIcon : InfoIcon;
  return (
    <span className={`verdict__icon verdict__icon--${tone}`} aria-hidden="true">
      <Icon className="icon" />
    </span>
  );
}

export function Home() {
  const stream = useOutletContext<EventStreamState>();
  const [attempt, setAttempt] = useState(0);
  const [vaults, setVaults] = useState<VaultSummary[] | null>(null);
  // Issue 378: a failed listing must never read as "nothing here yet".
  const [vaultsError, setVaultsError] = useState<string | null>(null);
  // No answer at all (not an error answer): palaia itself is unreachable.
  const [vaultsUnreachable, setVaultsUnreachable] = useState(false);
  const [toFile, setToFile] = useState<number | null>(null);
  const [index, setIndex] = useState<IndexProgress | null>(null);
  const [tokens, setTokens] = useState<TokenInfo[] | null>(null);
  const [setup, setSetup] = useState<SetupStatus | null>(null);
  const [backups, setBackups] = useState<BackupState>(undefined);
  const [funnel, setFunnel] = useState<FunnelStatus | null>(null);
  const [loadedChanges, setLoadedChanges] = useState<RecentChange[]>([]);
  const [celebrationSeen, setCelebrationSeen] = useState(() => readFlag(CELEBRATION_KEY));
  const feed = buildFeed(stream.recentChanges, loadedChanges);
  const health = hubHealth(stream);

  useEffect(() => {
    let cancelled = false;
    api
      .listVaults()
      .then(async (list) => {
        if (cancelled) return;
        setVaultsError(null);
        setVaultsUnreachable(false);
        setVaults(list);
        const inbox = await Promise.all(list.map((v) => api.inboxStatus(v.key).catch(() => null)));
        if (cancelled) return;
        setToFile(inbox.reduce((sum, status) => sum + (status?.count ?? 0), 0));
        const indexes = await Promise.all(list.map((v) => api.indexStatus(v.key).catch(() => null)));
        if (cancelled) return;
        let ready = 0;
        let pending = 0;
        for (const status of indexes) {
          if (!status || !status.embeds.enabled) continue;
          ready += status.embeds.ready;
          pending += status.embeds.pending;
        }
        setIndex({ ready, pending });
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        setVaultsUnreachable(!(err instanceof ApiError));
        setVaultsError(describeApiError(err));
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
      .setupStatus()
      .then((value) => {
        if (!cancelled) setSetup(value);
      })
      .catch(() => {
        // older hubs, or a hub mid-restart: the page works without it
      });
    api
      .listBackupTargets()
      .then((value) => {
        if (!cancelled) setBackups(value);
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        const gated = err instanceof ApiError && (err.status === 401 || err.status === 403);
        setBackups(gated ? "needs-sign-in" : null);
      });
    api
      .recentActivity()
      .then((changes) => {
        if (!cancelled) setLoadedChanges(changes);
      })
      .catch(() => {
        // the live feed still works; the list just starts empty
      });
    api
      .funnelStatus()
      .then((status) => {
        if (!cancelled) setFunnel(status);
      })
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, [attempt]);

  // SPEC-504: wait for the first saved note without a refresh button,
  // backing off (issue 384) and stopping once it arrived.
  const firstMemoryAt = funnel?.first_memory_at ?? null;
  useEffect(() => {
    if (firstMemoryAt) return;
    let cancelled = false;
    let delay = POLL_INITIAL_MS;
    let timer = 0;
    const tick = () => {
      api
        .funnelStatus()
        .then((status) => {
          if (!cancelled) setFunnel(status);
        })
        .catch(() => {})
        .finally(() => {
          if (cancelled) return;
          delay = nextPollDelay(delay);
          timer = window.setTimeout(tick, delay);
        });
    };
    timer = window.setTimeout(tick, delay);
    return () => {
      cancelled = true;
      window.clearTimeout(timer);
    };
  }, [firstMemoryAt]);

  const activeTokens = (tokens ?? []).filter((token) => !token.revoked_at);
  const connected = activeTokens
    .filter((token) => token.last_used_at)
    .sort((a, b) => (b.last_used_at ?? "").localeCompare(a.last_used_at ?? ""));
  // An AI app that signs in with the owner account (ChatGPT, Claude, the
  // extension on a hub with sign-in) uses no access key, so the keys can't
  // show it; the hub records the first request of any app
  // (`client_connected`). Counted only while sign-in runs and no key shows
  // a connection: that record is kept once ever, so it can't tell how many
  // apps, and a key's own use already counts.
  const signedInApp =
    connected.length === 0 && Boolean(setup?.client_connected && setup.sign_in_active);
  const anyConnected = connected.length > 0 || signedInApp;
  const hasVaults = (vaults?.length ?? 0) > 0;
  const totalNotes = vaults?.reduce((sum, vault) => sum + vault.note_count, 0) ?? 0;
  const unreachable =
    stream.connection === "reconnecting" || stream.connection === "closed" || vaultsUnreachable;

  // ---- the verdict ------------------------------------------------------
  let verdict: { tone: "ok" | "warn" | "error" | "info" | "neutral"; title: string; text?: ReactNode };
  let primary: ReactNode = null;
  if (unreachable) {
    verdict = {
      tone: "error",
      title: "Can't reach palaia",
      text: "Check that palaia is still running and that you opened the address shown at install. This page reconnects by itself.",
    };
  } else if (vaultsError) {
    verdict = {
      tone: "error",
      title: "Couldn't load your memories",
      text: `palaia answered with an error. ${vaultsError}`,
    };
    primary = (
      <Button variant="primary" onClick={() => setAttempt((n) => n + 1)}>
        Try again
      </Button>
    );
  } else if (vaults === null) {
    verdict = { tone: "neutral", title: "Connecting to palaia…" };
  } else if (!hasVaults) {
    verdict = {
      tone: "info",
      title: "Finish setting up palaia",
      text: "Create a memory so your AI apps have somewhere to save.",
    };
    primary = (
      <LinkButton variant="primary" to="/onboarding">
        Continue setup
      </LinkButton>
    );
  } else if (health.tone === "warn" || health.tone === "error") {
    verdict = {
      tone: health.tone,
      title: "palaia needs attention",
      text: "Part of palaia reports a problem. Restarting palaia often fixes it.",
    };
  } else if (health.tone === "neutral") {
    verdict = { tone: "neutral", title: "Connecting to palaia…" };
  } else {
    verdict = { tone: "ok", title: "palaia is running" };
    if (tokens !== null && !anyConnected) {
      verdict.text = "Connect an AI app so it can start saving to your memories.";
      primary = (
        <LinkButton variant="primary" to="/apps">
          Connect an AI app
        </LinkButton>
      );
    }
  }

  const problemComponents = Object.entries(stream.health?.components ?? {}).filter(
    ([, status]) => status !== "ok",
  );
  const showCelebration = Boolean(funnel?.time_to_first_memory_display) && !celebrationSeen;
  const backup = lastBackup(backups);

  return (
    <div className="stack">
      <PageHeader title="Overview" />

      <section className="verdict" aria-labelledby="verdict-title">
        <div className="verdict__main">
          <VerdictIcon tone={verdict.tone} />
          <div className="grow">
            <h2 className="verdict__line" id="verdict-title">
              {verdict.title}
            </h2>
            {verdict.text ? <p className="verdict__sub">{verdict.text}</p> : null}
            {verdict.tone === "ok" && vaults ? (
              <div className="verdict__pills">
                <StatusPill tone="neutral" dot={false}>
                  {count(vaults.length, "memory", "memories")} · {count(totalNotes, "note", "notes")}
                </StatusPill>
                {tokens !== null ? (
                  <StatusPill tone={anyConnected ? "ok" : "neutral"}>
                    {connected.length > 0
                      ? `${count(connected.length, "AI app", "AI apps")} connected`
                      : signedInApp
                        ? "AI app connected"
                        : "No AI app connected yet"}
                  </StatusPill>
                ) : null}
                {toFile ? (
                  <StatusPill tone="info" title="Captured notes waiting to be sorted">
                    {count(toFile, "note", "notes")} to file
                  </StatusPill>
                ) : null}
                {index && index.pending > 0 ? (
                  <StatusPill tone="info">
                    Search index: {index.ready} of {index.ready + index.pending} notes ready
                  </StatusPill>
                ) : null}
              </div>
            ) : null}
            {problemComponents.length > 0 && (verdict.tone === "warn" || verdict.tone === "error") ? (
              <div style={{ marginTop: "var(--space-3)" }}>
                <Disclosure summary="Details">
                  <ul>
                    {problemComponents.map(([name, status]) => (
                      <li key={name}>
                        <span className="t-mono">{name}</span>: {status}
                      </li>
                    ))}
                  </ul>
                </Disclosure>
              </div>
            ) : null}
          </div>
        </div>
        {primary ? <div className="verdict__aside">{primary}</div> : null}
      </section>

      {vaults === null && !vaultsError && !unreachable ? <LoadingState label="Loading your overview…" /> : null}

      {setup?.restart_required ? <RestartCallout supported={setup.restart_supported} /> : null}

      {showCelebration ? (
        <div data-testid="first-memory-celebration">
          <Callout
            tone="ok"
            title={`First note saved — setup took ${spokenDuration(funnel?.time_to_first_memory_display ?? "")}.`}
            actions={
              <Button
                size="sm"
                variant="plain"
                onClick={() => {
                  writeFlag(CELEBRATION_KEY);
                  setCelebrationSeen(true);
                }}
              >
                Dismiss
              </Button>
            }
          >
            Measured from install to an AI app's first saved note. The time stays on this server.
          </Callout>
        </div>
      ) : null}

      {hasVaults ? (
        <div className="overview-cards">
          <Card>
            <CardHeader
              title="Memories"
              actions={
                toFile ? (
                  <StatusPill tone="info" title="Captured notes waiting to be sorted">
                    {toFile} to file
                  </StatusPill>
                ) : undefined
              }
            />
            {(vaults ?? []).slice(0, 3).map((vault) => (
              <ListRow
                key={vault.key}
                icon={<VaultsIcon className="icon" />}
                title={vault.key}
                description={count(vault.note_count, "note", "notes")}
              />
            ))}
            <div className="card__foot">
              <Link to="/memories">Open Memories</Link>
            </div>
          </Card>

          <Card>
            <CardHeader
              title="AI apps"
              actions={
                tokens !== null ? (
                  <span className="t-meta">
                    {signedInApp ? "Connected" : `${connected.length} connected`}
                  </span>
                ) : undefined
              }
            />
            {tokens === null ? (
              <InlineEmpty>Loading…</InlineEmpty>
            ) : activeTokens.length === 0 && !signedInApp ? (
              <InlineEmpty>No AI app connected yet.</InlineEmpty>
            ) : (
              <>
                {signedInApp ? (
                  <ListRow
                    icon={<ClientsIcon className="icon" />}
                    title="Apps that sign in"
                    description="Connected with your palaia account"
                    trailing={<StatusPill tone="ok">Connected</StatusPill>}
                  />
                ) : null}
                {activeTokens.slice(0, 3).map((token) => (
                  <ListRow
                    key={token.id}
                    icon={<ClientsIcon className="icon" />}
                    title={token.name}
                    description={
                      token.last_used_at ? (
                        <span title={exactTime(token.last_used_at)}>
                          Last request {timeAgo(token.last_used_at)}
                        </span>
                      ) : (
                        "Access key created, no request yet"
                      )
                    }
                    trailing={
                      token.last_used_at ? (
                        <StatusPill tone="ok">Connected</StatusPill>
                      ) : (
                        <StatusPill tone="info">Waiting for first use</StatusPill>
                      )
                    }
                  />
                ))}
              </>
            )}
            <div className="card__foot">
              <Link to="/apps">Open AI apps</Link>
            </div>
          </Card>

          <Card>
            <CardHeader
              title="Backup"
              actions={
                backup.tone === "ok" ? (
                  <StatusPill tone="ok">Backed up</StatusPill>
                ) : backup.tone === "error" ? (
                  <StatusPill tone="error">Failed</StatusPill>
                ) : backup.tone === "warn" ? (
                  <StatusPill tone="warn">Needs sign-in</StatusPill>
                ) : undefined
              }
            />
            <div className="card__body">
              <p className="t-muted">{backup.line}</p>
            </div>
            <div className="card__foot">
              <Link to="/settings/backups">Open Backups</Link>
            </div>
          </Card>
        </div>
      ) : null}

      {/* Nothing to say about activity while palaia can't be read: an
          empty feed there would claim "nothing happened". */}
      {unreachable || vaultsError ? null : (
        <Card>
          <CardHeader
            title="Activity"
            actions={
              stream.connection === "open" ? (
                <StatusPill tone="ok" title="New and changed notes appear here as they happen">
                  Live
                </StatusPill>
              ) : undefined
            }
          />
          {feed.length === 0 ? (
            <InlineEmpty>No activity yet. New and changed notes appear here.</InlineEmpty>
          ) : (
            <ul className="feed" aria-label="Recent activity">
              {feed.map((item) => (
                <li className="feed__item" key={item.key}>
                  <span className="feed__mark" aria-hidden="true">
                    <ExplorerIcon className="icon" />
                  </span>
                  <div className="grow">
                    <p className="feed__text">
                      {item.verb} <strong>{item.title}</strong>
                    </p>
                    <p className="feed__meta t-meta">
                      {[item.vault, item.at !== null ? timeAgo(item.at) : null].filter(Boolean).join(" · ")}
                    </p>
                  </div>
                </li>
              ))}
            </ul>
          )}
        </Card>
      )}
    </div>
  );
}
