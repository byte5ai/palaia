/**
 * Issue 439: the Telegram screen — the owner's view of the connector.
 * ADR-006 names exactly this: "per bot: connection state, last update
 * received, routing table, recent deliveries — a dashboard panel", and
 * records the MASTERPLAN §4 rule-8 answer that it is a dashboard screen,
 * not an MCP App: this is system administration, and the conversation
 * itself already lives where the user is, in Telegram.
 *
 * Metadata only. The hub keeps no message text (ADR-006: no message
 * store), so there is none here to show — "Recent messages" says which
 * bot, which chat and what happened, never what anyone wrote.
 *
 * Live via the hub's SSE bus (`stream.telegramActivityCount`, bumped on
 * every `telegram.*` event — `telegram.bot.state` included, which is what
 * turns a row red the moment its bot starts failing; see ../lib/events.ts).
 * No polling interval and no refresh button (system.md §0). The status
 * read never reaches Telegram; "Check connection" is the one thing on this
 * screen that does.
 */
import { useEffect, useState } from "react";
import { useOutletContext } from "react-router-dom";

import type { BadgeVariant, Column } from "../components";
import {
  Badge,
  Button,
  Card,
  CardBody,
  Chip,
  Dot,
  EmptyState,
  Skeleton,
  Table,
  useToast,
} from "../components";
import type {
  TelegramBotStatus,
  TelegramRecentMessage,
  TelegramRoute,
  TelegramStatus,
} from "../lib/api/client";
import { api, ApiError } from "../lib/api/client";
import { describeApiError } from "../lib/errors";
import type { EventStreamState } from "../lib/events";
import { formatAge } from "../lib/format";
import {
  AGENT_REFRESH_COALESCE_MS,
  useDebouncedValue,
} from "../lib/useDebouncedValue";
import { TelegramIcon } from "../shell/icons";

/** The connector's own guide — there is no docs-site page for it yet. */
const SETUP_GUIDE_URL =
  "https://github.com/byte5ai/palaia/blob/main/v3/docs/telegram.md";

function ago(seconds: number): string {
  if (Date.now() / 1000 - seconds < 5) return "just now";
  return formatAge(new Date(seconds * 1000).toISOString());
}

function exactly(seconds: number): string {
  return new Date(seconds * 1000).toLocaleString();
}

interface BotState {
  variant: BadgeVariant;
  label: string;
  title: string;
  /** The failure to show under the row, when there is one. */
  error: string | null;
}

/** One badge per bot, from what the hub reports. A live poll failure
 * outranks everything; a failed check counts until a poll succeeds after
 * it. */
function botState(bot: TelegramBotStatus): BotState {
  if (!bot.enabled) {
    return {
      variant: "warn",
      label: "Disabled",
      title: "Switched off in config.yaml (enabled: false); its rules are kept.",
      error: null,
    };
  }
  if (!bot.token_stored) {
    return {
      variant: "risk",
      label: "Token missing",
      title: "The hub's secret store holds no bot token for this bot yet.",
      error: null,
    };
  }
  const polling = bot.polling;
  const check = bot.last_check;
  if (polling && polling.consecutive_failures > 0) {
    return {
      variant: "risk",
      label: "Failing",
      title: `${polling.consecutive_failures} failed attempts in a row — the hub keeps retrying.`,
      error: polling.last_error,
    };
  }
  const pollAfterCheck =
    polling?.last_ok_at != null &&
    check != null &&
    polling.last_ok_at > check.checked_at;
  if (check && !check.ok && !pollAfterCheck) {
    return {
      variant: "risk",
      label: "Failing",
      title: "The last connection check failed.",
      error: check.error,
    };
  }
  if (polling?.last_ok_at != null || check?.ok) {
    return {
      variant: "ok",
      label: "Connected",
      title: "Telegram answered this bot recently.",
      error: null,
    };
  }
  return {
    variant: "warn",
    label: "Not checked yet",
    title: "Nothing has reached Telegram for this bot since the hub started.",
    error: null,
  };
}

function receiveTitle(bot: TelegramBotStatus): string {
  return bot.transport === "webhook"
    ? "Webhook: Telegram delivers this bot's messages to the hub's public address."
    : "Long polling: the hub asks Telegram for this bot's messages, so it works behind a firewall.";
}

/** A route's destination in plain words — the hub's own `describe()` is
 * `messenger:<to>`, `inbox:<vault>` or `event`. */
function destinationLabel(destination: string | null): string {
  if (!destination) return "nowhere";
  if (destination.startsWith("messenger:")) {
    return `Messenger → ${destination.slice("messenger:".length)}`;
  }
  if (destination.startsWith("inbox:")) {
    return `Inbox of vault ${destination.slice("inbox:".length)}`;
  }
  return "Hub event";
}

function destinationTitle(destination: string | null): string | undefined {
  if (destination === "event") {
    return "Published on the hub's event stream, text included — automations can react to it.";
  }
  return undefined;
}

function BotRow({
  bot,
  onChecked,
}: {
  bot: TelegramBotStatus;
  onChecked: (bot: TelegramBotStatus) => void;
}) {
  const toast = useToast();
  const [checking, setChecking] = useState(false);
  const state = botState(bot);
  const check = bot.last_check;

  async function runCheck() {
    setChecking(true);
    try {
      onChecked(await api.checkTelegramBot(bot.key));
    } catch (err) {
      toast.show(describeApiError(err));
    } finally {
      setChecking(false);
    }
  }

  return (
    <div className="listrow">
      <div style={{ flex: 1, minWidth: 0 }}>
        <div className="listrow__title">{bot.label}</div>
        <div className="listrow__meta t-mono" title={receiveTitle(bot)}>
          {bot.key}
        </div>
        <div className="listrow__meta">
          {bot.last_update_at != null ? (
            <span title={exactly(bot.last_update_at)}>
              Last message received {ago(bot.last_update_at)}
            </span>
          ) : (
            "No message received since the hub started"
          )}
        </div>
        {bot.enabled && !bot.token_stored ? (
          <div className="listrow__meta t-muted">
            Store this bot&apos;s token in the hub&apos;s secret store, then
            check again.
          </div>
        ) : null}
        {bot.webhook_secret_stored === false ? (
          <div className="listrow__meta t-muted">
            Cannot receive yet: the secret Telegram sends along with each
            message is not stored on the hub.
          </div>
        ) : null}
        {state.error ? (
          <div className="listrow__meta t-muted">{state.error}</div>
        ) : null}
        {check?.ok ? (
          <div className="listrow__meta" title={exactly(check.checked_at)}>
            Checked {ago(check.checked_at)}
            {check.username ? ` — Telegram knows it as @${check.username}` : ""}
          </div>
        ) : null}
      </div>
      <div className="row" style={{ gap: 8, alignItems: "center" }}>
        <span title={state.title}>
          <Badge variant={state.variant}>{state.label}</Badge>
        </span>
        {bot.enabled ? (
          <Button size="sm" onClick={runCheck} disabled={checking}>
            {checking ? "Checking…" : "Check connection"}
          </Button>
        ) : null}
      </div>
    </div>
  );
}

interface RouteRow extends TelegramRoute {
  id: string;
}

function RoutesTable({
  routes,
  labels,
}: {
  routes: TelegramRoute[];
  labels: Map<string, string>;
}) {
  const columns: Column<RouteRow>[] = [
    {
      key: "bot",
      header: "Bot",
      render: (route) => labels.get(route.bot) ?? route.bot,
    },
    {
      key: "chat",
      header: "Chat",
      render: (route) =>
        route.chat === "*" ? (
          "every chat"
        ) : (
          <span className="t-mono">{route.chat}</span>
        ),
    },
    {
      key: "destination",
      header: "Goes to",
      render: (route) => (
        <span title={destinationTitle(route.destination)}>
          {destinationLabel(route.destination)}
        </span>
      ),
    },
  ];
  return (
    <Table
      caption="Where each bot's messages go"
      columns={columns}
      rows={routes.map((route) => ({
        ...route,
        id: `${route.bot}/${route.chat}`,
      }))}
    />
  );
}

function RecentRow({
  entry,
  labels,
}: {
  entry: TelegramRecentMessage;
  labels: Map<string, string>;
}) {
  const chat = entry.chat_username
    ? `@${entry.chat_username}`
    : String(entry.chat_id);
  return (
    <div
      className="listrow"
      style={{ flexDirection: "column", alignItems: "stretch", gap: 6 }}
    >
      <div>
        <div className="listrow__title">
          {labels.get(entry.bot) ?? entry.bot} ·{" "}
          <span className="t-mono" title={`Chat type: ${entry.chat_type}`}>
            {chat}
          </span>
        </div>
        <div className="listrow__meta">
          <span title={exactly(entry.at)}>{ago(entry.at)}</span> ·{" "}
          {entry.text_chars} characters
        </div>
      </div>
      {entry.delivered ? (
        <p className="t-sm t-muted">
          <Dot variant="ok" /> Delivered to{" "}
          <span title={destinationTitle(entry.destination)}>
            {destinationLabel(entry.destination)}
          </span>
        </p>
      ) : entry.routed ? (
        <p className="t-sm t-muted">
          <Dot variant="risk" /> Not delivered — {entry.detail}
        </p>
      ) : (
        <div className="stack stack--2">
          <p className="t-sm t-muted">
            <Dot variant="warn" /> No rule matched. A rule for any of these
            chats would catch the next one:
          </p>
          <div className="row row--wrap" style={{ gap: 6 }}>
            {(entry.candidates ?? []).map((key) => (
              <Chip key={key} mono>
                {key}
              </Chip>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

export function Telegram() {
  const stream = useOutletContext<EventStreamState>();
  const [status, setStatus] = useState<TelegramStatus | null>(null);
  const [configured, setConfigured] = useState(true);
  const [error, setError] = useState<string | null>(null);

  function refresh() {
    api
      .telegramStatus()
      .then((next) => {
        setStatus(next);
        setConfigured(true);
        setError(null);
      })
      .catch((err) => {
        if (err instanceof ApiError && err.status === 404) {
          setConfigured(false);
          return;
        }
        setError(describeApiError(err));
      });
  }

  function replaceBot(updated: TelegramBotStatus) {
    setStatus((prev) =>
      prev
        ? {
            ...prev,
            bots: prev.bots.map((bot) =>
              bot.key === updated.key ? updated : bot,
            ),
          }
        : prev,
    );
  }

  // No polling loop: once on mount, then once per burst of telegram.*
  // events — the same coalescing the Agents screen uses (issue 384).
  const activity = useDebouncedValue(
    stream.telegramActivityCount ?? 0,
    AGENT_REFRESH_COALESCE_MS,
  );
  useEffect(() => {
    refresh();
  }, [activity]);

  if (!configured) {
    return (
      <section className="stack stack--4">
        <Card>
          <CardBody>
            <p className="t-sm t-muted" style={{ maxWidth: 620 }}>
              This hub has no Telegram bots set up yet. To connect one, add a{" "}
              <span className="t-mono">telegram:</span> section to its
              config.yaml and restart the hub — the{" "}
              <a href={SETUP_GUIDE_URL} target="_blank" rel="noreferrer">
                setup guide
              </a>{" "}
              walks you through it.
            </p>
          </CardBody>
        </Card>
      </section>
    );
  }

  const labels = new Map(
    (status?.bots ?? []).map((bot) => [bot.key, bot.label]),
  );

  return (
    <section className="stack stack--4">
      <p className="t-sm t-muted" style={{ maxWidth: 620 }}>
        Your Telegram bots, where their messages go, and what happened to the
        last ones — updates live. Only which chat and where a message went is
        kept, never what it said, and the list starts over when the hub
        restarts.
      </p>

      {error ? (
        <div className="banner banner--warn">
          <p className="t-sm t-muted">{error}</p>
        </div>
      ) : null}

      <div className="stack stack--2">
        <span className="field__label">Bots</span>
        {status === null ? (
          error ? null : (
            <Skeleton height={60} />
          )
        ) : status.bots.length === 0 ? (
          <EmptyState
            mark={<TelegramIcon className="icon--lg" />}
            title="No bots yet."
          >
            Add a bot under telegram.bots in config.yaml and restart the hub to
            see it here.
          </EmptyState>
        ) : (
          <Card>
            {status.bots.map((bot) => (
              <BotRow key={bot.key} bot={bot} onChecked={replaceBot} />
            ))}
          </Card>
        )}
      </div>

      <div className="stack stack--2">
        <span className="field__label">Where messages go</span>
        {status === null ? (
          error ? null : (
            <Skeleton height={60} />
          )
        ) : status.routes.length === 0 ? (
          <EmptyState
            mark={<TelegramIcon className="icon--lg" />}
            title="No rules yet."
          >
            Without a rule, every message a bot receives is dropped. Add one
            under telegram.routes in config.yaml and restart the hub.
          </EmptyState>
        ) : (
          <RoutesTable routes={status.routes} labels={labels} />
        )}
      </div>

      <div className="stack stack--2">
        <span className="field__label">Recent messages</span>
        {status === null ? (
          error ? null : (
            <Skeleton height={60} />
          )
        ) : status.recent.length === 0 ? (
          <EmptyState
            mark={<TelegramIcon className="icon--lg" />}
            title="No messages yet."
          >
            Messages your bots receive show up here, newest first. Send one to
            a bot to see where it goes.
          </EmptyState>
        ) : (
          <Card>
            {status.recent.map((entry, index) => (
              <RecentRow
                key={`${entry.bot}/${entry.chat_id}/${entry.message_id}/${index}`}
                entry={entry}
                labels={labels}
              />
            ))}
          </Card>
        )}
      </div>
    </section>
  );
}
