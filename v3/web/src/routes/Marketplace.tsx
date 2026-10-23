/**
 * Add-ons (SPEC-304, redesigned for issues 570 and 571): tools installed once in
 * palaia that every connected AI app can use.
 *
 * Two tabs, kept in the address: **Installed** (the default — what runs,
 * what has an update) and **Browse** (SPEC-303's merged list: palaia's
 * reviewed index, the public registry and entries added by hand, in one
 * shape). `?install=<id>` — the add-on MCP App's "Install and connect" link —
 * opens Browse with that entry's install panel.
 *
 * Every install goes through the same two steps regardless of kind: the
 * install panel (kind, source, review state and what it needs — always shown
 * before `POST …/install` can succeed: the hub refuses one without a fresh
 * consent token) and, for `remote`/`container` entries, a form generated
 * from the entry's `config_schema`. A `skill`/`mcpb`/`plugin` entry is set
 * up in the AI app itself, so this page only lists it and hands off.
 */
import { useCallback, useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";

import {
  Button,
  Callout,
  Card,
  CardBody,
  CardHeader,
  ConfigSchemaForm,
  ConfirmDialog,
  Disclosure,
  EmptyState,
  ErrorState,
  LinkButton,
  ListRow,
  LoadingState,
  PageHeader,
  Segmented,
  StatusPill,
  TabPanel,
  Tabs,
  useToast,
  type ConfigFormValues,
} from "../components";
import { missingRequiredFields } from "../lib/configSchema";
import type {
  GatewayProfile,
  InstalledAddon,
  MarketEntry,
  MarketEntryKind,
  MarketProvenance,
  PlanPreview,
} from "../lib/api/client";
import { api } from "../lib/api/client";
import { docsUrl } from "../lib/docs";
import { describeApiError } from "../lib/errors";
import { count } from "../lib/format";
import { SEARCH_DEBOUNCE_MS, useDebouncedValue } from "../lib/useDebouncedValue";
import { MarketplaceIcon, SearchIcon } from "../shell/icons";
import "./addons.css";

const HANDED_OFF_KINDS: MarketEntryKind[] = ["skill", "mcpb", "plugin"];

const KIND_LABEL: Record<MarketEntryKind, string> = {
  remote: "Connects over the internet",
  container: "Runs on this server",
  mcpb: "Installs in Claude Desktop",
  skill: "Skill for an AI app",
  plugin: "Plugin for an AI app",
};

const SOURCE_FILTERS: { value: MarketProvenance | "all"; label: string }[] = [
  { value: "all", label: "All" },
  { value: "curated", label: "Reviewed" },
  { value: "registry", label: "Public" },
  { value: "manual", label: "Added by you" },
];

type View = "installed" | "browse";

/** A publisher worth naming: not the registry's "unknown" placeholder, and
 * a repository address shortened to its host and path. */
function publisherOf(entry: MarketEntry): string | null {
  const raw = (entry.maintainer ?? "").trim();
  if (!raw || raw.toLowerCase() === "unknown") return null;
  return raw.replace(/^https?:\/\//, "").replace(/\/$/, "");
}

/** The hub's own notes may quote config keys in backticks; show plain text. */
function plain(text: string): string {
  return text.replace(/`/g, "");
}

function declaredMounts(entry: MarketEntry): string[] {
  const properties = entry.config_schema?.properties ?? {};
  return Object.entries(properties)
    .filter(([, prop]) => prop.format === "path")
    .map(([key, prop]) => prop.title || key);
}

function ReviewPill({ entry }: { entry: MarketEntry }) {
  return entry.verified ? (
    <StatusPill tone="ok">Reviewed by palaia</StatusPill>
  ) : (
    <StatusPill tone="neutral">Unreviewed</StatusPill>
  );
}

function InstallPanel({
  entry,
  profiles,
  onInstalled,
}: {
  entry: MarketEntry;
  profiles: GatewayProfile[];
  onInstalled: () => void;
}) {
  const toast = useToast();
  const [config, setConfig] = useState<ConfigFormValues>({});
  const [selectedProfiles, setSelectedProfiles] = useState<Set<string>>(
    new Set(profiles.some((p) => p.path === "default") ? ["default"] : []),
  );
  const [installing, setInstalling] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // Issue 349: a community listing resolves to a command only at install
  // time — show that command *before* asking for consent, derived by the
  // same code that will run it. Addresses and images are on the entry.
  const needsPlan = entry.kind === "remote" && entry.source.type === "registry_ref";
  const [plan, setPlan] = useState<PlanPreview | null>(null);
  const [planError, setPlanError] = useState<string | null>(null);
  const mounts = declaredMounts(entry);
  const missing = missingRequiredFields(entry.config_schema, config);

  useEffect(() => {
    if (!needsPlan) return;
    let cancelled = false;
    api
      .getMarketPlan(entry.id)
      .then((preview) => {
        if (!cancelled) setPlan(preview);
      })
      .catch((err: unknown) => {
        if (!cancelled) setPlanError(describeApiError(err));
      });
    return () => {
      cancelled = true;
    };
  }, [entry.id, needsPlan]);

  function toggleProfile(path: string, on: boolean) {
    setSelectedProfiles((prev) => {
      const next = new Set(prev);
      if (on) next.add(path);
      else next.delete(path);
      return next;
    });
  }

  async function install() {
    setInstalling(true);
    setError(null);
    try {
      const { token } = await api.issueMarketConsent(entry.id);
      await api.installMarketEntry(entry.id, {
        consent_token: token,
        config,
        profiles: [...selectedProfiles],
      });
      toast.show(`${entry.name} is installed. Your AI apps can use it now.`);
      onInstalled();
    } catch (err) {
      setError(describeApiError(err));
    } finally {
      setInstalling(false);
    }
  }

  return (
    <div className="stack stack--4 addons-install">
      {!entry.verified ? (
        <Callout tone="warn" title="Not reviewed by palaia">
          {entry.provenance === "manual"
            ? "You added this one yourself."
            : "It comes from the public registry, where anyone can publish. Check what it needs before you install it."}
        </Callout>
      ) : null}

      <div className="stack stack--2">
        <span className="field__label">What it needs</span>
        <ul className="addons-needs">
          <li>
            {entry.permissions.length === 0
              ? "Nothing beyond running."
              : `Access: ${entry.permissions.join(", ")}`}
          </li>
          {entry.kind === "container" ? (
            <li>
              Runs on this server from <code>{entry.source.value}</code>
            </li>
          ) : null}
          {entry.kind === "remote" && entry.source.type === "url" ? (
            <li>
              Connects to <code>{entry.source.value}</code>
            </li>
          ) : null}
          {needsPlan && plan?.kind === "stdio" ? (
            <li data-testid="install-plan">
              Runs on this server: <code>{[plan.command, ...plan.args].join(" ")}</code>
            </li>
          ) : null}
          {needsPlan && plan?.kind === "http" ? (
            <li data-testid="install-plan">
              Connects to <code>{plan.url}</code>
            </li>
          ) : null}
          {needsPlan && !plan && !planError ? <li>Looking up what it would run…</li> : null}
          {mounts.length > 0 ? <li>Folders it reads and writes: {mounts.join(", ")}</li> : null}
        </ul>
        {planError ? (
          <p className="field__error" role="alert">
            Couldn't find out what it would run. {planError}
          </p>
        ) : null}
      </div>

      <ConfigSchemaForm schema={entry.config_schema} values={config} onChange={setConfig} />

      {profiles.length > 1 ? (
        <Disclosure summary="Advanced: which tool sets get it">
          <div className="stack stack--2">
            {profiles.map((profile) => (
              <label key={profile.path} className="checkrow">
                <input
                  type="checkbox"
                  checked={selectedProfiles.has(profile.path)}
                  onChange={(event) => toggleProfile(profile.path, event.target.checked)}
                />
                <span>{profile.label ?? profile.path}</span>
              </label>
            ))}
          </div>
        </Disclosure>
      ) : null}

      {error ? (
        <p className="field__error" role="alert">
          {error}
        </p>
      ) : null}

      <div>
        <Button
          variant="primary"
          onClick={() => void install()}
          loading={installing}
          disabled={missing.length > 0 || (needsPlan && !plan)}
        >
          {installing ? "Installing…" : "Install add-on"}
        </Button>
      </div>
    </div>
  );
}

function EntryCard({
  entry,
  open,
  onToggle,
  profiles,
  onInstalled,
}: {
  entry: MarketEntry;
  open: boolean;
  onToggle: () => void;
  profiles: GatewayProfile[];
  onInstalled: () => void;
}) {
  const handedOff = HANDED_OFF_KINDS.includes(entry.kind);
  const publisher = publisherOf(entry);

  return (
    <Card>
      <CardHeader
        title={entry.name}
        description={entry.one_liner}
        actions={
          <>
            <ReviewPill entry={entry} />
            <Button size="sm" onClick={onToggle} aria-expanded={open}>
              {open ? "Close" : "Details"}
            </Button>
          </>
        }
      />
      <CardBody className="stack stack--3">
        <p className="t-sm t-muted">
          {KIND_LABEL[entry.kind]}
          {publisher ? ` · by ${publisher}` : ""}
        </p>
        {open ? (
          handedOff ? (
            <div className="stack stack--3">
              <p className="t-sm">
                This one is set up in the AI app itself, not in palaia. Open the app's page to
                install it.
              </p>
              <div>
                <LinkButton variant="primary" to="/apps">
                  Go to AI apps
                </LinkButton>
              </div>
            </div>
          ) : (
            <InstallPanel entry={entry} profiles={profiles} onInstalled={onInstalled} />
          )
        ) : null}
      </CardBody>
    </Card>
  );
}

function InstalledRow({ addon, onChanged }: { addon: InstalledAddon; onChanged: () => void }) {
  const toast = useToast();
  const [busy, setBusy] = useState<"update" | "remove" | null>(null);
  const [confirming, setConfirming] = useState(false);

  async function update() {
    setBusy("update");
    try {
      await api.updateInstalledAddon(addon.upstream_key);
      toast.show(`${addon.name} is up to date.`);
      onChanged();
    } catch (err) {
      toast.show(describeApiError(err));
    } finally {
      setBusy(null);
    }
  }

  async function uninstall() {
    setBusy("remove");
    try {
      await api.uninstallAddon(addon.upstream_key);
      toast.show(`${addon.name} is removed.`);
      setConfirming(false);
      onChanged();
    } catch (err) {
      toast.show(describeApiError(err));
    } finally {
      setBusy(null);
    }
  }

  return (
    <>
      <ListRow
        icon={<MarketplaceIcon className="icon" />}
        title={addon.name}
        description={addon.status}
        trailing={
          <span className="addons-row__actions">
            <StatusPill tone={addon.up ? "ok" : "error"}>
              {addon.up ? "Running" : "Not running"}
            </StatusPill>
            {addon.update_available ? (
              <Button size="sm" onClick={() => void update()} loading={busy === "update"} disabled={busy !== null}>
                {busy === "update" ? "Updating…" : "Update"}
              </Button>
            ) : null}
            <Button
              size="sm"
              variant="destructive"
              onClick={() => setConfirming(true)}
              disabled={busy !== null}
            >
              Remove
            </Button>
          </span>
        }
      />
      <ConfirmDialog
        open={confirming}
        onCancel={() => setConfirming(false)}
        onConfirm={() => void uninstall()}
        title={`Remove ${addon.name}?`}
        confirmLabel="Remove add-on"
        destructive
        busy={busy === "remove"}
      >
        <p>Your AI apps can no longer use its tools. You can install it again later.</p>
      </ConfirmDialog>
    </>
  );
}

function InstalledView({
  installed,
  error,
  onRetry,
  onChanged,
  onBrowse,
}: {
  installed: InstalledAddon[] | null;
  error: string | null;
  onRetry: () => void;
  onChanged: () => void;
  onBrowse: () => void;
}) {
  if (installed === null) {
    if (error) {
      return (
        <ErrorState title="Couldn't load your add-ons" details={error} onRetry={onRetry}>
          palaia didn't answer with the list of installed add-ons.
        </ErrorState>
      );
    }
    return <LoadingState label="Loading your add-ons…" />;
  }
  if (installed.length === 0) {
    return (
      <EmptyState
        mark={<MarketplaceIcon className="icon icon--xl" />}
        title="No add-ons installed"
        actions={
          <Button variant="primary" onClick={onBrowse}>
            Browse add-ons
          </Button>
        }
      >
        Add-ons are tools every connected AI app can use, such as reading web pages.
      </EmptyState>
    );
  }
  const updates = installed.filter((addon) => addon.update_available).length;
  return (
    <div className="stack stack--3">
      <p className="t-muted">
        {count(installed.length, "add-on", "add-ons")} installed
        {updates > 0 ? ` · ${count(updates, "update", "updates")} available` : ""}
      </p>
      <Card className="addons-installed">
        {installed.map((addon) => (
          <InstalledRow key={addon.upstream_key} addon={addon} onChanged={onChanged} />
        ))}
      </Card>
    </div>
  );
}

function BrowseView({
  initialOpenId,
  profiles,
  onInstalled,
}: {
  initialOpenId: string | null;
  profiles: GatewayProfile[];
  onInstalled: () => void;
}) {
  // The add-on MCP App's "Install and connect" deep-links here instead of
  // installing anything itself (MASTERPLAN §5.7).
  const [openId, setOpenId] = useState<string | null>(initialOpenId);
  const [query, setQuery] = useState("");
  const [source, setSource] = useState<MarketProvenance | "all">("all");
  const [entries, setEntries] = useState<MarketEntry[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [attempt, setAttempt] = useState(0);
  const [stale, setStale] = useState(false);
  const [notes, setNotes] = useState<Record<string, string>>({});

  // Issue 384: one request per pause in typing, not per keystroke — and the
  // previous one is cancelled, so a slow answer for a shorter query can
  // never overwrite the results of the query actually on screen.
  const debouncedQuery = useDebouncedValue(query, SEARCH_DEBOUNCE_MS);
  useEffect(() => {
    const controller = new AbortController();
    api
      .searchMarket(debouncedQuery, source === "all" ? undefined : source, controller.signal)
      .then((result) => {
        if (controller.signal.aborted) return;
        setEntries(result.entries);
        setError(null);
        setStale(result.stale);
        setNotes(result.notes ?? {});
      })
      .catch((err: unknown) => {
        if (!controller.signal.aborted) setError(describeApiError(err));
      });
    return () => controller.abort();
  }, [debouncedQuery, source, attempt]);

  // The deep-linked entry might not be in the current results at all (a
  // reviewed entry reached from outside any query) — fetch it once and fold
  // it in, so its install panel (already open) has something real to show.
  useEffect(() => {
    if (!openId || entries === null || entries.some((e) => e.id === openId)) return;
    api
      .getMarketEntry(openId)
      .then((entry) => setEntries((prev) => [entry, ...(prev ?? [])]))
      .catch(() => {
        // The linked entry no longer exists; the list says nothing matched.
      });
  }, [openId, entries]);

  return (
    <div className="stack stack--4">
      <div className="addons-filters">
        <label className="searchbox">
          <SearchIcon className="icon icon--sm" />
          <input
            aria-label="Search add-ons"
            placeholder="Search add-ons"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
          />
        </label>
        <Segmented
          options={SOURCE_FILTERS}
          value={source}
          onChange={setSource}
          ariaLabel="Where add-ons come from"
        />
      </div>

      {stale ? (
        <Callout tone="warn" title="Showing a saved copy">
          palaia couldn't reach every source just now, so some add-ons may be out of date.
        </Callout>
      ) : notes.curated ? (
        // Issue 409: no reviewed index is published yet — say what is shown
        // instead, and keep the hub's own note for whoever runs the server.
        <Callout
          tone="info"
          title="These add-ons are not reviewed by palaia"
          actions={
            <a href={docsUrl("/marketplace/")} target="_blank" rel="noreferrer">
              Learn more
            </a>
          }
        >
          <p>The list comes from the public registry, where anyone can publish.</p>
          <Disclosure summary="For the server admin">
            <p>{plain(notes.curated)}</p>
          </Disclosure>
        </Callout>
      ) : null}

      {entries === null ? (
        error ? (
          <ErrorState
            title="Couldn't load add-ons"
            details={error}
            onRetry={() => {
              setError(null);
              setAttempt((n) => n + 1);
            }}
          >
            palaia didn't answer with the list of add-ons.
          </ErrorState>
        ) : (
          <LoadingState label="Loading add-ons…" />
        )
      ) : error ? (
        <ErrorState
          title="Couldn't search add-ons"
          details={error}
          onRetry={() => {
            setError(null);
            setAttempt((n) => n + 1);
          }}
        />
      ) : entries.length === 0 ? (
        <EmptyState mark={<MarketplaceIcon className="icon icon--xl" />} title="No add-ons match">
          Try a different search, or show all sources.
        </EmptyState>
      ) : (
        <div className="stack stack--3">
          {entries.map((entry) => (
            <EntryCard
              key={entry.id}
              entry={entry}
              open={openId === entry.id}
              onToggle={() => setOpenId((current) => (current === entry.id ? null : entry.id))}
              profiles={profiles}
              onInstalled={() => {
                setOpenId(null);
                onInstalled();
              }}
            />
          ))}
        </div>
      )}
    </div>
  );
}

export function Marketplace() {
  const [params, setParams] = useSearchParams();
  const installId = params.get("install");
  const view: View = installId || params.get("view") === "browse" ? "browse" : "installed";
  const [profiles, setProfiles] = useState<GatewayProfile[]>([]);
  const [installed, setInstalled] = useState<InstalledAddon[] | null>(null);
  const [installedError, setInstalledError] = useState<string | null>(null);

  const setView = useCallback(
    (next: View) => {
      setParams(
        (prev) => {
          const updated = new URLSearchParams(prev);
          updated.delete("install");
          if (next === "browse") updated.set("view", "browse");
          else updated.delete("view");
          return updated;
        },
        { replace: true },
      );
    },
    [setParams],
  );

  const refreshInstalled = useCallback(() => {
    api
      .listInstalledAddons()
      .then((list) => {
        setInstalled(list);
        setInstalledError(null);
      })
      .catch((err: unknown) => setInstalledError(describeApiError(err)));
  }, []);

  useEffect(() => {
    api
      .listGatewayProfiles()
      .then(setProfiles)
      .catch(() => setProfiles([]));
    refreshInstalled();
  }, [refreshInstalled]);

  const updates = (installed ?? []).filter((addon) => addon.update_available).length;

  return (
    <div className="stack">
      <PageHeader
        title="Add-ons"
        description="Install a tool once and every connected AI app can use it."
      />
      <Tabs<View>
        label="Add-ons"
        idPrefix="addons"
        value={view}
        onChange={setView}
        items={[
          { id: "installed", label: "Installed", count: updates || undefined },
          { id: "browse", label: "Browse" },
        ]}
      />
      <TabPanel idPrefix="addons" id={view}>
        {view === "installed" ? (
          <InstalledView
            installed={installed}
            error={installedError}
            onRetry={() => {
              setInstalledError(null);
              refreshInstalled();
            }}
            onChanged={refreshInstalled}
            onBrowse={() => setView("browse")}
          />
        ) : (
          <BrowseView
            key={installId ?? "browse"}
            initialOpenId={installId}
            profiles={profiles}
            onInstalled={refreshInstalled}
          />
        )}
      </TabPanel>
    </div>
  );
}
