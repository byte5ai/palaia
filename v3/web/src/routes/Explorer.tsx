/**
 * Memories › Browse (SPEC-110 deliverable #2, redesigned for issues 570 and 571):
 * the memory picker and search, the list of notes, the open note, and what
 * is known about it (fields, links, history).
 *
 * States, each with its own words — an error is never shown as "empty"
 * (report §5.7): loading (skeleton), couldn't load (ErrorState with Try
 * again), no memories yet (EmptyState with Create memory), and the browser.
 *
 * Honest simplifications, unchanged from v0: search is the engine's linear
 * scan; a note's text renders as plain text; the local graph is one hop.
 *
 * `VaultView` is keyed by `vaultKey` and `NotePane` by `permalink`: React
 * remounts each with fresh state on a switch, rather than an effect
 * resetting the previous one's state by hand.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useSearchParams } from "react-router-dom";

import {
  Button,
  Dialog,
  Disclosure,
  EmptyState,
  ErrorState,
  Field,
  LabeledInput,
  LinkButton,
  LoadingState,
  StatusPill,
  useToast,
} from "../components";
import { Skeleton } from "../components/Skeleton";
import type {
  CommitSummary,
  GatewayVaultIdentity,
  LocalGraph,
  NoteRecord,
  NoteSummary,
  SearchHit,
  VaultSummary,
} from "../lib/api/client";
import { api } from "../lib/api/client";
import { describeApiError } from "../lib/errors";
import { count, exactTime, shortDateTime } from "../lib/format";
import { SEARCH_DEBOUNCE_MS, useDebouncedValue } from "../lib/useDebouncedValue";
import { SearchIcon, VaultsIcon } from "../shell/icons";
import "./memories.css";
import { NewTemporaryMemory, TemporaryMemoryBanner } from "./TemporaryMemory";

/** The name rule the hub enforces (`palaia_hub.vault.registry.NAME_RE`). */
const MEMORY_NAME_RE = /^[a-z0-9][a-z0-9-]{0,31}$/;

/** The memory tools an AI app sees, each renameable (report §3.7). */
const RENAMEABLE_TOOLS = [
  "search",
  "read",
  "write",
  "edit",
  "move",
  "delete",
  "list",
  "recent_activity",
] as const;

/** Mirrors `palaia_hub.gateway.naming.sanitize_tool_name` for the inline
 * preview only; the hub's own answer (`sanitized`) is the truth. */
function previewToolName(raw: string): string {
  let value = raw.replace(/[^a-zA-Z0-9_]+/g, "_").replace(/^_+|_+$/g, "");
  if (/^[0-9]/.test(value)) value = `t_${value}`;
  return value || "tool";
}

interface FolderGroup {
  folder: string;
  notes: NoteSummary[];
}

function isInboxFolder(folder: string): boolean {
  return folder === "inbox" || folder.startsWith("inbox/");
}

/** The inbox folder is where captures wait to be sorted: "To file". */
function folderLabel(folder: string): string {
  if (folder === "inbox") return "To file";
  if (folder.startsWith("inbox/")) return `To file / ${folder.slice("inbox/".length)}`;
  return folder;
}

function groupByFolder(notes: NoteSummary[]): FolderGroup[] {
  const groups = new Map<string, NoteSummary[]>();
  for (const note of notes) {
    const bucket = groups.get(note.folder) ?? [];
    bucket.push(note);
    groups.set(note.folder, bucket);
  }
  // Issue 375: captures waiting to be filed are notes like any other —
  // shown first, since they are what is new.
  return [...groups.entries()]
    .sort(([a], [b]) => {
      const inboxA = isInboxFolder(a) ? 0 : 1;
      const inboxB = isInboxFolder(b) ? 0 : 1;
      return inboxA - inboxB || a.localeCompare(b);
    })
    .map(([folder, items]) => ({
      folder,
      notes: items.sort((a, b) => a.title.localeCompare(b.title)),
    }));
}

/**
 * The description the hub writes when nobody gave one (the engine's
 * `palaia vault '<key>'.` and the gateway's "A palaia memory vault.") is
 * not something the person wrote — show it as missing (report §3.6).
 */
function isGeneratedDescription(purpose: string | null | undefined, key: string): boolean {
  const text = (purpose ?? "").trim();
  if (!text) return true;
  return (
    text === `palaia vault '${key}'.` ||
    text === `palaia vault ${key}.` ||
    text === "A palaia memory vault."
  );
}

const HISTORY_VERB: Record<string, string> = {
  write: "Created",
  edit: "Edited",
  move: "Moved",
  rename: "Renamed",
  delete: "Deleted",
};

/**
 * "Created by Claude Code CLI · 23 Oct, 15:35" from one commit: the author
 * is the AI app that made the change (`Attribution.git_author`), "human"
 * is the person in the dashboard, "palaia-hub" is palaia itself. The raw
 * subject and commit id stay in the tooltip.
 */
function describeCommit(commit: CommitSummary): { text: string; title: string } {
  const subject = commit.subject.split("\n")[0] ?? "";
  const summary = subject.includes(": ") ? subject.slice(subject.lastIndexOf(": ") + 2) : subject;
  const verb = HISTORY_VERB[summary.split(" ")[0]?.toLowerCase() ?? ""] ?? "Saved";
  const author = commit.author_name?.trim() ?? "";
  const who =
    author === "human" ? "you" : author === "palaia-hub" || author === "" ? "palaia" : author;
  const when = commit.committed_at ? shortDateTime(commit.committed_at) : "";
  return {
    text: `${verb} by ${who}${when ? ` · ${when}` : ""}`,
    title: [subject, commit.sha.slice(0, 7), commit.committed_at ? exactTime(commit.committed_at) : ""]
      .filter(Boolean)
      .join(" · "),
  };
}

export function Explorer() {
  const [vaults, setVaults] = useState<VaultSummary[] | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [vaultKey, setVaultKey] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);

  // `select`: switch to this memory once the list is back (one just
  // created); `null` drops the current one (a temporary memory just closed)
  // and falls back to the first one left.
  const loadVaults = useCallback((select?: string | null) => {
    api
      .listVaults()
      .then((list) => {
        setVaults(list);
        setLoadError(null);
        setVaultKey((current) => {
          const wanted = select === undefined ? current : select;
          return wanted && list.some((v) => v.key === wanted) ? wanted : (list[0]?.key ?? null);
        });
      })
      .catch((err: unknown) => {
        // Report §5.7: a failed listing is not "no memories yet".
        setLoadError(describeApiError(err));
      });
  }, []);

  useEffect(() => {
    loadVaults();
  }, [loadVaults]);

  const createDialog = (
    <CreateMemoryDialog
      open={creating}
      onClose={() => setCreating(false)}
      onCreated={(key) => {
        setCreating(false);
        loadVaults(key);
      }}
    />
  );

  if (vaults === null) {
    if (loadError) {
      return (
        <ErrorState
          title="Couldn't load your memories"
          details={loadError}
          onRetry={() => {
            setLoadError(null);
            loadVaults();
          }}
        >
          palaia didn't answer with the list of memories.
        </ErrorState>
      );
    }
    return <LoadingState label="Loading your memories…" />;
  }

  if (vaults.length === 0 || !vaultKey) {
    return (
      <>
        <EmptyState
          mark={<VaultsIcon className="icon icon--xl" />}
          title="No memories yet"
          actions={
            <Button variant="primary" onClick={() => setCreating(true)}>
              Create memory
            </Button>
          }
        >
          Create one to start saving notes.
        </EmptyState>
        {createDialog}
      </>
    );
  }

  return (
    <>
      <VaultView
        key={vaultKey}
        vaultKey={vaultKey}
        vaults={vaults}
        onSwitchVault={setVaultKey}
        onVaultsChanged={loadVaults}
        onCreateMemory={() => setCreating(true)}
      />
      {createDialog}
    </>
  );
}

/** "New memory": a name, what it's for, and — under Advanced — where its
 * folder lives. The same request the setup wizard's memory step sends. */
function CreateMemoryDialog({
  open,
  onClose,
  onCreated,
}: {
  open: boolean;
  onClose: () => void;
  onCreated: (key: string) => void;
}) {
  const toast = useToast();
  const [name, setName] = useState("");
  const [purpose, setPurpose] = useState("");
  const [folder, setFolder] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const trimmed = name.trim();
  const nameInvalid = trimmed !== "" && !MEMORY_NAME_RE.test(trimmed);

  async function create() {
    setSaving(true);
    setError(null);
    try {
      const created = await api.createVault({
        key: trimmed,
        purpose: purpose.trim() || undefined,
        path: folder.trim() || undefined,
      });
      toast.show(`Created the memory ${created.key}.`);
      setName("");
      setPurpose("");
      setFolder("");
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
      onClose={onClose}
      size="form"
      title="New memory"
      description="A memory is a folder of notes your AI apps read and write."
      footer={
        <>
          <Button onClick={onClose} disabled={saving}>
            Cancel
          </Button>
          <Button
            variant="primary"
            onClick={() => void create()}
            loading={saving}
            disabled={!trimmed || nameInvalid}
          >
            {saving ? "Creating…" : "Create memory"}
          </Button>
        </>
      }
    >
      <LabeledInput
        label="Name"
        placeholder="work"
        hint="Lowercase letters, numbers and dashes, e.g. work."
        error={
          nameInvalid
            ? "Use lowercase letters, numbers and dashes, starting with a letter or number."
            : undefined
        }
        invalid={nameInvalid}
        value={name}
        autoComplete="off"
        onChange={(event) => setName(event.target.value)}
      />
      <LabeledInput
        label="What it's for"
        optional
        placeholder="Projects, decisions and notes for my team"
        hint="AI apps use this to choose the right memory."
        value={purpose}
        onChange={(event) => setPurpose(event.target.value)}
      />
      <Disclosure summary="Advanced">
        <Field label="Folder" optional hint="Leave empty to use palaia's data folder.">
          <input
            className="input input--mono"
            placeholder="/data/memories/work"
            value={folder}
            onChange={(event) => setFolder(event.target.value)}
          />
        </Field>
      </Disclosure>
      {error ? (
        <p className="field__error" role="alert">
          {error}
        </p>
      ) : null}
    </Dialog>
  );
}

/**
 * Advanced › Tool names for one memory: what AI apps see this memory's
 * tools as. Renaming is live everywhere the memory is used; an app that
 * already approved a tool may ask again. Hidden on a palaia without tool
 * sets (404).
 */
function MemoryToolNames({ vaultKey }: { vaultKey: string }) {
  const toast = useToast();
  const [identity, setIdentity] = useState<GatewayVaultIdentity | null | undefined>(undefined);
  const [draft, setDraft] = useState<Record<string, string>>({});
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    api
      .listGatewayVaults()
      .then((list) => {
        if (cancelled) return;
        const found = list.find((v) => v.key === vaultKey) ?? null;
        setIdentity(found);
        setDraft(found?.tool_renames ?? {});
      })
      .catch(() => {
        if (!cancelled) setIdentity(null);
      });
    return () => {
      cancelled = true;
    };
  }, [vaultKey]);

  if (!identity) return null;

  function setValue(tool: string, value: string) {
    setDraft((prev) => {
      const next = { ...prev };
      if (value.trim()) next[tool] = value.trim();
      else delete next[tool];
      return next;
    });
  }

  async function save() {
    if (!identity) return;
    setSaving(true);
    setError(null);
    setNotice(null);
    try {
      const result = await api.updateGatewayVault(identity.key, { tool_renames: draft });
      setIdentity(result);
      setDraft(result.tool_renames);
      if (result.sanitized.length > 0) {
        setNotice(
          result.sanitized
            .map((s) => `"${s.requested}" isn't a valid tool name, so palaia saved "${s.applied}".`)
            .join(" "),
        );
      }
      toast.show(`Tool names for ${identity.key} saved.`);
    } catch (err) {
      setError(describeApiError(err));
    } finally {
      setSaving(false);
    }
  }

  return (
    <Disclosure summary={`Advanced: tool names for ${identity.key}`} section>
      <div className="stack stack--3 memories-tools">
        <p>Rename what AI apps see. Apps may ask you to approve renamed tools again.</p>
        <div className="memories-tools__grid">
          {RENAMEABLE_TOOLS.map((tool) => {
            const value = draft[tool] ?? "";
            return (
              <label key={tool} className="memories-tools__row">
                <span className="t-mono">{`${identity.namespace}_${value ? previewToolName(value) : tool}`}</span>
                <input
                  className="input input--mono"
                  aria-label={`New name for ${tool}`}
                  placeholder={tool}
                  value={value}
                  onChange={(event) => setValue(tool, event.target.value)}
                />
              </label>
            );
          })}
        </div>
        {notice ? <p className="t-sm">{notice}</p> : null}
        {error ? (
          <p className="field__error" role="alert">
            {error}
          </p>
        ) : null}
        <div>
          <Button size="sm" onClick={() => void save()} loading={saving}>
            {saving ? "Saving…" : "Save tool names"}
          </Button>
        </div>
      </div>
    </Disclosure>
  );
}

function VaultView({
  vaultKey,
  vaults,
  onSwitchVault,
  onVaultsChanged,
  onCreateMemory,
}: {
  vaultKey: string;
  vaults: VaultSummary[];
  onSwitchVault: (key: string) => void;
  onVaultsChanged: (select?: string | null) => void;
  onCreateMemory: () => void;
}) {
  const [creatingTemporary, setCreatingTemporary] = useState(false);
  const [notes, setNotes] = useState<NoteSummary[] | null>(null);
  const [notesError, setNotesError] = useState<string | null>(null);
  const [notesAttempt, setNotesAttempt] = useState(0);
  const [inboxCount, setInboxCount] = useState<number | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [searchResults, setSearchResults] = useState<SearchHit[] | null>(null);
  const [searchError, setSearchError] = useState<string | null>(null);
  // `null` until known: whether any AI app has an access key at all, so the
  // empty note pane only suggests connecting one when none is.
  const [hasApps, setHasApps] = useState<boolean | null>(null);
  // Issue 380: ⌘K / Ctrl+K arrive here with `?focus=search`.
  const [params] = useSearchParams();
  const focusSearch = params.get("focus") === "search";
  const searchInput = useRef<HTMLInputElement>(null);
  useEffect(() => {
    if (focusSearch) searchInput.current?.focus();
  }, [focusSearch]);

  useEffect(() => {
    let cancelled = false;
    // `VaultView` is keyed by memory, so a switch remounts it clean.
    api
      .listNotes(vaultKey)
      .then((list) => {
        if (cancelled) return;
        setNotes(list);
        setNotesError(null);
      })
      .catch((err: unknown) => {
        // Issue 378: a listing that failed is not an empty memory.
        if (!cancelled) setNotesError(describeApiError(err));
      });
    return () => {
      cancelled = true;
    };
  }, [vaultKey, notesAttempt]);

  useEffect(() => {
    let cancelled = false;
    api
      .inboxStatus(vaultKey)
      .then((status) => {
        if (!cancelled) setInboxCount(status.count);
      })
      .catch(() => {
        if (!cancelled) setInboxCount(null);
      });
    api
      .listTokens()
      .then((tokens) => {
        if (!cancelled) setHasApps(tokens.some((token) => !token.revoked_at));
      })
      .catch(() => {
        if (!cancelled) setHasApps(null);
      });
    return () => {
      cancelled = true;
    };
  }, [vaultKey]);

  // Issue 384: search once typing pauses, and cancel the request a newer
  // keystroke made stale, so results never arrive out of order.
  const debouncedQuery = useDebouncedValue(query, SEARCH_DEBOUNCE_MS);
  useEffect(() => {
    const text = debouncedQuery.trim();
    if (!text) return;
    const controller = new AbortController();
    api
      .search(vaultKey, text, controller.signal)
      .then((hits) => {
        if (controller.signal.aborted) return;
        setSearchResults(hits);
        setSearchError(null);
      })
      .catch((err: unknown) => {
        if (controller.signal.aborted) return;
        setSearchResults([]);
        setSearchError(describeApiError(err));
      });
    return () => controller.abort();
  }, [debouncedQuery, vaultKey]);

  function onQueryChange(text: string) {
    setQuery(text);
    // Clearing the box clears the results at once — nothing to wait for.
    if (!text.trim()) {
      setSearchResults(null);
      setSearchError(null);
    }
  }

  const groups = useMemo(() => groupByFolder(notes ?? []), [notes]);
  const vault = vaults.find((v) => v.key === vaultKey) ?? null;
  const description =
    vault && !isGeneratedDescription(vault.purpose, vault.key) ? vault.purpose : null;

  function treeRow(permalink: string, title: string, indent: boolean) {
    return (
      <button
        key={permalink}
        type="button"
        className={["tree__row", permalink === selected ? "tree__row--on" : ""]
          .filter(Boolean)
          .join(" ")}
        aria-current={permalink === selected ? "true" : undefined}
        onClick={() => setSelected(permalink)}
      >
        {indent ? <span className="tree__ind" /> : null}
        {title}
      </button>
    );
  }

  return (
    <div className="stack">
      <section className="searchrow memories-toolbar" aria-label="Find notes">
        {vaults.length > 1 ? (
          <select
            className="vaultpick"
            value={vaultKey}
            onChange={(event) => onSwitchVault(event.target.value)}
            aria-label="Memory"
          >
            {vaults.map((v) => (
              <option key={v.key} value={v.key}>
                {v.key}
                {v.ephemeral ? " (temporary)" : ""}
              </option>
            ))}
          </select>
        ) : (
          <span className="memories-toolbar__name" title="The memory you are looking at">
            <VaultsIcon className="icon" />
            {vaultKey}
          </span>
        )}
        <label className="searchbox">
          <SearchIcon className="icon icon--sm" />
          <input
            ref={searchInput}
            value={query}
            onChange={(event) => onQueryChange(event.target.value)}
            placeholder={`Search ${count(vault?.note_count ?? 0, "note", "notes")} in ${vaultKey}`}
            aria-label="Search this memory"
          />
          {searchResults ? (
            <span className="t-meta">{count(searchResults.length, "result", "results")}</span>
          ) : null}
        </label>
        <div className="memories-toolbar__actions">
          <Button size="sm" onClick={onCreateMemory}>
            New memory
          </Button>
          <Button
            size="sm"
            variant="plain"
            onClick={() => setCreatingTemporary(true)}
          >
            New temporary memory
          </Button>
        </div>
      </section>

      <NewTemporaryMemory
        open={creatingTemporary}
        onCreated={(key) => {
          setCreatingTemporary(false);
          onVaultsChanged(key);
        }}
        onCancel={() => setCreatingTemporary(false)}
      />

      {vault?.ephemeral ? (
        <TemporaryMemoryBanner
          vault={vault}
          vaults={vaults}
          notes={notes ?? []}
          onClosed={() => onVaultsChanged(null)}
          onPromoted={() => onVaultsChanged()}
        />
      ) : null}

      <section className="explorer">
        <div className="pane pane--tree">
          <div className="pane__head">
            <span>Notes</span>
            {inboxCount ? (
              <StatusPill tone="info" title="Captured notes waiting to be sorted">
                {inboxCount} to file
              </StatusPill>
            ) : null}
          </div>
          <div className="pane__body scrollpane">
            {searchResults ? (
              <div className="tree">
                {searchError ? (
                  <p className="t-sm t-muted" role="alert">
                    Couldn't search this memory. {searchError}
                  </p>
                ) : searchResults.length === 0 ? (
                  <p className="t-sm t-muted">No notes match “{query}”.</p>
                ) : (
                  searchResults.map((hit) => treeRow(hit.permalink, hit.title, false))
                )}
              </div>
            ) : notesError ? (
              <div className="stack stack--2" role="alert">
                <p className="t-sm">Couldn't load the notes in this memory.</p>
                <p className="t-sm t-muted">{notesError}</p>
                <div>
                  <Button size="sm" onClick={() => setNotesAttempt((n) => n + 1)}>
                    Try again
                  </Button>
                </div>
              </div>
            ) : notes === null ? (
              <div className="stack stack--2">
                <Skeleton height={16} />
                <Skeleton height={16} width="70%" />
                <Skeleton height={16} width="85%" />
              </div>
            ) : groups.length === 0 ? (
              <p className="t-sm t-muted">
                No notes yet. Notes appear here as your AI apps save them.
              </p>
            ) : (
              <div className="tree">
                {groups.map((group) => (
                  <div key={group.folder || "·"}>
                    {group.folder ? (
                      <div className="tree__row tree__row--dir" title={group.folder}>
                        {folderLabel(group.folder)}
                      </div>
                    ) : null}
                    {group.notes.map((item) => treeRow(item.permalink, item.title, true))}
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>

        {selected ? (
          <NotePane key={selected} vaultKey={vaultKey} permalink={selected} onSelect={setSelected} />
        ) : (
          <>
            <div className="pane">
              <div className="pane__body memories-pick">
                <p className="t-muted">Pick a note from the list, or search.</p>
              </div>
            </div>
            <div className="pane pane--ctx">
              <div className="pane__head">
                <span>About this memory</span>
              </div>
              <div className="ctx__block">
                {description ? (
                  <p className="t-sm">{description}</p>
                ) : (
                  <p className="t-sm t-muted">No description yet.</p>
                )}
                <p className="t-sm t-muted">
                  {count(vault?.note_count ?? 0, "note", "notes")}
                  {vault?.writable === false ? " · read-only" : ""}
                </p>
                {hasApps === false ? (
                  <div>
                    <LinkButton size="sm" variant="primary" to="/apps">
                      Connect an AI app
                    </LinkButton>
                  </div>
                ) : null}
              </div>
            </div>
          </>
        )}
      </section>

      <MemoryToolNames vaultKey={vaultKey} />
    </div>
  );
}

function NotePane({
  vaultKey,
  permalink,
  onSelect,
}: {
  vaultKey: string;
  permalink: string;
  onSelect: (permalink: string) => void;
}) {
  const [note, setNote] = useState<NoteRecord | null>(null);
  const [noteError, setNoteError] = useState<string | null>(null);
  const [graph, setGraph] = useState<LocalGraph | null>(null);
  const [graphError, setGraphError] = useState<string | null>(null);
  const [commits, setCommits] = useState<CommitSummary[] | null>(null);
  const [historyError, setHistoryError] = useState<string | null>(null);

  useEffect(() => {
    // Issue 378: a failed read used to leave the skeleton up for good.
    // (`NotePane` is keyed by permalink, so a new note starts clean.)
    let cancelled = false;
    api
      .readNote(vaultKey, permalink)
      .then((record) => {
        if (!cancelled) setNote(record);
      })
      .catch((err: unknown) => {
        if (!cancelled) setNoteError(describeApiError(err));
      });
    api
      .noteGraph(vaultKey, permalink)
      .then((value) => {
        if (!cancelled) setGraph(value);
      })
      .catch((err: unknown) => {
        if (!cancelled) setGraphError(describeApiError(err));
      });
    api
      .noteHistory(vaultKey, permalink)
      .then((value) => {
        if (!cancelled) setCommits(value);
      })
      .catch((err: unknown) => {
        if (!cancelled) setHistoryError(describeApiError(err));
      });
    return () => {
      cancelled = true;
    };
  }, [vaultKey, permalink]);

  function linkList(label: string, items: { permalink: string; title: string }[]) {
    if (items.length === 0) return null;
    return (
      <div className="stack stack--1">
        <span className="t-sm t-muted">{label}</span>
        <ul className="memories-links">
          {items.map((n) => (
            <li key={n.permalink}>
              <button type="button" className="wlink linklike" onClick={() => onSelect(n.permalink)}>
                {n.title}
              </button>
            </li>
          ))}
        </ul>
      </div>
    );
  }

  return (
    <>
      <div className="pane">
        <div className="pane__head">
          <span>Note</span>
        </div>
        {note === null ? (
          <div className="pane__body">
            {noteError ? (
              <div className="stack stack--2" role="alert">
                <p className="t-sm">Couldn't load this note.</p>
                <p className="t-sm t-muted">{noteError}</p>
              </div>
            ) : (
              <div className="stack stack--2">
                <Skeleton height={28} width="60%" />
                <Skeleton height={16} />
                <Skeleton height={16} width="90%" />
              </div>
            )}
          </div>
        ) : (
          <article className="note scrollpane">
            <h2 className="note__title">{note.title}</h2>
            <div className="note__meta">
              {note.type && note.type !== "note" ? <span className="chip">{note.type}</span> : null}
              {note.tags.map((tag) => (
                <span className="chip" key={tag}>
                  {tag}
                </span>
              ))}
              {note.modified ? (
                <span className="t-meta" title={exactTime(note.modified)}>
                  Updated {shortDateTime(note.modified)}
                </span>
              ) : null}
            </div>
            <p className="note__body">{note.body}</p>
          </article>
        )}
      </div>

      <div className="pane pane--ctx">
        <div className="pane__head">
          <span>Details</span>
        </div>
        <div className="ctx scrollpane">
          <div className="ctx__block">
            <span className="t-over">Fields</span>
            {note ? (
              <dl className="fm">
                <dt>Type</dt>
                <dd>{note.type || "—"}</dd>
                <dt>Tags</dt>
                <dd>{note.tags.join(", ") || "—"}</dd>
                <dt>Created</dt>
                <dd title={note.created ? exactTime(note.created) : undefined}>
                  {note.created ? shortDateTime(note.created) || note.created : "—"}
                </dd>
                <dt>Path</dt>
                <dd className="t-mono">{note.permalink}</dd>
              </dl>
            ) : noteError ? (
              <p className="t-sm t-muted">Not available.</p>
            ) : (
              <Skeleton height={60} />
            )}
          </div>
          <div className="ctx__block">
            <span className="t-over">Links</span>
            {graph === null ? (
              graphError ? (
                <p className="t-sm t-muted">Couldn't load the links: {graphError}</p>
              ) : (
                <Skeleton height={40} />
              )
            ) : graph.outbound.length === 0 && graph.inbound.length === 0 ? (
              <p className="t-sm t-muted">No links to or from this note yet.</p>
            ) : (
              <>
                {linkList("Links to", graph.outbound)}
                {linkList("Linked from", graph.inbound)}
              </>
            )}
          </div>
          <div className="ctx__block">
            <span className="t-over">History</span>
            {commits === null ? (
              historyError ? (
                <p className="t-sm t-muted">Couldn't load the history: {historyError}</p>
              ) : (
                <Skeleton height={40} />
              )
            ) : commits.length === 0 ? (
              <p className="t-sm t-muted">No history yet.</p>
            ) : (
              <ul className="memories-history">
                {commits.slice(0, 5).map((commit) => {
                  const line = describeCommit(commit);
                  return (
                    <li key={commit.sha} title={line.title}>
                      {line.text}
                    </li>
                  );
                })}
              </ul>
            )}
          </div>
        </div>
      </div>
    </>
  );
}

