/**
 * SPEC-405: the Agents screen — the live directory of agent sessions
 * connected to this hub, and the messages moving between them.
 *
 * MASTERPLAN §5.4 trust rule #7: "the human can read along, join in, or
 * shut a conversation down." This screen is "read along" (always, live,
 * no reload); "Send a message" is "join in"; "End conversation" and
 * "Remove" are "shut down". The last two are the SPEC-304 rule this SPEC
 * inherits: destructive controls stay dashboard-only, which is exactly
 * where they are — the session-monitor MCP App only ever links back here
 * for them.
 *
 * Live updates ride the hub's existing SSE bus (`stream.agentActivityCount`,
 * bumped on every `session.*`/`message.*` event — see ../lib/events.ts) —
 * there is no polling interval anywhere in this file.
 */
import { useEffect, useId, useState } from "react";
import { useOutletContext } from "react-router-dom";

import { Badge, Button, Card, CardBody, CardHead, Chip, EmptyState, Field, Skeleton, useToast } from "../components";
import type {
  EnvelopeMetadata,
  MessageType,
  SearchHit,
  SessionRecord,
  Urgency,
  VaultSummary,
} from "../lib/api/client";
import { api, ApiError } from "../lib/api/client";
import type { EventStreamState } from "../lib/events";
import { AgentsIcon } from "../shell/icons";

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

function describeError(err: unknown): string {
  if (err instanceof ApiError) {
    const body = err.body as { detail?: string } | undefined;
    if (body?.detail) return body.detail;
    return `The hub answered ${err.status}.`;
  }
  return "Could not reach the hub.";
}

function relativeTime(seconds: number): string {
  const minutes = Math.max(0, Math.round((Date.now() - seconds * 1000) / 60000));
  if (minutes < 1) return "just now";
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  return `${Math.round(hours / 24)}d ago`;
}

function statusBadgeVariant(status: SessionRecord["status"]): "ok" | "warn" | "risk" {
  if (status === "stale") return "risk";
  if (status === "idle") return "warn";
  return "ok";
}

function statusLabel(status: SessionRecord["status"]): string {
  if (status === "stale") return "Inactive";
  if (status === "idle") return "Idle";
  return "Active";
}

function byteLength(text: string): number {
  return new TextEncoder().encode(text).length;
}

function AgentRow({ session, onRemoved }: { session: SessionRecord; onRemoved: () => void }) {
  const toast = useToast();
  const [confirming, setConfirming] = useState(false);
  const [busy, setBusy] = useState(false);

  async function remove() {
    setBusy(true);
    try {
      await api.deregisterSession(session.handle);
      toast.show(`${session.handle} removed from the directory.`);
      onRemoved();
    } catch (err) {
      toast.show(describeError(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="listrow">
      <div style={{ flex: 1, minWidth: 0 }}>
        <div className="listrow__title t-mono">{session.handle}</div>
        <div className="listrow__meta">{session.scope || "No scope reported"}</div>
        <div className="listrow__meta">
          {session.platform || "Unknown platform"}
          {session.model ? ` · ${session.model}` : ""}
        </div>
      </div>
      <div className="row" style={{ gap: 8, alignItems: "center" }}>
        <Badge variant={statusBadgeVariant(session.status)}>{statusLabel(session.status)}</Badge>
        <span
          className="t-xs t-subtle"
          title={new Date(session.last_seen_at * 1000).toLocaleString()}
        >
          seen {relativeTime(session.last_seen_at)}
        </span>
        {confirming ? (
          <>
            <Button size="sm" variant="ghost" onClick={() => setConfirming(false)} disabled={busy}>
              Never mind
            </Button>
            <Button size="sm" variant="risk" onClick={remove} disabled={busy}>
              Yes, remove
            </Button>
          </>
        ) : (
          <Button size="sm" variant="risk" onClick={() => setConfirming(true)} disabled={busy}>
            Remove
          </Button>
        )}
      </div>
    </div>
  );
}

function messageStateLabel(state: EnvelopeMetadata["state"]): string {
  if (state === "pending") return "Waiting";
  if (state === "delivered") return "Delivered";
  return "Done";
}

function messageStateVariant(state: EnvelopeMetadata["state"]): "warn" | "neutral" | "ok" {
  if (state === "pending") return "warn";
  if (state === "acked") return "ok";
  return "neutral";
}

function MessageRow({ flow, onEnded }: { flow: EnvelopeMetadata; onEnded: () => void }) {
  const toast = useToast();
  const [open, setOpen] = useState(false);
  const [body, setBody] = useState<string | null>(null);
  const [loadingBody, setLoadingBody] = useState(false);
  const [ending, setEnding] = useState(false);
  const [confirmEnd, setConfirmEnd] = useState(false);

  async function toggle() {
    const next = !open;
    setOpen(next);
    if (next && body === null) {
      setLoadingBody(true);
      try {
        const detail = await api.envelopeDetail(flow.id);
        setBody(detail.item.envelope.body);
      } catch {
        setBody("This message could not be read.");
      } finally {
        setLoadingBody(false);
      }
    }
  }

  async function end() {
    setEnding(true);
    try {
      const result = await api.endConversation(flow.id);
      const count = result.expired.length;
      toast.show(
        count === 0
          ? "Nothing was left waiting in this conversation."
          : `Conversation ended — ${count} unread message${count === 1 ? "" : "s"} will not be delivered.`,
      );
      onEnded();
    } catch (err) {
      toast.show(describeError(err));
    } finally {
      setEnding(false);
      setConfirmEnd(false);
    }
  }

  return (
    <div className="listrow" style={{ flexDirection: "column", alignItems: "stretch", gap: 8 }}>
      <button
        type="button"
        className="row row--between"
        onClick={toggle}
        aria-expanded={open}
        style={{ width: "100%", cursor: "pointer", background: "none", border: 0, padding: 0 }}
      >
        <div style={{ flex: 1, minWidth: 0, textAlign: "left" }}>
          <div className="listrow__title">{flow.subject}</div>
          <div className="listrow__meta">
            {flow.from} &rarr; {flow.recipient} · {TYPE_LABEL[flow.type]} · {URGENCY_LABEL[flow.urgency]}
          </div>
        </div>
        <Badge variant={messageStateVariant(flow.state)}>{messageStateLabel(flow.state)}</Badge>
      </button>
      {open ? (
        <div className="stack stack--2">
          {loadingBody ? (
            <Skeleton height={40} />
          ) : (
            <p className="t-sm t-muted" style={{ whiteSpace: "pre-wrap" }}>
              {body || "(no message text — see the linked note)"}
            </p>
          )}
          {flow.refs.length > 0 ? (
            <p className="t-xs t-subtle">Linked notes: {flow.refs.join(", ")}</p>
          ) : null}
          <div className="row">
            {confirmEnd ? (
              <>
                <Button size="sm" variant="ghost" onClick={() => setConfirmEnd(false)} disabled={ending}>
                  Never mind
                </Button>
                <Button size="sm" variant="risk" onClick={end} disabled={ending}>
                  Yes, end it
                </Button>
              </>
            ) : (
              <Button size="sm" variant="risk" onClick={() => setConfirmEnd(true)}>
                End conversation
              </Button>
            )}
          </div>
        </div>
      ) : null}
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
      <span className="field__label">Link a note (optional)</span>
      <div className="row" style={{ gap: 8 }}>
        {vaults.length > 1 ? (
          <select className="input" value={vaultKey} onChange={(event) => setVaultKey(event.target.value)}>
            {vaults.map((vault) => (
              <option key={vault.key} value={vault.key}>
                {vault.key}
              </option>
            ))}
          </select>
        ) : null}
        <input
          className="input"
          placeholder="Search notes to link…"
          value={query}
          onChange={(event) => setQuery(event.target.value)}
        />
      </div>
      {hits.length > 0 ? (
        <div className="stack stack--2">
          {hits.slice(0, 5).map((hit) => (
            <button
              key={hit.permalink}
              type="button"
              className="listrow"
              style={{ width: "100%", textAlign: "left", cursor: "pointer" }}
              onClick={() => add(hit.permalink)}
            >
              <div style={{ flex: 1, minWidth: 0 }}>
                <div className="listrow__title">{hit.title}</div>
                <div className="listrow__meta t-mono">{hit.permalink}</div>
              </div>
            </button>
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
                onClick={() => onChange(refs.filter((r) => r !== ref))}
                aria-label={`Remove ${ref}`}
                style={{ marginLeft: 6, background: "none", border: 0, cursor: "pointer" }}
              >
                &times;
              </button>
            </Chip>
          ))}
        </div>
      ) : null}
    </div>
  );
}

function ComposePanel({ sessions, onSent }: { sessions: SessionRecord[]; onSent: () => void }) {
  const toast = useToast();
  const subjectId = useId();
  const bodyId = useId();
  const typeId = useId();
  const urgencyId = useId();
  const [open, setOpen] = useState(false);
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
      toast.show("Sent.");
      setOpen(false);
      reset();
      onSent();
    } catch (err) {
      setError(describeError(err));
    } finally {
      setSending(false);
    }
  }

  if (!open) {
    return (
      <Button variant="primary" onClick={() => setOpen(true)}>
        Send a message
      </Button>
    );
  }

  return (
    <Card>
      <CardHead title="Send a message" />
      <CardBody className="stack stack--3">
        <Field label="To" hint="An agent's ID, or * for everyone">
          <input
            className="input"
            list="agent-handles"
            placeholder="Agent ID, or *"
            value={to}
            onChange={(event) => setTo(event.target.value)}
          />
          <datalist id="agent-handles">
            {sessions.map((session) => (
              <option key={session.handle} value={session.handle} />
            ))}
            <option value="*">Everyone</option>
          </datalist>
        </Field>
        <div className="row row--wrap" style={{ gap: 12 }}>
          <Field label={<label htmlFor={typeId}>Type</label>}>
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
          <Field label={<label htmlFor={urgencyId}>Priority</label>}>
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
        <Field label={<label htmlFor={subjectId}>Subject</label>}>
          <input
            id={subjectId}
            className="input"
            maxLength={200}
            value={subject}
            onChange={(event) => setSubject(event.target.value)}
          />
        </Field>
        <Field
          label={<label htmlFor={bodyId}>Message</label>}
          hint={overBody ? undefined : `${bodyBytes} / ${MAX_BODY_BYTES} bytes`}
          error={overBody ? `${bodyBytes} / ${MAX_BODY_BYTES} bytes — over the limit.` : undefined}
        >
          <textarea
            id={bodyId}
            className="input"
            rows={4}
            value={body}
            onChange={(event) => setBody(event.target.value)}
          />
        </Field>
        <RefPicker refs={refs} onChange={setRefs} />
        <label className="row" style={{ gap: 8 }}>
          <input
            type="checkbox"
            checked={expectsReply}
            onChange={(event) => setExpectsReply(event.target.checked)}
          />
          <span className="t-sm">Needs a reply</span>
        </label>
        {error ? <p className="field__error">{error}</p> : null}
        <div className="row">
          <Button variant="primary" onClick={send} disabled={sending}>
            {sending ? "Sending…" : "Send"}
          </Button>
          <Button variant="ghost" onClick={() => setOpen(false)} disabled={sending}>
            Cancel
          </Button>
        </div>
      </CardBody>
    </Card>
  );
}

export function Agents() {
  const stream = useOutletContext<EventStreamState>();
  const [sessions, setSessions] = useState<SessionRecord[] | null>(null);
  const [flows, setFlows] = useState<EnvelopeMetadata[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  function refresh() {
    api
      .listSessions()
      .then((result) => setSessions(result.sessions))
      .catch((err) => {
        setSessions([]);
        setError(describeError(err));
      });
    api
      .messageFlows({ limit: 50 })
      .then((result) => setFlows(result.flows))
      .catch(() => setFlows([]));
  }

  // No polling loop (deliverable #1): this refetches once on mount, then
  // again only when the SSE stream reports a session.*/message.* event.
  useEffect(() => {
    refresh();
  }, [stream.agentActivityCount]);

  return (
    <section className="stack stack--4">
      <p className="t-sm t-muted" style={{ maxWidth: 620 }}>
        Every agent connected to this hub, and the messages moving between them — updates live, no
        need to reload.
      </p>

      {error ? (
        <div className="banner banner--warn">
          <p className="t-sm t-muted">{error}</p>
        </div>
      ) : null}

      <div className="stack stack--2">
        <span className="field__label">Agents</span>
        {sessions === null ? (
          <Skeleton height={60} />
        ) : sessions.length === 0 ? (
          <EmptyState mark={<AgentsIcon className="icon--lg" />} title="No agents yet.">
            Connect a client and have it register with the directory to see it here.
          </EmptyState>
        ) : (
          <Card>
            {sessions.map((session) => (
              <AgentRow key={session.handle} session={session} onRemoved={refresh} />
            ))}
          </Card>
        )}
      </div>

      <div className="stack stack--2">
        <span className="field__label">Messages</span>
        {flows === null ? (
          <Skeleton height={60} />
        ) : flows.length === 0 ? (
          <EmptyState mark={<AgentsIcon className="icon--lg" />} title="No messages yet.">
            Nothing has been sent between agents on this hub.
          </EmptyState>
        ) : (
          <Card>
            {flows.map((flow) => (
              <MessageRow key={flow.id} flow={flow} onEnded={refresh} />
            ))}
          </Card>
        )}
      </div>

      <div className="stack stack--2">
        <span className="field__label">Send as yourself</span>
        <ComposePanel sessions={sessions ?? []} onSent={refresh} />
      </div>
    </section>
  );
}
