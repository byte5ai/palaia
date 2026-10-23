/**
 * AI apps › Live sessions (SPEC-405): the AI sessions that registered with
 * palaia, and the messages moving between them.
 *
 * MASTERPLAN §5.4 trust rule #7: "the human can read along, join in, or
 * shut a conversation down." This tab is "read along" (always, live, no
 * reload); "Send a message" is "join in"; "End conversation" and "Remove"
 * are "shut down". Destructive controls stay in the dashboard (SPEC-304);
 * the session-monitor MCP App only links back here for them.
 *
 * Live updates ride the hub's event stream (`stream.agentActivityCount`,
 * bumped on every `session.*`/`message.*` event — see ../lib/events.ts);
 * there is no polling interval in this file.
 */
import { useCallback, useEffect, useId, useState } from "react";
import { useOutletContext } from "react-router-dom";

import "./apps.css";

import {
  Button,
  Card,
  CardHeader,
  Chip,
  ConfirmDialog,
  Dialog,
  ErrorState,
  Field,
  InlineEmpty,
  ListRow,
  LoadingState,
  Skeleton,
  StatusPill,
  useToast,
} from "../components";
import type { StatusTone } from "../components";
import type {
  EnvelopeMetadata,
  MessageType,
  SearchHit,
  SessionRecord,
  Urgency,
  VaultSummary,
} from "../lib/api/client";
import { api } from "../lib/api/client";
import { describeApiError } from "../lib/errors";
import type { EventStreamState } from "../lib/events";
import { count, exactTime, timeAgo } from "../lib/format";
import { AGENT_REFRESH_COALESCE_MS, useDebouncedValue } from "../lib/useDebouncedValue";

const MAX_BODY_BYTES = 4096;

const TYPE_LABEL: Record<MessageType, string> = {
  request: "Request",
  inform: "Update",
  question: "Question",
  handoff: "Handoff",
  broadcast: "Announcement to everyone",
};

const URGENCY_LABEL: Record<Urgency, string> = {
  low: "Low",
  normal: "Normal",
  high: "High",
};

const SESSION_STATUS: Record<SessionRecord["status"], { tone: StatusTone; label: string }> = {
  active: { tone: "ok", label: "Active" },
  idle: { tone: "neutral", label: "Idle" },
  stale: { tone: "warn", label: "Inactive" },
};

const MESSAGE_STATE: Record<EnvelopeMetadata["state"], { tone: StatusTone; label: string }> = {
  pending: { tone: "info", label: "Waiting" },
  delivered: { tone: "neutral", label: "Delivered" },
  acked: { tone: "ok", label: "Done" },
};

function byteLength(text: string): number {
  return new TextEncoder().encode(text).length;
}

function SessionRow({ session, onRemoved }: { session: SessionRecord; onRemoved: () => void }) {
  const toast = useToast();
  const [confirming, setConfirming] = useState(false);
  const [busy, setBusy] = useState(false);
  const status = SESSION_STATUS[session.status];
  const seen = session.last_seen_at * 1000;

  async function remove() {
    setBusy(true);
    try {
      await api.deregisterSession(session.handle);
      toast.show(`${session.handle} removed from the list.`);
      onRemoved();
    } catch (err) {
      toast.show(describeApiError(err));
    } finally {
      setBusy(false);
      setConfirming(false);
    }
  }

  return (
    <>
      <ListRow
        title={<span className="t-mono">{session.handle}</span>}
        description={session.scope || "No task reported"}
        meta={
          <span title={exactTime(seen)}>
            {session.platform || "Unknown app"}
            {session.model ? ` · ${session.model}` : ""} · seen {timeAgo(seen)}
          </span>
        }
        trailing={
          <>
            <StatusPill tone={status.tone}>{status.label}</StatusPill>
            <Button size="sm" variant="destructive" onClick={() => setConfirming(true)} disabled={busy}>
              Remove
            </Button>
          </>
        }
      />
      <ConfirmDialog
        open={confirming}
        onCancel={() => setConfirming(false)}
        onConfirm={() => void remove()}
        title={`Remove ${session.handle} from the list?`}
        confirmLabel="Remove session"
        destructive
        busy={busy}
      >
        <p>If the session is still running, it shows up again the next time it checks in.</p>
      </ConfirmDialog>
    </>
  );
}

function MessageRow({ flow, onEnded }: { flow: EnvelopeMetadata; onEnded: () => void }) {
  const toast = useToast();
  const [open, setOpen] = useState(false);
  const [body, setBody] = useState<string | null>(null);
  const [loadingBody, setLoadingBody] = useState(false);
  const [ending, setEnding] = useState(false);
  const [confirmEnd, setConfirmEnd] = useState(false);
  const state = MESSAGE_STATE[flow.state];
  const bodyId = useId();

  async function toggle() {
    const next = !open;
    setOpen(next);
    if (next && body === null) {
      setLoadingBody(true);
      try {
        const detail = await api.envelopeDetail(flow.id);
        setBody(detail.item.envelope.body);
      } catch {
        setBody("Couldn't load this message.");
      } finally {
        setLoadingBody(false);
      }
    }
  }

  async function end() {
    setEnding(true);
    try {
      const result = await api.endConversation(flow.id);
      const n = result.expired.length;
      toast.show(
        n === 0
          ? "Nothing in this conversation was still waiting."
          : `Conversation ended. ${count(n, "unread message", "unread messages")} won't be delivered.`,
      );
      onEnded();
    } catch (err) {
      toast.show(describeApiError(err));
    } finally {
      setEnding(false);
      setConfirmEnd(false);
    }
  }

  return (
    <div className="listrow" style={{ flexDirection: "column", alignItems: "stretch" }}>
      <button
        type="button"
        className="message-toggle"
        onClick={toggle}
        aria-expanded={open}
        aria-controls={bodyId}
      >
        <span className="listrow__main">
          <span className="listrow__title">{flow.subject}</span>
          <span className="listrow__desc">
            {flow.from} → {flow.recipient} · {TYPE_LABEL[flow.type]} · {URGENCY_LABEL[flow.urgency]} priority
          </span>
        </span>
        <StatusPill tone={state.tone}>{state.label}</StatusPill>
      </button>
      {open ? (
        <div className="stack stack--3" id={bodyId}>
          {loadingBody ? (
            <Skeleton height={40} />
          ) : (
            <p className="t-sm t-muted message-body">{body || "No message text — see the linked note."}</p>
          )}
          {flow.refs.length > 0 ? (
            <p className="t-sm t-muted">Linked notes: {flow.refs.join(", ")}</p>
          ) : null}
          <div className="row">
            <Button size="sm" variant="destructive" onClick={() => setConfirmEnd(true)} disabled={ending}>
              End conversation
            </Button>
          </div>
        </div>
      ) : null}
      <ConfirmDialog
        open={confirmEnd}
        onCancel={() => setConfirmEnd(false)}
        onConfirm={() => void end()}
        title="End this conversation?"
        confirmLabel="End conversation"
        destructive
        busy={ending}
      >
        <p>Messages in it that nobody has read yet won&rsquo;t be delivered.</p>
      </ConfirmDialog>
    </div>
  );
}

function RefPicker({ refs, onChange }: { refs: string[]; onChange: (refs: string[]) => void }) {
  const [vaults, setVaults] = useState<VaultSummary[]>([]);
  const [vaultKey, setVaultKey] = useState("");
  const [query, setQuery] = useState("");
  const [hits, setHits] = useState<SearchHit[]>([]);

  useEffect(() => {
    api
      .listVaults()
      .then((list) => {
        setVaults(list);
        if (list.length > 0) setVaultKey(list[0].key);
      })
      .catch(() => setVaults([]));
  }, []);

  useEffect(() => {
    const handle = setTimeout(() => {
      if (!vaultKey || !query.trim()) {
        setHits([]);
        return;
      }
      api
        .search(vaultKey, query)
        .then(setHits)
        .catch(() => setHits([]));
    }, 250);
    return () => clearTimeout(handle);
  }, [vaultKey, query]);

  function add(permalink: string) {
    const ref = `memory://${permalink}`;
    if (!refs.includes(ref)) onChange([...refs, ref]);
    setQuery("");
    setHits([]);
  }

  if (vaults.length === 0) return null;

  return (
    <div className="stack stack--2">
      <span className="field__label">
        Link a note<span className="field__optional">Optional</span>
      </span>
      <div className="row" style={{ gap: 8 }}>
        {vaults.length > 1 ? (
          <select
            className="input"
            aria-label="Memory to search"
            value={vaultKey}
            onChange={(event) => setVaultKey(event.target.value)}
            style={{ maxWidth: 180 }}
          >
            {vaults.map((vault) => (
              <option key={vault.key} value={vault.key}>
                {vault.key}
              </option>
            ))}
          </select>
        ) : null}
        <input
          className="input"
          aria-label="Search notes to link"
          placeholder="Search notes to link"
          value={query}
          onChange={(event) => setQuery(event.target.value)}
        />
      </div>
      {hits.length > 0 ? (
        <div className="card card--flat">
          {hits.slice(0, 5).map((hit) => (
            <ListRow key={hit.permalink} onClick={() => add(hit.permalink)} title={hit.title} description={hit.permalink} />
          ))}
        </div>
      ) : null}
      {refs.length > 0 ? (
        <div className="row row--wrap" style={{ gap: 6 }}>
          {refs.map((ref) => (
            <Chip key={ref} mono>
              {ref}
              <button
                type="button"
                className="linklike"
                onClick={() => onChange(refs.filter((r) => r !== ref))}
                aria-label={`Remove ${ref}`}
                style={{ marginLeft: 6 }}
              >
                ×
              </button>
            </Chip>
          ))}
        </div>
      ) : null}
    </div>
  );
}

function ComposeDialog({
  open,
  onClose,
  sessions,
  onSent,
}: {
  open: boolean;
  onClose: () => void;
  sessions: SessionRecord[];
  onSent: () => void;
}) {
  const toast = useToast();
  const typeId = useId();
  const urgencyId = useId();
  const [to, setTo] = useState("");
  const [type, setType] = useState<MessageType>("inform");
  const [subject, setSubject] = useState("");
  const [body, setBody] = useState("");
  const [urgency, setUrgency] = useState<Urgency>("normal");
  const [expectsReply, setExpectsReply] = useState(false);
  const [refs, setRefs] = useState<string[]>([]);
  const [sending, setSending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const bodyBytes = byteLength(body);
  const overBody = bodyBytes > MAX_BODY_BYTES;

  function reset() {
    setTo("");
    setSubject("");
    setBody("");
    setRefs([]);
    setExpectsReply(false);
    setError(null);
  }

  async function send() {
    setError(null);
    if (!to.trim() || !subject.trim()) {
      setError("Fill in who this is for and a subject.");
      return;
    }
    if (overBody) {
      setError(
        `The message is ${bodyBytes} bytes; the limit is ${MAX_BODY_BYTES}. Link a note instead of pasting the rest in.`,
      );
      return;
    }
    setSending(true);
    try {
      await api.sendAsOwner({
        type,
        to: to.trim(),
        subject: subject.trim(),
        body,
        urgency,
        expects_reply: expectsReply,
        refs: refs.length > 0 ? refs : undefined,
      });
      toast.show("Message sent.");
      reset();
      onClose();
      onSent();
    } catch (err) {
      setError(describeApiError(err));
    } finally {
      setSending(false);
    }
  }

  return (
    <Dialog
      open={open}
      onClose={onClose}
      size="form"
      title="Send a message"
      description="You send it as yourself, to one session or to all of them."
      footer={
        <>
          <Button onClick={onClose} disabled={sending}>
            Cancel
          </Button>
          <Button variant="primary" onClick={send} loading={sending}>
            {sending ? "Sending…" : "Send"}
          </Button>
        </>
      }
    >
      <Field label="To" hint="A session's ID from the list, or * for every session.">
        <input
          className="input"
          list="session-handles"
          placeholder="abc123handle, or *"
          value={to}
          onChange={(event) => setTo(event.target.value)}
        />
        <datalist id="session-handles">
          {sessions.map((session) => (
            <option key={session.handle} value={session.handle} />
          ))}
          <option value="*">Every session</option>
        </datalist>
      </Field>
      <div className="row row--wrap" style={{ gap: 12, alignItems: "flex-start" }}>
        <Field label="Type" controlId={typeId}>
          <select
            id={typeId}
            className="input"
            value={type}
            onChange={(event) => setType(event.target.value as MessageType)}
          >
            {Object.entries(TYPE_LABEL).map(([value, label]) => (
              <option key={value} value={value}>
                {label}
              </option>
            ))}
          </select>
        </Field>
        <Field label="Priority" controlId={urgencyId}>
          <select
            id={urgencyId}
            className="input"
            value={urgency}
            onChange={(event) => setUrgency(event.target.value as Urgency)}
          >
            {Object.entries(URGENCY_LABEL).map(([value, label]) => (
              <option key={value} value={value}>
                {label}
              </option>
            ))}
          </select>
        </Field>
      </div>
      <Field label="Subject">
        <input
          className="input"
          maxLength={200}
          value={subject}
          onChange={(event) => setSubject(event.target.value)}
        />
      </Field>
      <Field
        label="Message"
        hint={overBody ? undefined : `${bodyBytes} of ${MAX_BODY_BYTES} bytes`}
        error={overBody ? `${bodyBytes} of ${MAX_BODY_BYTES} bytes — over the limit.` : undefined}
      >
        <textarea className="input" rows={4} value={body} onChange={(event) => setBody(event.target.value)} />
      </Field>
      <RefPicker refs={refs} onChange={setRefs} />
      <label className="checkrow">
        <input type="checkbox" checked={expectsReply} onChange={(event) => setExpectsReply(event.target.checked)} />
        <span>Needs a reply</span>
      </label>
      {error ? (
        <p className="field__error" role="alert">
          {error}
        </p>
      ) : null}
    </Dialog>
  );
}

export function Agents() {
  const stream = useOutletContext<EventStreamState>();
  const [sessions, setSessions] = useState<SessionRecord[] | null>(null);
  const [sessionsError, setSessionsError] = useState<string | null>(null);
  const [flows, setFlows] = useState<EnvelopeMetadata[] | null>(null);
  const [flowsError, setFlowsError] = useState<string | null>(null);
  const [composing, setComposing] = useState(false);

  const refresh = useCallback(() => {
    api
      .listSessions()
      .then((result) => {
        setSessions(result.sessions);
        setSessionsError(null);
      })
      .catch((err) => setSessionsError(describeApiError(err)));
    api
      .messageFlows({ limit: 50 })
      .then((result) => {
        setFlows(result.flows);
        setFlowsError(null);
      })
      .catch((err) => setFlowsError(describeApiError(err)));
  }, []);

  // No polling loop (SPEC-405 #1): fetched once on mount, then again only
  // when the event stream reports a session.*/message.* event. Issue 384: a
  // burst of events is one refetch, read once the count holds still.
  const activity = useDebouncedValue(stream.agentActivityCount, AGENT_REFRESH_COALESCE_MS);
  useEffect(() => {
    refresh();
  }, [activity, refresh]);

  const hasSessions = (sessions?.length ?? 0) > 0;

  return (
    <section className="stack">
      <div className="sessions-intro">
        <p>AI sessions that registered with palaia, and messages between them.</p>
        <div className="row row--wrap">
          {!hasSessions ? <span className="t-sm t-muted">No session to send to</span> : null}
          <Button onClick={() => setComposing(true)} disabled={!hasSessions}>
            Send a message
          </Button>
        </div>
      </div>

      <Card>
        <CardHeader
          title="Sessions"
          description={sessions && sessions.length > 0 ? count(sessions.length, "session", "sessions") : undefined}
        />
        {sessionsError && sessions === null ? (
          <div className="card__body">
            <ErrorState title="Couldn't load live sessions" details={sessionsError} onRetry={refresh} />
          </div>
        ) : sessions === null ? (
          <div className="card__body">
            <LoadingState label="Loading live sessions…" lines={2} />
          </div>
        ) : sessions.length === 0 ? (
          <InlineEmpty>
            No live sessions. Sessions appear when an app with the palaia-messenger skill starts
            working.
          </InlineEmpty>
        ) : (
          <div className="list">
            {sessions.map((session) => (
              <SessionRow key={session.handle} session={session} onRemoved={refresh} />
            ))}
          </div>
        )}
      </Card>

      <Card>
        <CardHeader title="Messages" />
        {flowsError && flows === null ? (
          <div className="card__body">
            <ErrorState title="Couldn't load messages" details={flowsError} onRetry={refresh} />
          </div>
        ) : flows === null ? (
          <div className="card__body">
            <LoadingState label="Loading messages…" lines={2} />
          </div>
        ) : flows.length === 0 ? (
          <InlineEmpty>No messages yet. Messages between sessions appear here.</InlineEmpty>
        ) : (
          <div className="list">
            {flows.map((flow) => (
              <MessageRow key={flow.id} flow={flow} onEnded={refresh} />
            ))}
          </div>
        )}
      </Card>

      <ComposeDialog
        open={composing}
        onClose={() => setComposing(false)}
        sessions={sessions ?? []}
        onSent={refresh}
      />
    </section>
  );
}
