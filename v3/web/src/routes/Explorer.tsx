/**
 * Memory explorer (SPEC-110 deliverable #2): vault switcher, folder tree,
 * note view (rendered body + frontmatter panel + git history from
 * SPEC-102), inbox uncurated badge (SPEC-107), a search bar, and a local
 * graph drill-down for the open note.
 *
 * Honest simplifications for v0 (recorded here rather than only in the
 * PR, so the next SPEC that touches this file sees them too):
 * - Search is `EngineVaultService`'s linear scan (`dashboard_api.py`'s
 *   docstring) — SPEC-104's hybrid index is not merged yet.
 * - The note body renders as plain text, not SPEC-103's parsed
 *   observations/relations — this SPEC depends on SPEC-109 only, and that
 *   structured extraction is not wired to any REST endpoint yet.
 * - The local graph is computed live (outbound: the note's own wikilinks;
 *   inbound: a linear scan of every other note) — see `dashboard_api.py`.
 *
 * `VaultView` is keyed by `vaultKey` and `NotePane` by `permalink`: React
 * remounts each with fresh state on a switch, rather than an effect
 * resetting the previous vault's/note's state by hand (the
 * `react-hooks/set-state-in-effect` rule this file used to trip).
 */
import { useEffect, useMemo, useRef, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";

import { EmptyState } from "../components/EmptyState";
import { Skeleton } from "../components/Skeleton";
import type {
  LocalGraph,
  NoteRecord,
  NoteSummary,
  SearchHit,
  VaultSummary,
} from "../lib/api/client";
import { api } from "../lib/api/client";
import { describeApiError } from "../lib/errors";
import {
  SEARCH_DEBOUNCE_MS,
  useDebouncedValue,
} from "../lib/useDebouncedValue";
import { ExplorerIcon, SearchIcon, VaultsIcon } from "../shell/icons";

interface FolderGroup {
  folder: string;
  notes: NoteSummary[];
}

function isInboxFolder(folder: string): boolean {
  return folder === "inbox" || folder.startsWith("inbox/");
}

function groupByFolder(notes: NoteSummary[]): FolderGroup[] {
  const groups = new Map<string, NoteSummary[]>();
  for (const note of notes) {
    const bucket = groups.get(note.folder) ?? [];
    bucket.push(note);
    groups.set(note.folder, bucket);
  }
  // Issue 375: captures waiting in the inbox used to be hidden here while
  // every "review now" button pointed at a page that did not exist. They
  // are notes like any other — shown first, since they are what is new.
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

export function Explorer() {
  const [vaults, setVaults] = useState<VaultSummary[] | null>(null);
  const [vaultKey, setVaultKey] = useState<string | null>(null);

  useEffect(() => {
    api
      .listVaults()
      .then((list) => {
        setVaults(list);
        setVaultKey((current) => current ?? list[0]?.key ?? null);
      })
      .catch(() => setVaults([]));
  }, []);

  if (vaults === null) {
    return (
      <div className="stack">
        <Skeleton height={34} />
        <Skeleton height={320} />
      </div>
    );
  }

  if (vaults.length === 0 || !vaultKey) {
    return (
      <EmptyState
        mark={<ExplorerIcon className="icon--lg" />}
        title="No vault exists yet."
      >
        <Link to="/onboarding">The setup wizard</Link> creates your first one —
        or an operator can register one directly with the vault registry. Once a
        vault exists, its notes show up here automatically.
      </EmptyState>
    );
  }

  return (
    <VaultView
      key={vaultKey}
      vaultKey={vaultKey}
      vaults={vaults}
      onSwitchVault={setVaultKey}
    />
  );
}

function VaultView({
  vaultKey,
  vaults,
  onSwitchVault,
}: {
  vaultKey: string;
  vaults: VaultSummary[];
  onSwitchVault: (key: string) => void;
}) {
  const [notes, setNotes] = useState<NoteSummary[] | null>(null);
  const [notesError, setNotesError] = useState<string | null>(null);
  const [inboxCount, setInboxCount] = useState<number | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [searchResults, setSearchResults] = useState<SearchHit[] | null>(null);
  // Issue 380: the topbar's search (and ⌘K) arrive here with `?focus=search`.
  const [params] = useSearchParams();
  const focusSearch = params.get("focus") === "search";
  const searchInput = useRef<HTMLInputElement>(null);
  useEffect(() => {
    if (focusSearch) searchInput.current?.focus();
  }, [focusSearch]);

  useEffect(() => {
    // `VaultView` is keyed by vault, so a switch remounts it with clean state.
    api
      .listNotes(vaultKey)
      .then(setNotes)
      .catch((err: unknown) => {
        // Issue 378: an empty tree that says "No folders yet" is not the
        // same as a listing that failed.
        setNotes([]);
        setNotesError(describeApiError(err));
      });
    api
      .inboxStatus(vaultKey)
      .then((status) => setInboxCount(status.count))
      .catch(() => setInboxCount(null));
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
        if (!controller.signal.aborted) setSearchResults(hits);
      })
      .catch(() => {
        if (!controller.signal.aborted) setSearchResults([]);
      });
    return () => controller.abort();
  }, [debouncedQuery, vaultKey]);

  function onQueryChange(text: string) {
    setQuery(text);
    // Clearing the box clears the results at once — nothing to wait for.
    if (!text.trim()) setSearchResults(null);
  }

  const groups = useMemo(() => groupByFolder(notes ?? []), [notes]);
  const vault = vaults.find((v) => v.key === vaultKey) ?? null;

  return (
    <div className="stack">
      <section className="searchrow">
        <select
          className="vaultpick"
          value={vaultKey}
          onChange={(event) => onSwitchVault(event.target.value)}
          aria-label="Vault"
        >
          {vaults.map((v) => (
            <option key={v.key} value={v.key}>
              {v.key}
            </option>
          ))}
        </select>
        <label className="searchbox">
          <SearchIcon className="icon--sm" />
          <input
            ref={searchInput}
            value={query}
            onChange={(event) => onQueryChange(event.target.value)}
            placeholder={`Search ${vaultKey} — keywords, ${vault?.note_count ?? 0} notes`}
            aria-label="Search this vault"
          />
          {searchResults ? (
            <span className="t-meta">{searchResults.length} results</span>
          ) : null}
        </label>
      </section>

      <section className="explorer">
        <div className="pane pane--tree">
          <div className="pane__head">
            <span className="t-over">Notes</span>
            {inboxCount ? (
              <span
                className="badge badge--warn"
                title="Captures waiting in the inbox folder below"
              >
                <span className="dot dot--warn" />
                {inboxCount} uncurated
              </span>
            ) : null}
          </div>
          <div className="pane__body scrollpane">
            {searchResults ? (
              <div className="tree">
                {searchResults.length === 0 ? (
                  <p className="t-xs t-subtle">No matches for "{query}".</p>
                ) : (
                  searchResults.map((hit) => (
                    <button
                      key={hit.permalink}
                      type="button"
                      className={[
                        "tree__row",
                        hit.permalink === selected ? "tree__row--on" : "",
                      ]
                        .filter(Boolean)
                        .join(" ")}
                      onClick={() => setSelected(hit.permalink)}
                    >
                      {hit.title}
                    </button>
                  ))
                )}
              </div>
            ) : notes === null ? (
              <Skeleton height={200} />
            ) : notesError ? (
              <div
                className="empty"
                style={{ padding: "var(--space-6) var(--space-2)" }}
              >
                <p className="t-sm t-muted">
                  Could not load this vault's notes.
                </p>
                <p className="t-xs t-subtle">{notesError}</p>
              </div>
            ) : groups.length === 0 ? (
              <div
                className="empty"
                style={{ padding: "var(--space-6) var(--space-2)" }}
              >
                <p className="t-sm t-muted">No folders yet.</p>
                <p className="t-xs t-subtle">
                  Structure appears as knowledge arrives — nothing to design up
                  front.
                </p>
              </div>
            ) : (
              <div className="tree">
                {groups.map((group) => (
                  <div key={group.folder || "·"}>
                    {group.folder ? (
                      <div className="tree__row tree__row--dir">
                        {group.folder}
                      </div>
                    ) : null}
                    {group.notes.map((item) => (
                      <button
                        key={item.permalink}
                        type="button"
                        className={[
                          "tree__row",
                          item.permalink === selected ? "tree__row--on" : "",
                        ]
                          .filter(Boolean)
                          .join(" ")}
                        onClick={() => setSelected(item.permalink)}
                      >
                        <span className="tree__ind" />
                        {item.title}
                      </button>
                    ))}
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>

        {selected ? (
          <NotePane
            key={selected}
            vaultKey={vaultKey}
            permalink={selected}
            onSelect={setSelected}
          />
        ) : (
          <>
            <div className="pane">
              <div className="pane__body">
                <EmptyState
                  mark={<ExplorerIcon className="icon--lg" />}
                  title="Pick a note."
                >
                  Select one from the tree on the left, or search above.
                </EmptyState>
              </div>
            </div>
            <div className="pane pane--ctx">
              <div className="pane__head">
                <span className="t-over">Context</span>
              </div>
              <div className="ctx__block">
                <span className="t-over">Vault</span>
                <p className="t-sm">
                  {vault?.purpose ?? "No purpose set yet."}
                </p>
                <p className="t-xs t-subtle">
                  {vault?.note_count ?? 0} notes on disk.
                </p>
                <Link className="btn btn--sm btn--primary" to="/clients">
                  <VaultsIcon className="icon--sm" />
                  Connect a client
                </Link>
              </div>
            </div>
          </>
        )}
      </section>
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
  const [commits, setCommits] = useState<
    { sha: string; subject: string }[] | null
  >(null);

  useEffect(() => {
    // Issue 378: a failed read used to leave the skeleton up for good.
    // (`NotePane` is keyed by permalink, so a new note starts clean.)
    api
      .readNote(vaultKey, permalink)
      .then(setNote)
      .catch((err: unknown) => {
        setNote(null);
        setNoteError(describeApiError(err));
      });
    api
      .noteGraph(vaultKey, permalink)
      .then(setGraph)
      .catch((err: unknown) => {
        setGraph(null);
        setGraphError(describeApiError(err));
      });
    api
      .noteHistory(vaultKey, permalink)
      .then(setCommits)
      .catch(() => setCommits([]));
  }, [vaultKey, permalink]);

  return (
    <>
      <div className="pane">
        <div className="pane__head">
          <div className="row" style={{ gap: 8 }}>
            <span className="t-over">Note</span>
            <span className="chip chip--mono">{permalink}</span>
          </div>
        </div>
        {note === null ? (
          <div className="pane__body">
            {noteError ? (
              <p className="t-sm t-muted">
                Could not load this note: {noteError}
              </p>
            ) : (
              <Skeleton height={200} />
            )}
          </div>
        ) : (
          <article className="note scrollpane">
            <h2 className="note__title">{note.title}</h2>
            <div className="note__meta">
              <span className="chip">{note.type}</span>
              {note.tags.map((tag) => (
                <span className="chip" key={tag}>
                  {tag}
                </span>
              ))}
              {note.modified ? (
                <span className="t-meta">updated {note.modified}</span>
              ) : null}
            </div>
            <p className="note__body">{note.body}</p>
          </article>
        )}
      </div>

      <div className="pane pane--ctx">
        <div className="pane__head">
          <span className="t-over">Context</span>
        </div>
        <div className="ctx scrollpane">
          <div className="ctx__block">
            <span className="t-over">Fields</span>
            {note ? (
              <dl className="fm">
                <dt>type</dt>
                <dd>{note.type}</dd>
                <dt>tags</dt>
                <dd>{note.tags.join(", ") || "—"}</dd>
                <dt>created</dt>
                <dd>{note.created || "—"}</dd>
                <dt>permalink</dt>
                <dd>{note.permalink}</dd>
              </dl>
            ) : noteError ? (
              <p className="t-xs t-subtle">Not available.</p>
            ) : (
              <Skeleton height={60} />
            )}
          </div>
          <div className="ctx__block">
            <div className="row row--between">
              <span className="t-over">Local graph</span>
              <span className="t-xs t-subtle">1 hop</span>
            </div>
            {graph === null ? (
              graphError ? (
                <p className="t-xs t-subtle">
                  Could not load the graph: {graphError}
                </p>
              ) : (
                <Skeleton height={60} />
              )
            ) : graph.outbound.length === 0 && graph.inbound.length === 0 ? (
              <p className="t-xs t-subtle">
                Nothing links to or from this note yet.
              </p>
            ) : (
              <>
                {graph.outbound.length > 0 ? (
                  <div>
                    <span className="t-xs t-subtle">Links to</span>
                    <ul className="factline">
                      {graph.outbound.map((n) => (
                        <li key={n.permalink}>
                          <span className="fact-dot" />
                          <button
                            type="button"
                            className="wlink linklike"
                            onClick={() => onSelect(n.permalink)}
                          >
                            {n.title}
                          </button>
                        </li>
                      ))}
                    </ul>
                  </div>
                ) : null}
                {graph.inbound.length > 0 ? (
                  <div>
                    <span className="t-xs t-subtle">Linked from</span>
                    <ul className="factline">
                      {graph.inbound.map((n) => (
                        <li key={n.permalink}>
                          <span className="fact-dot" />
                          <button
                            type="button"
                            className="wlink linklike"
                            onClick={() => onSelect(n.permalink)}
                          >
                            {n.title}
                          </button>
                        </li>
                      ))}
                    </ul>
                  </div>
                ) : null}
              </>
            )}
          </div>
          <div className="ctx__block">
            <span className="t-over">History</span>
            {commits === null ? (
              <Skeleton height={40} />
            ) : commits.length === 0 ? (
              <p className="t-xs t-subtle">No history yet.</p>
            ) : (
              <div className="stack stack--2">
                {commits.slice(0, 5).map((commit) => (
                  <div className="commitrow" key={commit.sha}>
                    <code>{commit.sha.slice(0, 7)}</code>
                    <span className="grow">
                      {commit.subject.split("\n")[0]}
                    </span>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>
      </div>
    </>
  );
}
