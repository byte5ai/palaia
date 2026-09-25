/**
 * Issue 439: the Telegram screen — the owner's view of the connector.
 * ADR-006 names exactly this: "per bot: connection state, last update
 * received, routing table, recent deliveries — a dashboard panel", and
 * records the MASTERPLAN §4 rule-8 answer that it is a dashboard screen,
 * not an MCP App: this is system administration, and the conversation
 * itself already lives where the user is, in Telegram.
 *
 * Issue 463 made it the place the connector is *set up*, too — MASTERPLAN
 * P7: "no config-file editing as a required path". Bots, the rules that
 * decide where their messages go, and which tool profiles may send are
 * all edited here. Every save is written to the hub's config.yaml and
 * applied to the running hub at once; the answer is the new status, so
 * the screen shows what the hub now runs. A bot's token never passes
 * through the Telegram routes: it goes straight to the hub's write-only
 * secret store, under the name the bot carries.
 *
 * Metadata only. The hub keeps no message text (ADR-006: no message
 * store), so there is none here to show — "Recent messages" says which
 * bot, which chat and what happened, never what anyone wrote.
 *
 * Live via the hub's SSE bus (`stream.telegramActivityCount`, bumped on
 * every `telegram.*` event — `telegram.bot.state` included, which is what
 * turns a row red the moment its bot starts failing, and
 * `telegram.config.updated`, which brings a second tab along after an
 * edit; see ../lib/events.ts). No polling interval and no refresh button
 * (system.md §0). The status read never reaches Telegram; "Check
 * connection" is the one thing on this screen that does.
 */
import { useEffect, useId, useState } from "react";
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
  Field,
  LabeledInput,
  Segmented,
  Skeleton,
  SwitchRow,
  Table,
  useToast,
} from "../components";
import type {
  GatewayProfile,
  TelegramBotStatus,
  TelegramDestination,
  TelegramDestinationKind,
  TelegramGrant,
  TelegramMessageType,
  TelegramRecentMessage,
  TelegramRoute,
  TelegramRouteInput,
  TelegramStatus,
  TelegramTransport,
  TelegramUrgency,
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

/** The routing wildcard: every chat the bot receives from. */
const EVERY = "*";

function ago(seconds: number): string {
  if (Date.now() / 1000 - seconds < 5) return "just now";
  return formatAge(new Date(seconds * 1000).toISOString());
}

function exactly(seconds: number): string {
  return new Date(seconds * 1000).toLocaleString();
}

/** A save's failure in one line. A refused edit carries the hub's own
 * sentence (`detail`); a malformed one carries a list of field errors. */
function explain(err: unknown): string {
  if (err instanceof ApiError) {
    const detail = (err.body as { detail?: unknown } | undefined)?.detail;
    if (Array.isArray(detail)) {
      const lines = detail
        .map((item) =>
          typeof item === "object" && item !== null && "msg" in item
            ? String((item as { msg: unknown }).msg).replace(/^Value error, /, "")
            : "",
        )
        .filter(Boolean);
      if (lines.length > 0) return lines.join(" ");
    }
  }
  return describeApiError(err);
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
      title: "Switched off; its rules are kept.",
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

function chatLabel(chat: string): string {
  return chat === EVERY ? "every chat" : chat;
}

/** Remove, in two steps — the second one says what it does. */
function RemoveControl({
  label,
  confirmLabel,
  onConfirm,
}: {
  label: string;
  confirmLabel: string;
  onConfirm: () => Promise<void>;
}) {
  const [confirming, setConfirming] = useState(false);
  const [busy, setBusy] = useState(false);
  if (!confirming) {
    return (
      <Button variant="risk" size="sm" onClick={() => setConfirming(true)}>
        {label}
      </Button>
    );
  }
  return (
    <span className="row" style={{ gap: 6 }}>
      <Button
        variant="ghost"
        size="sm"
        onClick={() => setConfirming(false)}
        disabled={busy}
      >
        Keep it
      </Button>
      <Button
        variant="risk"
        size="sm"
        disabled={busy}
        onClick={async () => {
          setBusy(true);
          try {
            await onConfirm();
          } finally {
            setBusy(false);
            setConfirming(false);
          }
        }}
      >
        {confirmLabel}
      </Button>
    </span>
  );
}

// ---------------------------------------------------------------- bots

/** Add a bot, or change one. The token, when typed, goes to the secret
 * store under the name the bot carries — after the bot is saved, because
 * a new bot's name is only known once the hub has filed it. */
function BotEditor({
  bot,
  existingKeys,
  onSaved,
  onCancel,
}: {
  bot: TelegramBotStatus | null;
  existingKeys: Set<string>;
  onSaved: (status: TelegramStatus) => void;
  onCancel: () => void;
}) {
  const toast = useToast();
  const [key, setKey] = useState(bot?.key ?? "");
  const [label, setLabel] = useState(bot?.configured_label ?? "");
  const [transport, setTransport] = useState<TelegramTransport>(
    bot?.transport ?? "polling",
  );
  const [enabled, setEnabled] = useState(bot?.enabled ?? true);
  const [token, setToken] = useState("");
  const [echo, setEcho] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const cleanKey = key.trim().toLowerCase();
  const keyTaken = bot === null && existingKeys.has(cleanKey);

  async function save() {
    setSaving(true);
    setError(null);
    try {
      let status =
        bot === null
          ? await api.createTelegramBot({
              key: cleanKey,
              label: label.trim() || null,
              transport,
              enabled,
            })
          : await api.updateTelegramBot(bot.key, {
              label: label.trim() || null,
              transport,
              enabled,
            });
      const saved = status.bots.find((b) => b.key === (bot?.key ?? cleanKey));
      const stored: string[] = [];
      if (saved && token.trim()) {
        await api.storeSecret(saved.token_secret, token.trim());
        stored.push("token");
      }
      if (saved?.webhook_secret && echo.trim()) {
        await api.storeSecret(saved.webhook_secret, echo.trim());
        stored.push("delivery secret");
      }
      if (stored.length > 0) status = await api.telegramStatus();
      toast.show(
        stored.length > 0
          ? `Saved, and the ${stored.join(" and ")} stored. Check the connection to confirm Telegram accepts it.`
          : "Saved — the hub runs it now.",
      );
      onSaved(status);
    } catch (err) {
      setError(explain(err));
    } finally {
      setSaving(false);
    }
  }

  return (
    <CardBody className="stack stack--3">
      {bot === null ? (
        <LabeledInput
          label="Name on the hub"
          hint="Lowercase letters, digits, - or _. Rules and agents use it to pick this bot; it cannot be changed later."
          value={key}
          onChange={(event) => setKey(event.target.value)}
          invalid={keyTaken}
          error={keyTaken ? "A bot with this name already exists." : undefined}
        />
      ) : null}
      <LabeledInput
        label="Display name"
        placeholder={cleanKey || bot?.key}
        hint="Cosmetic only."
        value={label}
        onChange={(event) => setLabel(event.target.value)}
      />
      <Field
        label="How messages reach the hub"
        hint={
          transport === "polling"
            ? "The hub asks Telegram for new messages (long polling). Works behind a firewall and on a private hub."
            : "Telegram delivers each message to the hub's public address (a webhook). Needs a hub reachable from the internet."
        }
      >
        <Segmented<TelegramTransport>
          ariaLabel="How messages reach the hub"
          value={transport}
          onChange={setTransport}
          options={[
            { value: "polling", label: "The hub fetches them" },
            { value: "webhook", label: "Telegram sends them" },
          ]}
        />
      </Field>
      {bot !== null ? (
        <SwitchRow
          label="Switched on"
          consequence="Switched off, the bot receives and sends nothing; its rules are kept."
          checked={enabled}
          onChange={setEnabled}
        />
      ) : null}
      <LabeledInput
        label="Bot token"
        type="password"
        autoComplete="off"
        placeholder={
          bot?.token_stored ? "Stored — type a new one to replace it" : ""
        }
        hint={`From @BotFather. Stored encrypted in the hub's secret store${
          bot ? ` as ${bot.token_secret}` : ""
        } — never in config.yaml.${bot?.token_stored ? " Leave empty to keep the stored one." : ""}`}
        value={token}
        onChange={(event) => setToken(event.target.value)}
      />
      {transport === "webhook" ? (
        <LabeledInput
          label="Delivery secret"
          type="password"
          autoComplete="off"
          placeholder={
            bot?.webhook_secret_stored
              ? "Stored — type a new one to replace it"
              : ""
          }
          hint="A random value Telegram sends along with every message, so the hub can tell it apart from anyone else. Pass the same value as secret_token when you point the bot at this hub (setWebhook)."
          value={echo}
          onChange={(event) => setEcho(event.target.value)}
        />
      ) : null}
      {error ? <p className="field__error">{error}</p> : null}
      <div className="row row--wrap">
        <Button
          variant="primary"
          onClick={save}
          disabled={saving || (bot === null && (!cleanKey || keyTaken))}
        >
          {saving ? "Saving…" : bot === null ? "Add bot" : "Save"}
        </Button>
        <Button variant="ghost" onClick={onCancel} disabled={saving}>
          Cancel
        </Button>
      </div>
    </CardBody>
  );
}

function BotRow({
  bot,
  editable,
  editing,
  onEdit,
  onChecked,
  onSaved,
}: {
  bot: TelegramBotStatus;
  editable: boolean;
  editing: boolean;
  onEdit: (key: string | null) => void;
  onChecked: (bot: TelegramBotStatus) => void;
  onSaved: (status: TelegramStatus) => void;
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

  async function remove() {
    try {
      onSaved(await api.deleteTelegramBot(bot.key));
      toast.show(`${bot.label} removed.`);
    } catch (err) {
      toast.show(explain(err));
    }
  }

  return (
    <>
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
              {editable
                ? "Edit the bot to store its token, then check the connection."
                : "Store this bot's token in the hub's secret store, then check again."}
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
              {check.username
                ? ` — Telegram knows it as @${check.username}`
                : ""}
            </div>
          ) : null}
        </div>
        <div className="row row--wrap" style={{ gap: 8, alignItems: "center" }}>
          <span title={state.title}>
            <Badge variant={state.variant}>{state.label}</Badge>
          </span>
          {bot.enabled ? (
            <Button size="sm" onClick={runCheck} disabled={checking}>
              {checking ? "Checking…" : "Check connection"}
            </Button>
          ) : null}
          {editable && !editing ? (
            <Button size="sm" variant="ghost" onClick={() => onEdit(bot.key)}>
              Edit
            </Button>
          ) : null}
          {editable ? (
            <RemoveControl
              label="Remove"
              confirmLabel="Yes, remove the bot"
              onConfirm={remove}
            />
          ) : null}
        </div>
      </div>
      {editing ? (
        <BotEditor
          bot={bot}
          existingKeys={new Set()}
          onSaved={(status) => {
            onSaved(status);
            onEdit(null);
          }}
          onCancel={() => onEdit(null)}
        />
      ) : null}
    </>
  );
}

// -------------------------------------------------------------- routes

/** The rule being written: a fresh one (possibly started from a dropped
 * message), or an existing one addressed by its bot and chat. */
interface RouteDraft {
  original: { bot: string; chat: string } | null;
  bot: string;
  chat: string;
  destination: TelegramDestination;
}

const MESSAGE_TYPE_LABEL: Record<TelegramMessageType, string> = {
  inform: "For information",
  request: "A request",
  question: "A question",
  handoff: "A handoff",
  broadcast: "A broadcast",
};

const URGENCY_LABEL: Record<TelegramUrgency, string> = {
  low: "Low",
  normal: "Normal",
  high: "High",
};

function RouteEditor({
  draft,
  bots,
  vaults,
  messenger,
  onSaved,
  onCancel,
}: {
  draft: RouteDraft;
  bots: TelegramBotStatus[];
  vaults: string[];
  messenger: boolean;
  onSaved: (status: TelegramStatus) => void;
  onCancel: () => void;
}) {
  const toast = useToast();
  const botId = useId();
  const vaultId = useId();
  const typeId = useId();
  const urgencyId = useId();
  const [bot, setBot] = useState(draft.bot || bots[0]?.key || "");
  const [chat, setChat] = useState(draft.chat);
  const [kind, setKind] = useState<TelegramDestinationKind>(
    draft.destination.kind,
  );
  const [to, setTo] = useState(draft.destination.to ?? "");
  const [messageType, setMessageType] = useState<TelegramMessageType>(
    draft.destination.message_type ?? "inform",
  );
  const [urgency, setUrgency] = useState<TelegramUrgency>(
    draft.destination.urgency ?? "normal",
  );
  const [vault, setVault] = useState(
    draft.destination.vault ?? vaults[0] ?? "",
  );
  const [eventLabel, setEventLabel] = useState(draft.destination.label ?? "");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // A vault the rule names but the hub does not have (yet) stays choosable,
  // so editing such a rule never silently re-points it.
  const vaultChoices =
    vault && !vaults.includes(vault) ? [...vaults, vault] : vaults;

  function destination(): TelegramDestination {
    if (kind === "messenger") {
      return { kind, to: to.trim(), message_type: messageType, urgency };
    }
    if (kind === "inbox") return { kind, vault };
    return { kind, label: eventLabel.trim() || null };
  }

  async function save() {
    setSaving(true);
    setError(null);
    const body: TelegramRouteInput = {
      bot,
      chat: chat.trim() || EVERY,
      destination: destination(),
    };
    try {
      const status = draft.original
        ? await api.replaceTelegramRoute(
            draft.original.bot,
            draft.original.chat,
            body,
          )
        : await api.createTelegramRoute(body);
      toast.show("Rule saved — the next message follows it.");
      onSaved(status);
    } catch (err) {
      setError(explain(err));
    } finally {
      setSaving(false);
    }
  }

  const incomplete =
    !bot ||
    (kind === "messenger" && !to.trim()) ||
    (kind === "inbox" && !vault);

  return (
    <Card>
      <CardBody className="stack stack--3">
        <div className="row row--wrap" style={{ gap: 12, alignItems: "flex-start" }}>
          <Field label="Bot" controlId={botId}>
            <select
              id={botId}
              className="input"
              value={bot}
              onChange={(event) => setBot(event.target.value)}
            >
              {bots.map((b) => (
                <option key={b.key} value={b.key}>
                  {b.label}
                </option>
              ))}
            </select>
          </Field>
          <LabeledInput
            label="Chat"
            hint="A numeric chat id (e.g. -1001234567890), a public @name, or * for every chat this bot hears from that no other rule claims."
            value={chat}
            placeholder={EVERY}
            onChange={(event) => setChat(event.target.value)}
          />
        </div>
        <Field label="Where its messages go">
          <Segmented<TelegramDestinationKind>
            ariaLabel="Where its messages go"
            value={kind}
            onChange={setKind}
            options={[
              { value: "messenger", label: "An agent's inbox" },
              { value: "inbox", label: "A vault's inbox" },
              { value: "event", label: "A hub event" },
            ]}
          />
        </Field>
        {kind === "messenger" ? (
          <>
            <LabeledInput
              label="To"
              hint={
                messenger
                  ? "The agent's handle, or * for everyone — relayed as you, the owner."
                  : "This hub runs without a messenger, so a rule like this cannot deliver."
              }
              value={to}
              onChange={(event) => setTo(event.target.value)}
            />
            <div className="row row--wrap" style={{ gap: 12 }}>
              <Field label="Type" controlId={typeId}>
                <select
                  id={typeId}
                  className="input"
                  value={messageType}
                  onChange={(event) =>
                    setMessageType(event.target.value as TelegramMessageType)
                  }
                >
                  {Object.entries(MESSAGE_TYPE_LABEL).map(([value, text]) => (
                    <option key={value} value={value}>
                      {text}
                    </option>
                  ))}
                </select>
              </Field>
              <Field label="Priority" controlId={urgencyId}>
                <select
                  id={urgencyId}
                  className="input"
                  value={urgency}
                  onChange={(event) =>
                    setUrgency(event.target.value as TelegramUrgency)
                  }
                >
                  {Object.entries(URGENCY_LABEL).map(([value, text]) => (
                    <option key={value} value={value}>
                      {text}
                    </option>
                  ))}
                </select>
              </Field>
            </div>
          </>
        ) : null}
        {kind === "inbox" ? (
          <Field
            label="Vault"
            controlId={vaultId}
            hint="The message lands in the vault's inbox, waiting to be sorted."
          >
            {vaultChoices.length === 0 ? (
              <span className="t-sm t-muted">
                This hub has no vault yet — create one first.
              </span>
            ) : (
              <select
                id={vaultId}
                className="input"
                value={vault}
                onChange={(event) => setVault(event.target.value)}
              >
                {vaultChoices.map((key) => (
                  <option key={key} value={key}>
                    {key}
                  </option>
                ))}
              </select>
            )}
          </Field>
        ) : null}
        {kind === "event" ? (
          <LabeledInput
            label="Label"
            hint="Optional. Tells this rule's events apart from another's, so an automation can react to just these. The event carries the message text."
            value={eventLabel}
            onChange={(event) => setEventLabel(event.target.value)}
          />
        ) : null}
        {error ? <p className="field__error">{error}</p> : null}
        <div className="row row--wrap">
          <Button
            variant="primary"
            onClick={save}
            disabled={saving || incomplete}
          >
            {saving ? "Saving…" : "Save rule"}
          </Button>
          <Button variant="ghost" onClick={onCancel} disabled={saving}>
            Cancel
          </Button>
        </div>
      </CardBody>
    </Card>
  );
}

interface RouteRow extends TelegramRoute {
  id: string;
}

function RoutesTable({
  routes,
  labels,
  editable,
  onEdit,
  onSaved,
}: {
  routes: TelegramRoute[];
  labels: Map<string, string>;
  editable: boolean;
  onEdit: (route: TelegramRoute) => void;
  onSaved: (status: TelegramStatus) => void;
}) {
  const toast = useToast();
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
        route.chat === EVERY ? (
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
  if (editable) {
    columns.push({
      key: "actions",
      header: "",
      render: (route) => (
        <span className="row" style={{ gap: 6, justifyContent: "flex-end" }}>
          <Button size="sm" variant="ghost" onClick={() => onEdit(route)}>
            Edit
          </Button>
          <RemoveControl
            label="Remove"
            confirmLabel="Yes, remove the rule"
            onConfirm={async () => {
              try {
                onSaved(await api.deleteTelegramRoute(route.bot, route.chat));
                toast.show("Rule removed.");
              } catch (err) {
                toast.show(explain(err));
              }
            }}
          />
        </span>
      ),
    });
  }
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

// -------------------------------------------------------------- grants

/** `*` or a comma-separated list, as the grant stores it. */
function parseList(text: string): string[] {
  return text
    .split(",")
    .map((item) => item.trim())
    .filter(Boolean);
}

function GrantEditor({
  grant,
  bots,
  granted,
  onSaved,
  onCancel,
}: {
  grant: TelegramGrant | null;
  bots: TelegramBotStatus[];
  /** Profiles that already have an entry — offered for a new one no more. */
  granted: string[];
  onSaved: (status: TelegramStatus) => void;
  onCancel: () => void;
}) {
  const toast = useToast();
  const profileId = useId();
  const grantedKey = granted.join("\n");
  const [profiles, setProfiles] = useState<GatewayProfile[] | null>(null);
  const [profile, setProfile] = useState(grant?.profile ?? "");
  const [everyBot, setEveryBot] = useState(
    grant ? grant.bots.includes(EVERY) : true,
  );
  const [chosen, setChosen] = useState<Set<string>>(
    new Set(grant?.bots.filter((b) => b !== EVERY) ?? []),
  );
  const [chats, setChats] = useState(grant ? grant.chats.join(", ") : EVERY);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (grant) return;
    let cancelled = false;
    api
      .listGatewayProfiles()
      .then((list) => {
        if (cancelled) return;
        const taken = new Set(grantedKey.split("\n"));
        const open = list.filter((p) => !p.managed && !taken.has(p.path));
        setProfiles(open);
        setProfile((current) => current || open[0]?.path || "");
      })
      .catch(() => {
        if (!cancelled) setProfiles([]);
      });
    return () => {
      cancelled = true;
    };
  }, [grant, grantedKey]);

  const selected = profiles?.find((p) => p.path === profile);

  async function save() {
    setSaving(true);
    setError(null);
    try {
      const status = await api.putTelegramGrant(profile, {
        bots: everyBot ? [EVERY] : [...chosen],
        chats: parseList(chats),
      });
      toast.show("Saved — the profile's next send follows it.");
      onSaved(status);
    } catch (err) {
      setError(explain(err));
    } finally {
      setSaving(false);
    }
  }

  return (
    <Card>
      <CardBody className="stack stack--3">
        {grant ? (
          <p className="t-sm">
            Tool profile <span className="t-mono">{grant.profile}</span>
          </p>
        ) : (
          <Field
            label="Tool profile"
            controlId={profileId}
            hint={
              selected && !selected.telegram
                ? "This profile does not carry the Telegram tools yet — switch them on under Tool profiles, or it has nothing to send with."
                : "Its clients can send only where this says."
            }
          >
            {profiles === null ? (
              <span className="t-sm t-muted">Loading…</span>
            ) : profiles.length === 0 ? (
              <span className="t-sm t-muted">
                Every tool profile already has an entry.
              </span>
            ) : (
              <select
                id={profileId}
                className="input"
                value={profile}
                onChange={(event) => setProfile(event.target.value)}
              >
                {profiles.map((p) => (
                  <option key={p.path} value={p.path}>
                    {p.label ?? p.path}
                  </option>
                ))}
              </select>
            )}
          </Field>
        )}
        <div className="stack stack--2">
          <SwitchRow
            label="Through every bot"
            consequence="Including bots added later."
            checked={everyBot}
            onChange={setEveryBot}
          />
          {everyBot ? null : (
            <div className="stack stack--2">
              {bots.map((b) => (
                <label key={b.key} className="row" style={{ gap: 8 }}>
                  <input
                    type="checkbox"
                    checked={chosen.has(b.key)}
                    onChange={(event) =>
                      setChosen((prev) => {
                        const next = new Set(prev);
                        if (event.target.checked) next.add(b.key);
                        else next.delete(b.key);
                        return next;
                      })
                    }
                  />
                  <span className="t-sm">{b.label}</span>
                </label>
              ))}
              {chosen.size === 0 ? (
                <span className="t-xs t-muted">
                  No bot chosen: this profile can send nothing.
                </span>
              ) : null}
            </div>
          )}
        </div>
        <LabeledInput
          label="To these chats"
          hint="* for every chat, or chat ids and @names separated by commas. Empty: none."
          value={chats}
          onChange={(event) => setChats(event.target.value)}
        />
        {error ? <p className="field__error">{error}</p> : null}
        <div className="row row--wrap">
          <Button
            variant="primary"
            onClick={save}
            disabled={saving || !profile}
          >
            {saving ? "Saving…" : "Save"}
          </Button>
          <Button variant="ghost" onClick={onCancel} disabled={saving}>
            Cancel
          </Button>
        </div>
      </CardBody>
    </Card>
  );
}

function listLabel(items: string[], every: string, none: string): string {
  if (items.includes(EVERY)) return every;
  if (items.length === 0) return none;
  return items.join(", ");
}

function GrantRow({
  grant,
  labels,
  editable,
  onEdit,
  onSaved,
}: {
  grant: TelegramGrant;
  labels: Map<string, string>;
  editable: boolean;
  onEdit: () => void;
  onSaved: (status: TelegramStatus) => void;
}) {
  const toast = useToast();
  const bots = grant.bots.includes(EVERY)
    ? grant.bots
    : grant.bots.map((b) => labels.get(b) ?? b);
  return (
    <div className="listrow">
      <div style={{ flex: 1, minWidth: 0 }}>
        <div className="listrow__title t-mono">{grant.profile}</div>
        <div className="listrow__meta">
          Through {listLabel(bots, "every bot", "no bot")}, to{" "}
          {listLabel(grant.chats, "every chat", "no chat")}
        </div>
      </div>
      {editable ? (
        <div className="row row--wrap" style={{ gap: 8 }}>
          <Button size="sm" variant="ghost" onClick={onEdit}>
            Edit
          </Button>
          <RemoveControl
            label="Remove"
            confirmLabel="Yes, stop it sending"
            onConfirm={async () => {
              try {
                onSaved(await api.deleteTelegramGrant(grant.profile));
                toast.show(`${grant.profile} can no longer send.`);
              } catch (err) {
                toast.show(explain(err));
              }
            }}
          />
        </div>
      ) : null}
    </div>
  );
}

// ------------------------------------------------------ recent messages

function RecentRow({
  entry,
  labels,
  editable,
  onCreateRule,
}: {
  entry: TelegramRecentMessage;
  labels: Map<string, string>;
  editable: boolean;
  onCreateRule: (bot: string, chat: string) => void;
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
            chats would catch the next one
            {editable ? " — pick one to write it:" : ":"}
          </p>
          <div className="row row--wrap" style={{ gap: 6 }}>
            {(entry.candidates ?? []).map((key) =>
              editable ? (
                <Button
                  key={key}
                  size="sm"
                  title={`Create a rule for ${chatLabel(key)}`}
                  onClick={() => onCreateRule(entry.bot, key)}
                >
                  <Chip mono>{key}</Chip>
                </Button>
              ) : (
                <Chip key={key} mono>
                  {key}
                </Chip>
              ),
            )}
          </div>
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------- screen

export function Telegram() {
  const stream = useOutletContext<EventStreamState>();
  const [status, setStatus] = useState<TelegramStatus | null>(null);
  const [error, setError] = useState<string | null>(null);
  /** `""` = the new-bot form; a key = that bot's; `null` = none open. */
  const [editingBot, setEditingBot] = useState<string | null>(null);
  const [routeDraft, setRouteDraft] = useState<RouteDraft | null>(null);
  /** `""` = the new-grant form; a profile = that grant's. */
  const [editingGrant, setEditingGrant] = useState<string | null>(null);

  function refresh() {
    api
      .telegramStatus()
      .then((next) => {
        setStatus(next);
        setError(null);
      })
      .catch((err) => setError(describeApiError(err)));
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

  const bots = status?.bots ?? [];
  const labels = new Map(bots.map((bot) => [bot.key, bot.label]));
  const editable = status?.editable ?? false;

  function startRule(bot: string, chat: string) {
    setRouteDraft({
      original: null,
      bot,
      chat,
      destination: status?.vaults.length
        ? { kind: "inbox", vault: status.vaults[0] }
        : { kind: "event" },
    });
    // The editor opens above the rules; bring it into view.
    requestAnimationFrame(() =>
      document
        .getElementById("telegram-rules")
        ?.scrollIntoView?.({ behavior: "smooth", block: "start" }),
    );
  }

  const intro = editable
    ? "Your Telegram bots, where their messages go, and who may send through them — every change is saved to the hub and applies at once, no restart."
    : "Your Telegram bots, where their messages go, and what happened to the last ones — updates live.";

  return (
    <section className="stack stack--4">
      <p className="t-sm t-muted" style={{ maxWidth: 620 }}>
        {intro} Only which chat and where a message went is kept, never what
        it said, and the list of recent messages starts over when the hub
        restarts. New to this? The{" "}
        <a href={SETUP_GUIDE_URL} target="_blank" rel="noreferrer">
          setup guide
        </a>{" "}
        walks through creating a bot.
      </p>

      {error ? (
        <div className="banner banner--warn">
          <p className="t-sm t-muted">{error}</p>
        </div>
      ) : null}

      {status && status.warnings.length > 0 ? (
        <div className="banner banner--warn stack stack--2">
          {status.warnings.map((warning) => (
            <p key={warning} className="t-sm t-muted">
              {warning}
            </p>
          ))}
        </div>
      ) : null}

      <div className="stack stack--2">
        <div className="row row--between">
          <span className="field__label">Bots</span>
          {editable && editingBot !== "" ? (
            <Button size="sm" onClick={() => setEditingBot("")}>
              Add a bot
            </Button>
          ) : null}
        </div>
        {editingBot === "" ? (
          <Card>
            <BotEditor
              bot={null}
              existingKeys={new Set(bots.map((b) => b.key))}
              onSaved={(next) => {
                setStatus(next);
                setEditingBot(null);
              }}
              onCancel={() => setEditingBot(null)}
            />
          </Card>
        ) : null}
        {status === null ? (
          error ? null : (
            <Skeleton height={60} />
          )
        ) : bots.length === 0 ? (
          editingBot === "" ? null : (
            <EmptyState
              mark={<TelegramIcon className="icon--lg" />}
              title="No bots yet."
            >
              {editable
                ? "Create a bot with @BotFather in Telegram, then add it here with its token."
                : "Add a bot under telegram.bots in config.yaml and restart the hub to see it here."}
            </EmptyState>
          )
        ) : (
          <Card>
            {bots.map((bot) => (
              <BotRow
                key={bot.key}
                bot={bot}
                editable={editable}
                editing={editingBot === bot.key}
                onEdit={setEditingBot}
                onChecked={replaceBot}
                onSaved={setStatus}
              />
            ))}
          </Card>
        )}
      </div>

      <div className="stack stack--2" id="telegram-rules">
        <div className="row row--between">
          <span className="field__label">Where messages go</span>
          {editable && bots.length > 0 && routeDraft === null ? (
            <Button size="sm" onClick={() => startRule(bots[0].key, EVERY)}>
              Add a rule
            </Button>
          ) : null}
        </div>
        {routeDraft !== null && status !== null ? (
          <RouteEditor
            key={`${routeDraft.original?.bot ?? ""}/${routeDraft.original?.chat ?? ""}/${routeDraft.bot}/${routeDraft.chat}`}
            draft={routeDraft}
            bots={bots}
            vaults={status.vaults}
            messenger={status.messenger}
            onSaved={(next) => {
              setStatus(next);
              setRouteDraft(null);
            }}
            onCancel={() => setRouteDraft(null)}
          />
        ) : null}
        {status === null ? (
          error ? null : (
            <Skeleton height={60} />
          )
        ) : status.routes.length === 0 ? (
          <EmptyState
            mark={<TelegramIcon className="icon--lg" />}
            title="No rules yet."
          >
            {editable
              ? "Without a rule, every message a bot receives is dropped. Add one — or send the bot a message and write the rule from it under Recent messages."
              : "Without a rule, every message a bot receives is dropped. Add one under telegram.routes in config.yaml and restart the hub."}
          </EmptyState>
        ) : (
          <RoutesTable
            routes={status.routes}
            labels={labels}
            editable={editable}
            onEdit={(route) =>
              setRouteDraft({
                original: { bot: route.bot, chat: route.chat },
                bot: route.bot,
                chat: route.chat,
                destination: route.target,
              })
            }
            onSaved={setStatus}
          />
        )}
      </div>

      <div className="stack stack--2">
        <div className="row row--between">
          <span className="field__label">Who may send</span>
          {editable && editingGrant === null ? (
            <Button size="sm" onClick={() => setEditingGrant("")}>
              Let a profile send
            </Button>
          ) : null}
        </div>
        <p className="t-xs t-muted" style={{ maxWidth: 620 }}>
          Agents send through the Telegram tools of their tool profile. A
          profile with no entry here can send nothing at all; the curator
          never can.
        </p>
        {editingGrant === "" && status !== null ? (
          <GrantEditor
            grant={null}
            bots={bots}
            granted={status.grants.map((g) => g.profile)}
            onSaved={(next) => {
              setStatus(next);
              setEditingGrant(null);
            }}
            onCancel={() => setEditingGrant(null)}
          />
        ) : null}
        {status === null ? (
          error ? null : (
            <Skeleton height={60} />
          )
        ) : status.grants.length === 0 ? (
          editingGrant === "" ? null : (
            <EmptyState
              mark={<TelegramIcon className="icon--lg" />}
              title="No profile may send yet."
            >
              Messages still arrive; only sending is off until a tool profile
              is let through.
            </EmptyState>
          )
        ) : (
          <Card>
            {status.grants.map((grant) =>
              editingGrant === grant.profile ? (
                <GrantEditor
                  key={grant.profile}
                  grant={grant}
                  bots={bots}
                  granted={[]}
                  onSaved={(next) => {
                    setStatus(next);
                    setEditingGrant(null);
                  }}
                  onCancel={() => setEditingGrant(null)}
                />
              ) : (
                <GrantRow
                  key={grant.profile}
                  grant={grant}
                  labels={labels}
                  editable={editable}
                  onEdit={() => setEditingGrant(grant.profile)}
                  onSaved={setStatus}
                />
              ),
            )}
          </Card>
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
                editable={editable}
                onCreateRule={startRule}
              />
            ))}
          </Card>
        )}
      </div>
    </section>
  );
}
