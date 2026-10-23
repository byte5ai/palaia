/**
 * Temporary memories (issue 168): a memory for one task — the sources behind
 * a report, the research for a trip — kept apart from everyday memories and
 * closed when the task is done.
 *
 * - `NewTemporaryMemory` is the "New temporary memory" dialog
 *   (`POST /api/vaults` with `ephemeral: true` and an optional number of
 *   days until it is due).
 * - `TemporaryMemoryBanner` sits above a temporary memory's notes: when it
 *   is due, and the two things to do at the end of the task.
 *   - "Keep notes…" copies chosen notes into an everyday memory
 *     (`POST /api/vaults/{key}/promote`) — all or nothing; a note that
 *     already exists there is named and nothing is copied.
 *   - "Close…" takes it away from every AI app and archives its folder
 *     (`POST /api/vaults/{key}/close`). Nothing is deleted, and the name has
 *     to be typed to confirm, the same confirmation the API asks for.
 *
 * Nothing closes on its own when the due date passes; palaia only marks it
 * as overdue.
 */
import { useState } from "react";

import { Button, Dialog, LabeledInput, useToast } from "../components";
import type { NoteSummary, VaultSummary } from "../lib/api/client";
import { api } from "../lib/api/client";
import { describeApiError } from "../lib/errors";
import { count, shortDate } from "../lib/format";
import { InfoIcon, WarningIcon } from "../shell/icons";

const DEFAULT_DAYS = 14;
const NAME_RE = /^[a-z0-9][a-z0-9-]{0,31}$/;

export function NewTemporaryMemory({
  open,
  onCreated,
  onCancel,
}: {
  open: boolean;
  onCreated: (key: string) => void;
  onCancel: () => void;
}) {
  const toast = useToast();
  const [key, setKey] = useState("");
  const [purpose, setPurpose] = useState("");
  const [days, setDays] = useState(String(DEFAULT_DAYS));
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const name = key.trim();
  const nameInvalid = name !== "" && !NAME_RE.test(name);

  async function create() {
    setSaving(true);
    setError(null);
    const ttl = Number.parseInt(days, 10);
    try {
      const created = await api.createVault({
        key: name,
        purpose: purpose.trim() || undefined,
        ephemeral: true,
        ttl_days: Number.isFinite(ttl) && ttl > 0 ? ttl : undefined,
      });
      toast.show(`Created the temporary memory ${created.key}.`);
      setKey("");
      setPurpose("");
      setDays(String(DEFAULT_DAYS));
      onCreated(created.key);
    } catch (err) {
      setError(describeApiError(err));
    } finally {
      setSaving(false);
    }
  }

  return (
    <Dialog
      open={open}
      onClose={onCancel}
      size="form"
      title="New temporary memory"
      description="A separate memory for one task. When you're done, copy the notes you want to keep and close it."
      footer={
        <>
          <Button onClick={onCancel} disabled={saving}>
            Cancel
          </Button>
          <Button
            variant="primary"
            onClick={() => void create()}
            loading={saving}
            disabled={!name || nameInvalid}
          >
            {saving ? "Creating…" : "Create temporary memory"}
          </Button>
        </>
      }
    >
      <LabeledInput
        label="Name"
        placeholder="trip-lisbon"
        hint="Lowercase letters, numbers and dashes, e.g. trip-lisbon."
        error={
          nameInvalid
            ? "Use lowercase letters, numbers and dashes, starting with a letter or number."
            : undefined
        }
        invalid={nameInvalid}
        autoComplete="off"
        value={key}
        onChange={(event) => setKey(event.target.value)}
      />
      <LabeledInput
        label="What it's for"
        optional
        placeholder="Research for the Lisbon trip"
        hint="AI apps use this to choose the right memory."
        value={purpose}
        onChange={(event) => setPurpose(event.target.value)}
      />
      <LabeledInput
        label="Due in days"
        optional
        type="number"
        min={1}
        max={3650}
        hint="palaia only marks it as overdue; nothing closes by itself."
        value={days}
        onChange={(event) => setDays(event.target.value)}
      />
      {error ? (
        <p className="field__error" role="alert">
          {error}
        </p>
      ) : null}
    </Dialog>
  );
}

function KeepNotes({
  vault,
  notes,
  targets,
  onDone,
}: {
  vault: VaultSummary;
  notes: NoteSummary[];
  targets: VaultSummary[];
  onDone: () => void;
}) {
  const toast = useToast();
  const [target, setTarget] = useState(targets[0]?.key ?? "");
  const [chosen, setChosen] = useState<Set<string>>(new Set());
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  function toggle(permalink: string) {
    setChosen((prev) => {
      const next = new Set(prev);
      if (next.has(permalink)) next.delete(permalink);
      else next.add(permalink);
      return next;
    });
  }

  async function keep() {
    setSaving(true);
    setError(null);
    try {
      const result = await api.promoteNotes(vault.key, {
        target,
        notes: notes.filter((n) => chosen.has(n.permalink)).map((n) => n.permalink),
      });
      toast.show(`Copied ${count(result.promoted.length, "note", "notes")} into ${result.target}.`);
      setChosen(new Set());
      onDone();
    } catch (err) {
      setError(describeApiError(err));
    } finally {
      setSaving(false);
    }
  }

  if (targets.length === 0) {
    return (
      <p className="t-sm t-muted">
        There is no everyday memory to copy notes into yet. Create one first.
      </p>
    );
  }

  return (
    <div className="stack stack--3" data-testid="keep-notes">
      <label className="row row--wrap">
        <span className="t-strong">Copy into</span>
        <select
          className="vaultpick"
          value={target}
          onChange={(event) => setTarget(event.target.value)}
          aria-label="Copy into"
        >
          {targets.map((v) => (
            <option key={v.key} value={v.key}>
              {v.key}
            </option>
          ))}
        </select>
      </label>
      {notes.length === 0 ? (
        <p className="t-sm t-muted">This memory has no notes yet.</p>
      ) : (
        <ul className="memories-keep">
          {notes.map((note) => (
            <li key={note.permalink}>
              <label className="checkrow">
                <input
                  type="checkbox"
                  checked={chosen.has(note.permalink)}
                  onChange={() => toggle(note.permalink)}
                />
                <span>{note.title}</span>
              </label>
            </li>
          ))}
        </ul>
      )}
      <p className="t-sm t-muted">
        Notes keep their titles, tags and links. If one already exists there, nothing is copied
        and palaia tells you which.
      </p>
      {error ? (
        <p className="field__error" role="alert">
          {error}
        </p>
      ) : null}
      <div>
        <Button
          variant="primary"
          size="sm"
          onClick={() => void keep()}
          loading={saving}
          disabled={chosen.size === 0 || !target}
        >
          {saving
            ? "Copying…"
            : `Copy ${count(chosen.size, "note", "notes")} into ${target}`}
        </Button>
      </div>
    </div>
  );
}

function CloseMemory({ vault, onClosed }: { vault: VaultSummary; onClosed: () => void }) {
  const toast = useToast();
  const [confirm, setConfirm] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function close() {
    setSaving(true);
    setError(null);
    try {
      const result = await api.closeVault(vault.key, confirm);
      toast.show(`Closed ${result.key}. Its folder is in palaia's archive.`);
      onClosed();
    } catch (err) {
      setError(describeApiError(err));
      setSaving(false);
    }
  }

  return (
    <div className="stack stack--3" data-testid="close-memory">
      <p className="t-sm">
        Closing takes <b>{vault.key}</b> away from every AI app and moves its folder to
        palaia&rsquo;s archive. Nothing is deleted. Keep the notes you need first.
      </p>
      <LabeledInput
        label={`Type ${vault.key} to confirm`}
        value={confirm}
        onChange={(event) => setConfirm(event.target.value)}
        autoComplete="off"
      />
      {error ? (
        <p className="field__error" role="alert">
          {error}
        </p>
      ) : null}
      <div>
        <Button
          variant="danger"
          size="sm"
          onClick={() => void close()}
          loading={saving}
          disabled={confirm !== vault.key}
        >
          {saving ? "Closing…" : `Close ${vault.key}`}
        </Button>
      </div>
    </div>
  );
}

export function TemporaryMemoryBanner({
  vault,
  vaults,
  notes,
  onClosed,
  onPromoted,
  now: nowProp,
}: {
  vault: VaultSummary;
  vaults: VaultSummary[];
  notes: NoteSummary[];
  onClosed: () => void;
  onPromoted: () => void;
  now?: number;
}) {
  const [panel, setPanel] = useState<"keep" | "close" | null>(null);
  // Read once per mount: "overdue" is a day-level fact, not a ticking clock.
  const [now] = useState(() => nowProp ?? Date.now());
  const overdue = vault.expires ? Date.parse(vault.expires) < now : false;
  const targets = vaults.filter((v) => v.key !== vault.key && !v.ephemeral && v.writable);
  const Icon = overdue ? WarningIcon : InfoIcon;

  return (
    <div
      className={`callout ${overdue ? "callout--warn" : "callout--info"}`}
      data-testid="temporary-memory"
    >
      <Icon className="icon" />
      <div className="callout__main">
        <p className="callout__title">
          {overdue ? "This temporary memory is overdue" : "This is a temporary memory"}
        </p>
        <p className="callout__text">
          {vault.expires
            ? overdue
              ? `It was due on ${shortDate(vault.expires)}.`
              : `It is due on ${shortDate(vault.expires)}.`
            : "It has no due date."}{" "}
          Keep the notes you need, then close it.
        </p>
        <div className="callout__actions">
          <Button
            size="sm"
            onClick={() => setPanel(panel === "keep" ? null : "keep")}
            aria-expanded={panel === "keep"}
          >
            Keep notes…
          </Button>
          <Button
            variant="destructive"
            size="sm"
            onClick={() => setPanel(panel === "close" ? null : "close")}
            aria-expanded={panel === "close"}
          >
            Close…
          </Button>
        </div>
        {panel === "keep" ? (
          <div className="memories-temp__panel">
            <KeepNotes
              vault={vault}
              notes={notes}
              targets={targets}
              onDone={() => {
                setPanel(null);
                onPromoted();
              }}
            />
          </div>
        ) : null}
        {panel === "close" ? (
          <div className="memories-temp__panel">
            <CloseMemory vault={vault} onClosed={onClosed} />
          </div>
        ) : null}
      </div>
    </div>
  );
}
