import {
  type ComponentType,
  type KeyboardEvent,
  type SVGProps,
  useEffect,
  useId,
  useMemo,
  useRef,
  useState,
} from "react";
import { createPortal } from "react-dom";
import { useNavigate } from "react-router-dom";

import { api } from "../lib/api/client";
import { CLIENTS } from "../lib/clients";
import { describeApiError } from "../lib/errors";
import { matchesQuery, NOTE_QUERY_MIN, NOTE_RESULT_LIMIT, notePath } from "../lib/palette";
import { type ThemeMode, useTheme } from "../lib/theme";
import { SEARCH_DEBOUNCE_MS, useDebouncedValue } from "../lib/useDebouncedValue";
import { SETTINGS_AREAS } from "../routes/settings/settingsAreas";
import {
  AgentsIcon,
  AppearanceIcon,
  ClientsIcon,
  ReviewIcon,
  SearchIcon,
  SettingsIcon,
  SignOutIcon,
  VaultsIcon,
} from "./icons";
import { NAV_ITEMS } from "./navConfig";

type Icon = ComponentType<SVGProps<SVGSVGElement>>;
type Group = "Go to" | "Actions" | "Notes";

interface Command {
  id: string;
  group: Group;
  label: string;
  icon: Icon;
  /** Right-aligned context: the memory a note is in. */
  hint?: string;
  /** Extra words the command is found by. */
  keywords?: string;
  /** Listed before anything is typed. */
  primary?: boolean;
  run: () => void;
}

const GROUPS: Group[] = ["Go to", "Actions", "Notes"];

const APPEARANCE: { mode: ThemeMode; label: string }[] = [
  { mode: "light", label: "Use the light appearance" },
  { mode: "dark", label: "Use the dark appearance" },
  { mode: "system", label: "Follow the system appearance" },
];

/** What Settings areas are also known as. */
const SETTINGS_KEYWORDS: Record<string, string> = {
  "/settings": "preferences general appearance theme",
  "/settings/access": "password login public private cloud address",
  "/settings/backups": "backup download restore export",
  "/settings/telegram": "bot chat",
  "/settings/advanced": "tool sets memory use restart",
  "/settings/about": "version update release",
};

interface NoteHit {
  memory: string;
  permalink: string;
  title: string;
  score: number;
}

type NoteSearch =
  | { state: "idle" }
  | { state: "done"; query: string; hits: NoteHit[] }
  | { state: "failed"; query: string; message: string };

/**
 * The command palette: one field that reaches every page, a few actions and
 * the notes of all memories. ⌘K / Ctrl+K or `/` opens it (`AppShell`), the
 * arrow keys move, Enter opens, Escape closes; focus returns to where it was.
 *
 * It is a combobox over a grouped listbox: focus stays in the field and the
 * highlighted row is announced through `aria-activedescendant`.
 */
export function CommandPalette({
  open,
  onClose,
  onSignOut,
}: {
  open: boolean;
  onClose: () => void;
  /** Present when someone is signed in: adds "Sign out". */
  onSignOut?: () => void;
}) {
  if (!open) return null;
  // Mounted per opening, so every opening starts empty.
  return <OpenPalette onClose={onClose} onSignOut={onSignOut} />;
}

function OpenPalette({ onClose, onSignOut }: { onClose: () => void; onSignOut?: () => void }) {
  const navigate = useNavigate();
  const { mode, setMode } = useTheme();
  const listId = useId();
  const inputRef = useRef<HTMLInputElement>(null);
  const listRef = useRef<HTMLDivElement>(null);
  const [query, setQuery] = useState("");
  const [activeId, setActiveId] = useState<string | null>(null);
  const [memories, setMemories] = useState<string[] | null>(null);
  const [noteSearch, setNoteSearch] = useState<NoteSearch>({ state: "idle" });

  // Focus moves in, the page behind stops scrolling, and focus goes back.
  useEffect(() => {
    const previous = document.activeElement as HTMLElement | null;
    inputRef.current?.focus();
    const { overflow } = document.body.style;
    document.body.style.overflow = "hidden";
    return () => {
      document.body.style.overflow = overflow;
      previous?.focus?.();
    };
  }, []);

  useEffect(() => {
    let cancelled = false;
    api
      .listVaults()
      .then((list) => {
        if (!cancelled) setMemories(list.map((vault) => vault.key));
      })
      .catch(() => {
        // Places and actions still work; the note search says what failed.
        if (!cancelled) setMemories([]);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const text = query.trim();
  const debounced = useDebouncedValue(text, SEARCH_DEBOUNCE_MS);
  useEffect(() => {
    if (debounced.length < NOTE_QUERY_MIN || memories === null || memories.length === 0) return;
    const controller = new AbortController();
    Promise.allSettled(
      memories.map((memory) =>
        api
          .search(memory, debounced, controller.signal)
          .then((hits) => hits.map((hit) => ({ memory, permalink: hit.permalink, title: hit.title, score: hit.score }))),
      ),
    ).then((results) => {
      if (controller.signal.aborted) return;
      const failed = results.find((result) => result.status === "rejected");
      if (failed && results.every((result) => result.status === "rejected")) {
        setNoteSearch({ state: "failed", query: debounced, message: describeApiError(failed.reason) });
        return;
      }
      const hits = results
        .flatMap((result) => (result.status === "fulfilled" ? result.value : []))
        .sort((a, b) => b.score - a.score)
        .slice(0, NOTE_RESULT_LIMIT);
      setNoteSearch({ state: "done", query: debounced, hits });
    });
    return () => controller.abort();
  }, [debounced, memories]);

  const commands = useMemo<Command[]>(() => {
    const go = (path: string) => () => navigate(path);
    const places: Command[] = [];
    for (const item of NAV_ITEMS) {
      places.push({
        id: `go:${item.path}`,
        group: "Go to",
        label: item.label,
        icon: item.icon,
        primary: true,
        run: go(item.path),
      });
      if (item.path === "/memories") {
        places.push({
          id: "go:/memories/review",
          group: "Go to",
          label: "Needs review",
          icon: ReviewIcon,
          keywords: "memories proposals approve",
          primary: true,
          run: go("/memories/review"),
        });
      }
      if (item.path === "/apps") {
        places.push({
          id: "go:/apps/sessions",
          group: "Go to",
          label: "Live sessions",
          icon: AgentsIcon,
          keywords: "ai apps agents running",
          primary: true,
          run: go("/apps/sessions"),
        });
      }
    }
    for (const area of SETTINGS_AREAS) {
      places.push({
        id: `go:${area.to}`,
        group: "Go to",
        label: area.end ? "Settings" : `Settings: ${area.label}`,
        icon: SettingsIcon,
        keywords: SETTINGS_KEYWORDS[area.to],
        primary: area.end,
        run: go(area.to),
      });
    }

    const actions: Command[] = [
      ...CLIENTS.map((client) => ({
        id: `connect:${client.id}`,
        group: "Actions" as const,
        label: client.id === "generic" ? "Connect another AI app" : `Connect ${client.name}`,
        icon: ClientsIcon,
        keywords: "ai app add set up",
        run: go(`/apps?app=${encodeURIComponent(client.id)}`),
      })),
      ...APPEARANCE.filter((entry) => entry.mode !== mode).map((entry) => ({
        id: `appearance:${entry.mode}`,
        group: "Actions" as const,
        label: entry.label,
        icon: AppearanceIcon,
        keywords: "theme mode colours colors",
        primary: true,
        run: () => setMode(entry.mode),
      })),
    ];
    if (onSignOut) {
      actions.push({
        id: "sign-out",
        group: "Actions",
        label: "Sign out",
        icon: SignOutIcon,
        keywords: "log out logout",
        run: onSignOut,
      });
    }
    return [...places, ...actions];
  }, [navigate, mode, setMode, onSignOut]);

  // Results for the text as typed; notes only once their answer is for it.
  const notesCurrent = noteSearch.state !== "idle" && noteSearch.query === text;
  const noteCommands: Command[] =
    notesCurrent && noteSearch.state === "done"
      ? noteSearch.hits.map((hit) => ({
          id: `note:${hit.memory}:${hit.permalink}`,
          group: "Notes" as const,
          label: hit.title,
          icon: VaultsIcon,
          hint: hit.memory,
          run: () => navigate(notePath(hit.memory, hit.permalink)),
        }))
      : [];
  const visible = [
    ...commands.filter((command) => (text ? matchesQuery(command, text) : command.primary)),
    ...noteCommands,
  ];
  const active = visible.find((command) => command.id === activeId) ?? visible[0] ?? null;

  const searchesNotes = text.length >= NOTE_QUERY_MIN && (memories === null || memories.length > 0);
  const notesPending = searchesNotes && !notesCurrent;
  const notesFailed = notesCurrent && noteSearch.state === "failed" ? noteSearch.message : null;

  useEffect(() => {
    if (!active) return;
    const row = listRef.current?.querySelector<HTMLElement>(`[data-command="${CSS.escape(active.id)}"]`);
    row?.scrollIntoView?.({ block: "nearest" });
  }, [active]);

  function choose(command: Command) {
    onClose();
    command.run();
  }

  function onKeyDown(event: KeyboardEvent<HTMLInputElement>) {
    if (event.key === "Escape") {
      event.preventDefault();
      // A dialog underneath keeps its own Escape for the next press.
      event.stopPropagation();
      event.nativeEvent.stopImmediatePropagation();
      onClose();
      return;
    }
    if (event.key === "Tab") {
      // The field is the only stop: focus stays in the palette.
      event.preventDefault();
      return;
    }
    if (event.key === "Enter") {
      event.preventDefault();
      if (active) choose(active);
      return;
    }
    if (visible.length === 0) return;
    const index = active ? visible.indexOf(active) : 0;
    let next: number | null = null;
    if (event.key === "ArrowDown") next = (index + 1) % visible.length;
    else if (event.key === "ArrowUp") next = (index - 1 + visible.length) % visible.length;
    else if (event.key === "Home") next = 0;
    else if (event.key === "End") next = visible.length - 1;
    if (next === null) return;
    event.preventDefault();
    setActiveId(visible[next].id);
  }

  const optionId = (command: Command) => `${listId}-${visible.indexOf(command)}`;
  let status: string;
  if (notesPending) status = "Searching notes…";
  else if (visible.length === 0) status = "No results";
  else status = visible.length === 1 ? "1 result" : `${visible.length} results`;

  return createPortal(
    <div
      className="palette-scrim"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) onClose();
      }}
    >
      <div className="palette" role="dialog" aria-modal="true" aria-label="Search or jump to">
        <div className="palette__search">
          <SearchIcon className="icon" />
          <input
            ref={inputRef}
            role="combobox"
            aria-expanded="true"
            aria-controls={listId}
            aria-activedescendant={active ? optionId(active) : undefined}
            aria-autocomplete="list"
            aria-label="Search or jump to"
            placeholder="Search notes, pages and actions"
            autoComplete="off"
            spellCheck={false}
            value={query}
            onChange={(event) => {
              setQuery(event.target.value);
              setActiveId(null);
            }}
            onKeyDown={onKeyDown}
          />
          <kbd className="kbd palette__esc">esc</kbd>
          <button type="button" className="btn btn--plain btn--sm palette__cancel" onClick={onClose}>
            Cancel
          </button>
        </div>
        <div className="palette__list" id={listId} role="listbox" aria-label="Results" ref={listRef}>
          {GROUPS.map((group) => {
            const rows = visible.filter((command) => command.group === group);
            if (rows.length === 0) return null;
            const headingId = `${listId}-${group.replace(" ", "-")}`;
            return (
              <div className="palette__group" role="group" aria-labelledby={headingId} key={group}>
                <div className="palette__heading" id={headingId}>
                  {group}
                </div>
                {rows.map((command) => {
                  const Glyph = command.icon;
                  return (
                    <div
                      key={command.id}
                      id={optionId(command)}
                      className="palette__option"
                      role="option"
                      aria-selected={command === active}
                      data-command={command.id}
                      onMouseMove={() => {
                        if (command !== active) setActiveId(command.id);
                      }}
                      // Keep the focus in the field while the row is clicked.
                      onMouseDown={(event) => event.preventDefault()}
                      onClick={() => choose(command)}
                    >
                      <Glyph className="icon" />
                      <span className="palette__label">{command.label}</span>
                      {command.hint ? <span className="palette__hint">{command.hint}</span> : null}
                    </div>
                  );
                })}
              </div>
            );
          })}
          {notesPending ? <p className="palette__note">Searching notes…</p> : null}
          {notesFailed ? <p className="palette__note">Notes could not be searched. {notesFailed}</p> : null}
          {visible.length === 0 && !notesPending && !notesFailed ? (
            <p className="palette__note">Nothing matches “{text}”.</p>
          ) : null}
        </div>
        <div className="palette__foot" aria-hidden="true">
          <span>
            <kbd className="kbd">↑</kbd> <kbd className="kbd">↓</kbd> to move
          </span>
          <span>
            <kbd className="kbd">↵</kbd> to open
          </span>
        </div>
        <div className="sr-only" role="status">
          {status}
        </div>
      </div>
    </div>,
    document.body,
  );
}
