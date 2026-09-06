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
import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";

import { EmptyState } from "../components/EmptyState";
import { Skeleton } from "../components/Skeleton";
import type { LocalGraph, NoteRecord, NoteSummary, SearchHit, VaultSummary } from "../lib/api/client";
import { api } from "../lib/api/client";
import { ExplorerIcon, SearchIcon, VaultsIcon } from "../shell/icons";

interface FolderGroup {
  folder: string;
  notes: NoteSummary[];
}

function groupByFolder(notes: NoteSummary[]): FolderGroup[] {
  const groups = new Map<string, NoteSummary[]>();
  for (const note of notes) {
    if (note.folder.startsWith("inbox")) continue; // the inbox has its own count, not a tree slot
    const bucket = groups.get(note.folder) ?? [];
    bucket.push(note);
    groups.set(note.folder, bucket);
  }
  return [...groups.entries()]
    .sort(([a], [b]) => a.localeCompare(b))
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
      <EmptyState mark={<ExplorerIcon className="icon--lg" />} title="No vault exists yet.">
        <Link to="/onboarding">The setup wizard</Link> creates your first one — or an operator
        can register one directly with the vault registry. Once a vault exists, its notes show up
        here automatically.
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
  const [inboxCount, setInboxCount] = useState<number | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [searchResults, setSearchResults] = useState<SearchHit[] | null>(null);

  useEffect(() => {
    api
      .listNotes(vaultKey)
      .then(setNotes)
      .catch(() => setNotes([]));
    api
      .inboxStatus(vaultKey)
      .then((status) => setInboxCount(status.count))
      .catch(() => setInboxCount(null));
  }, [vaultKey]);

  function runSearch(text: string) {
    setQuery(text);
    if (!text.trim()) {
      setSearchResults(null);
      return;
    }
    api
      .search(vaultKey, text)
      .then(setSearchResults)
      .catch(() => setSearchResults([]));
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
            value={query}
            onChange={(event) => runSearch(event.target.value)}
            placeholder={`Search ${vaultKey} — keywords, ${vault?.note_count ?? 0} notes`}
            aria-label="Search this vault"
          />
          {searchResults ? <span className="t-meta">{searchResults.length} results</span> : null}
        </label>
      </section>

      <section className="explorer">
        <div className="pane pane--tree">
          <div className="pane__head">
            <span className="t-over">Notes</span>
            {inboxCount ? (
              <Link className="badge badge--warn" to="/inbox">
                <span className="dot dot--warn" />
                {inboxCount} uncurated
              </Link>
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
                      className={["tree__row", hit.permalink === selected ? "tree__row--on" : ""]
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
            ) : groups.length === 0 ? (
              <div className="empty" style={{ padding: "var(--space-6) var(--space-2)" }}>
                <p className="t-sm t-muted">No folders yet.</p>
                <p className="t-xs t-subtle">
                  Structure appears as knowledge arrives — nothing to design up front.
                </p>
              </div>
            ) : (
              <div className="tree">
                {groups.map((group) => (
                  <div key={group.folder || "·"}>
                    {group.folder ? (
                      <div className="tree__row tree__row--dir">{group.folder}</div>
                    ) : null}
                    {group.notes.map((item) => (
                      <button
                        key={item.permalink}
                        type="button"
                        className={["tree__row", item.permalink === selected ? "tree__row--on" : ""]
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
          <NotePane key={selected} vaultKey={vaultKey} permalink={selected} onSelect={setSelected} />
        ) : (
          <>
            <div className="pane">
              <div className="pane__body">
                <EmptyState mark={<ExplorerIcon className="icon--lg" />} title="Pick a note.">
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
                <p className="t-sm">{vault?.purpose ?? "No purpose set yet."}</p>
                <p className="t-xs t-subtle">{vault?.note_count ?? 0} notes on disk.</p>
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
  const [graph, setGraph] = useState<LocalGraph | null>(null);
  const [commits, setCommits] = useState<{ sha: string; subject: string }[] | null>(null);

  useEffect(() => {
    api
      .readNote(vaultKey, permalink)
      .then(setNote)
      .catch(() => setNote(null));
    api
      .noteGraph(vaultKey, permalink)
      .then(setGraph)
      .catch(() => setGraph(null));
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
            <Skeleton height={200} />
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
              {note.modified ? <span className="t-meta">updated {note.modified}</span> : null}
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
              <Skeleton height={60} />
            ) : graph.outbound.length === 0 && graph.inbound.length === 0 ? (
              <p className="t-xs t-subtle">Nothing links to or from this note yet.</p>
            ) : (
              <>
                {graph.outbound.length > 0 ? (
                  <div>
                    <span className="t-xs t-subtle">Links to</span>
                    <ul className="factline">
                      {graph.outbound.map((n) => (
                        <li key={n.permalink}>
                          <span className="fact-dot" />
                          <button type="button" className="wlink linklike" onClick={() => onSelect(n.permalink)}>
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
                          <button type="button" className="wlink linklike" onClick={() => onSelect(n.permalink)}>
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
                    <span className="grow">{commit.subject.split("\n")[0]}</span>
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
