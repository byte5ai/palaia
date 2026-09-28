/**
 * Temporary memories (issue 168): a vault for one task — the sources behind
 * a report, the research for a trip — that is kept apart from everyday
 * memory, and closed when the task is done.
 *
 * Three pieces, all on the Explorer:
 *
 * - `NewTemporaryMemory` creates one (`POST /api/vaults` with
 *   `ephemeral: true` and an optional number of days until it is due).
 * - `TemporaryMemoryBanner` sits above a temporary memory's notes: when it
 *   is due, and the two things to do at the end of the task.
 *   - "Keep notes…" copies chosen notes into an everyday memory
 *     (`POST /api/vaults/{key}/promote`) — all or nothing; a note that
 *     already exists there is named and nothing is copied.
 *   - "Close…" takes it away from every AI tool and archives its folder
 *     (`POST /api/vaults/{key}/close`). Nothing is deleted, and the name has
 *     to be typed to confirm, the same confirmation the API asks for.
 *
 * Nothing closes on its own when the due date passes; the banner says it is
 * overdue, and the hub's health check lists it.
 */
import { useState } from "react";

import { Button, LabeledInput, useToast } from "../components";
import type { NoteSummary, VaultSummary } from "../lib/api/client";
import { api } from "../lib/api/client";
import { describeApiError } from "../lib/errors";

const DEFAULT_DAYS = 14;

function formatDate(iso: string): string {
  return new Date(iso).toLocaleDateString(undefined, { dateStyle: "medium" });
}

export function NewTemporaryMemory({
  onCreated,
  onCancel,
}: {
  onCreated: (key: string) => void;
  onCancel: () => void;
}) {
  const toast = useToast();
  const [key, setKey] = useState("");
  const [purpose, setPurpose] = useState("");
  const [days, setDays] = useState(String(DEFAULT_DAYS));
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function create() {
    setSaving(true);
    setError(null);
    const ttl = Number.parseInt(days, 10);
    try {
      const created = await api.createVault({
        key: key.trim(),
        purpose: purpose.trim() || undefined,
        ephemeral: true,
        ttl_days: Number.isFinite(ttl) && ttl > 0 ? ttl : undefined,
      });
      toast.show(`Created the temporary memory ${created.key}`);
      onCreated(created.key);
    } catch (err) {
      setError(describeApiError(err));
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="card" data-testid="new-temporary-memory">
      <div className="card__head">
        <span className="card__subject">New temporary memory</span>
      </div>
      <div className="card__body stack stack--3">
        <p className="t-sm t-muted">
          A memory of its own for one task. Your AI tools see it as a separate
          memory, so what they collect for the task never mixes with your
          everyday notes. Keep the notes that matter when you are done, then
          close it.
        </p>
        <LabeledInput
          label="Name"
          placeholder="trip-lisbon"
          hint="Lowercase letters, digits and dashes. It becomes part of the tool names your AI tools see."
          value={key}
          onChange={(event) => setKey(event.target.value)}
        />
        <LabeledInput
          label="What it is for"
          placeholder="Research for the Lisbon trip"
          hint="Your AI tools read this to pick the right memory."
          value={purpose}
          onChange={(event) => setPurpose(event.target.value)}
        />
        <LabeledInput
          label="Due in (days)"
          type="number"
          min={1}
          max={3650}
          hint="Nothing happens on its own when it is due — it is only marked as overdue. Leave empty for no date."
          value={days}
          onChange={(event) => setDays(event.target.value)}
        />
        {error ? <p className="field__error">{error}</p> : null}
        <div className="row row--wrap">
          <Button
            variant="primary"
            size="sm"
            onClick={() => void create()}
            disabled={saving || !key.trim()}
          >
            {saving ? "Creating…" : "Create"}
          </Button>
          <Button variant="ghost" size="sm" onClick={onCancel} disabled={saving}>
            Cancel
          </Button>
        </div>
      </div>
    </div>
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
      toast.show(
        `Copied ${result.promoted.length} note${result.promoted.length === 1 ? "" : "s"} into ${result.target}`,
      );
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
        There is no everyday memory to copy notes into yet.
      </p>
    );
  }

  return (
    <div className="stack stack--3" data-testid="keep-notes">
      <label className="row row--wrap" style={{ gap: 8 }}>
        <span className="t-sm">Copy into</span>
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
        <ul
          className="stack stack--2"
          style={{ listStyle: "none", padding: 0, margin: 0, maxHeight: 240, overflow: "auto" }}
        >
          {notes.map((note) => (
            <li key={note.permalink}>
              <label className="row" style={{ gap: 8 }}>
                <input
                  type="checkbox"
                  checked={chosen.has(note.permalink)}
                  onChange={() => toggle(note.permalink)}
                />
                <span className="t-sm">{note.title}</span>
                <span className="t-meta">{note.permalink}</span>
              </label>
            </li>
          ))}
        </ul>
      )}
      <p className="t-xs t-subtle">
        The notes are copied with their titles, tags and links. If one of them
        already exists there, nothing is copied and you are told which one.
      </p>
      {error ? <p className="field__error">{error}</p> : null}
      <div className="row">
        <Button
          variant="primary"
          size="sm"
          onClick={() => void keep()}
          disabled={saving || chosen.size === 0 || !target}
        >
          {saving
            ? "Copying…"
            : `Copy ${chosen.size} note${chosen.size === 1 ? "" : "s"} into ${target}`}
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
      toast.show(`Closed ${result.key}; its folder is archived at ${result.archived_to}`);
      onClosed();
    } catch (err) {
      setError(describeApiError(err));
      setSaving(false);
    }
  }

  return (
    <div className="stack stack--3" data-testid="close-memory">
      <p className="t-sm">
        Closing takes <b>{vault.key}</b> away from every AI tool and moves its
        folder into the archive next to your hub&rsquo;s data. Nothing is
        deleted. Keep the notes that matter first.
      </p>
      <LabeledInput
        label={`Type ${vault.key} to confirm`}
        value={confirm}
        onChange={(event) => setConfirm(event.target.value)}
        autoComplete="off"
      />
      {error ? <p className="field__error">{error}</p> : null}
      <div className="row">
        <Button
          variant="primary"
          size="sm"
          onClick={() => void close()}
          disabled={saving || confirm !== vault.key}
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

  return (
    <div
      className={overdue ? "banner banner--warn" : "banner"}
      data-testid="temporary-memory"
      style={{ display: "block" }}
    >
      <div className="row--between">
        <div className="stack stack--2">
          <p className="banner__title">
            {overdue ? "This temporary memory is overdue." : "This is a temporary memory."}
          </p>
          <p className="t-sm t-muted">
            {vault.expires
              ? overdue
                ? `It was due on ${formatDate(vault.expires)}. Keep the notes that matter, then close it.`
                : `It is due on ${formatDate(vault.expires)}.`
              : "It has no due date."}{" "}
            It stays open until you close it.
          </p>
        </div>
        <div className="row row--wrap">
          <Button
            size="sm"
            onClick={() => setPanel(panel === "keep" ? null : "keep")}
            aria-expanded={panel === "keep"}
          >
            Keep notes…
          </Button>
          <Button
            variant="ghost"
            size="sm"
            onClick={() => setPanel(panel === "close" ? null : "close")}
            aria-expanded={panel === "close"}
          >
            Close…
          </Button>
        </div>
      </div>
      {panel === "keep" ? (
        <div style={{ marginTop: 12 }}>
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
        <div style={{ marginTop: 12 }}>
          <CloseMemory vault={vault} onClosed={onClosed} />
        </div>
      ) : null}
    </div>
  );
}
