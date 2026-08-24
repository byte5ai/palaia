/**
 * SPEC-304: the marketplace screen — browse (SPEC-303's merged model:
 * the official registry, palaia's curated index, and manual entries, all
 * in one shape), install with one click, see health and updates.
 *
 * Every install goes through the same two steps regardless of kind: this
 * screen's own consent panel (deliverable #3 — kind, source, verified
 * state, permissions, always shown before a `POST .../install` can
 * succeed at all: the hub itself refuses one without a fresh consent
 * token) and, for `remote`/`container` entries, a form generated from the
 * entry's `config_schema` (deliverable #2). A `skill`/`mcpb`/`plugin`
 * entry hands off to the Clients page instead — this screen only lists
 * it (MASTERPLAN §5.3, and this SPEC's own words: "the marketplace lists
 * them, it does not reinvent their delivery").
 */
import { useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";

import {
  Badge,
  Button,
  Card,
  CardBody,
  CardHead,
  ConfigSchemaForm,
  EmptyState,
  missingRequiredFields,
  Segmented,
  useToast,
  type ConfigFormValues,
} from "../components";
import type {
  GatewayProfile,
  InstalledAddon,
  MarketEntry,
  MarketEntryKind,
  MarketProvenance,
} from "../lib/api/client";
import { api, ApiError } from "../lib/api/client";
import { InfoIcon, MarketplaceIcon, WarningIcon } from "../shell/icons";

const HANDED_OFF_KINDS: MarketEntryKind[] = ["skill", "mcpb", "plugin"];

const KIND_LABEL: Record<MarketEntryKind, string> = {
  remote: "Remote server",
  container: "Runs in a container",
  mcpb: "Downloadable bundle",
  skill: "Skill",
  plugin: "Plugin",
};

const SOURCE_FILTERS: { value: MarketProvenance | "all"; label: string }[] = [
  { value: "all", label: "Everything" },
  { value: "curated", label: "Curated" },
  { value: "registry", label: "Community registry" },
  { value: "manual", label: "Added by hand" },
];

function describeError(err: unknown): string {
  if (err instanceof ApiError) {
    const body = err.body as { detail?: string } | undefined;
    if (body?.detail) return body.detail;
    return `The hub answered ${err.status}.`;
  }
  return "Could not reach the hub.";
}

function declaredMounts(entry: MarketEntry): string[] {
  const properties = entry.config_schema?.properties ?? {};
  return Object.entries(properties)
    .filter(([, prop]) => prop.format === "path")
    .map(([key, prop]) => prop.title || key);
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
  const mounts = declaredMounts(entry);
  const missing = missingRequiredFields(entry.config_schema, config);

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
      toast.show(`${entry.name} installed.`);
      onInstalled();
    } catch (err) {
      setError(describeError(err));
    } finally {
      setInstalling(false);
    }
  }

  return (
    <div className="stack stack--3">
      {!entry.verified ? (
        <div className="banner banner--warn">
          <WarningIcon className="icon icon--sm" />
          <div>
            <p className="banner__title">Not checked by palaia</p>
            <p className="t-sm t-muted">
              {entry.provenance === "manual"
                ? "You added this one yourself — palaia has not reviewed it."
                : "This came from the open community registry, which anyone can publish to."}
            </p>
          </div>
        </div>
      ) : null}

      <div className="stack stack--2">
        <span className="field__label">What it needs</span>
        {entry.permissions.length === 0 ? (
          <p className="t-xs t-muted">Nothing beyond running.</p>
        ) : (
          <p className="t-xs t-muted">{entry.permissions.join(", ")}</p>
        )}
        {entry.kind === "container" ? (
          <p className="t-xs t-muted">Image: {entry.source.value}</p>
        ) : null}
        {mounts.length > 0 ? (
          <p className="t-xs t-muted">Folders it will read and write: {mounts.join(", ")}</p>
        ) : null}
      </div>

      <ConfigSchemaForm schema={entry.config_schema} values={config} onChange={setConfig} />

      {profiles.length > 0 ? (
        <div className="stack stack--2">
          <span className="field__label">Which clients should see it</span>
          {profiles.map((profile) => (
            <label key={profile.path} className="row" style={{ gap: 8 }}>
              <input
                type="checkbox"
                checked={selectedProfiles.has(profile.path)}
                onChange={(event) => toggleProfile(profile.path, event.target.checked)}
              />
              <span className="t-sm">{profile.label ?? profile.path}</span>
            </label>
          ))}
        </div>
      ) : null}

      {error ? <p className="field__error">{error}</p> : null}

      <div className="row">
        <Button
          variant="primary"
          onClick={install}
          disabled={installing || missing.length > 0}
        >
          {installing ? "Installing…" : "Install and connect"}
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

  return (
    <Card>
      <CardHead title={entry.name} meta={KIND_LABEL[entry.kind]}>
        <Button variant="ghost" size="sm" onClick={onToggle} aria-expanded={open}>
          {open ? "Close" : "Details"}
        </Button>
      </CardHead>
      <CardBody className="stack stack--2">
        <div className="row row--wrap" style={{ gap: 6 }}>
          <Badge variant={entry.verified ? "ok" : "warn"}>
            {entry.verified ? "Checked by palaia" : "Not checked"}
          </Badge>
          <span className="t-xs t-subtle">by {entry.maintainer}</span>
        </div>
        <p className="t-sm t-muted">{entry.one_liner}</p>

        {open ? (
          handedOff ? (
            <div className="stack stack--2">
              <p className="t-sm t-muted">
                Set this one up from the Clients page — it is delivered straight to the
                client you connect, not through this hub.
              </p>
              <Link className="btn btn--primary" to="/clients">
                Go to Clients
              </Link>
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
  const [busy, setBusy] = useState(false);
  const [confirming, setConfirming] = useState(false);

  async function update() {
    setBusy(true);
    try {
      await api.updateInstalledAddon(addon.upstream_key);
      toast.show(`${addon.name} updated.`);
      onChanged();
    } catch (err) {
      toast.show(describeError(err));
    } finally {
      setBusy(false);
    }
  }

  async function uninstall() {
    setBusy(true);
    try {
      await api.uninstallAddon(addon.upstream_key);
      toast.show(`${addon.name} removed.`);
      onChanged();
    } catch (err) {
      toast.show(describeError(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="listrow">
      <div style={{ flex: 1, minWidth: 0 }}>
        <div className="listrow__title">{addon.name}</div>
        <div className="listrow__meta">{addon.status}</div>
      </div>
      <div className="row" style={{ gap: 6 }}>
        <Badge variant={addon.up ? "ok" : "risk"}>{addon.up ? "running" : "not running"}</Badge>
        {addon.update_available ? (
          <Button size="sm" onClick={update} disabled={busy}>
            {busy ? "Updating…" : "Update"}
          </Button>
        ) : null}
        {confirming ? (
          <>
            <Button size="sm" variant="ghost" onClick={() => setConfirming(false)} disabled={busy}>
              Never mind
            </Button>
            <Button size="sm" variant="risk" onClick={uninstall} disabled={busy}>
              Yes, remove it
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

export function Marketplace() {
  const [searchParams] = useSearchParams();
  // The marketplace MCP App's "Install and connect" always deep-links here
  // instead of installing anything itself (MASTERPLAN §5.7) — read once, as
  // the initial value of the one piece of state that already tracks which
  // card is open, rather than a separate effect fighting over it.
  const [openId, setOpenId] = useState<string | null>(() => searchParams.get("install"));
  const [query, setQuery] = useState("");
  const [source, setSource] = useState<MarketProvenance | "all">("all");
  const [entries, setEntries] = useState<MarketEntry[] | null>(null);
  const [stale, setStale] = useState(false);
  const [profiles, setProfiles] = useState<GatewayProfile[]>([]);
  const [installed, setInstalled] = useState<InstalledAddon[] | null>(null);

  function refreshInstalled() {
    api
      .listInstalledAddons()
      .then(setInstalled)
      .catch(() => setInstalled([]));
  }

  useEffect(() => {
    api
      .searchMarket(query, source === "all" ? undefined : source)
      .then((result) => {
        setEntries(result.entries);
        setStale(result.stale);
      })
      .catch(() => {
        setEntries([]);
      });
  }, [query, source]);

  useEffect(() => {
    api.listGatewayProfiles().then(setProfiles).catch(() => setProfiles([]));
    refreshInstalled();
  }, []);

  // The deep-linked entry might not be in the current search results at
  // all (a curated entry reached from outside any query) — fetch it once
  // and fold it in, so its consent panel (already open, above) has
  // something real to show.
  useEffect(() => {
    if (!openId || entries === null || entries.some((e) => e.id === openId)) return;
    api
      .getMarketEntry(openId)
      .then((entry) => setEntries((prev) => [entry, ...(prev ?? [])]))
      .catch(() => {
        // The linked entry no longer exists — the panel below already
        // says plainly that nothing matched, no extra handling needed.
      });
  }, [openId, entries]);

  return (
    <section className="stack stack--4">
      <div className="row row--wrap" style={{ justifyContent: "space-between" }}>
        <p className="t-sm t-muted" style={{ maxWidth: 560 }}>
          Add-ons for every client at once: browse, install with one click, and see what needs
          updating — all from here.
        </p>
      </div>

      <div className="row row--wrap" style={{ gap: 12 }}>
        <input
          className="input"
          style={{ maxWidth: 280 }}
          placeholder="Search add-ons…"
          value={query}
          onChange={(event) => setQuery(event.target.value)}
        />
        <Segmented options={SOURCE_FILTERS} value={source} onChange={setSource} />
      </div>

      {stale ? (
        <div className="banner banner--warn">
          <InfoIcon className="icon icon--sm" />
          <p className="t-sm t-muted">
            Showing the last copy palaia saved — it could not reach every source just now.
          </p>
        </div>
      ) : null}

      {entries && entries.length === 0 ? (
        <EmptyState mark={<MarketplaceIcon className="icon--lg" />} title="Nothing matched.">
          Try a different search, or check back once the curated list grows.
        </EmptyState>
      ) : (
        <div className="stack stack--3">
          {(entries ?? []).map((entry) => (
            <EntryCard
              key={entry.id}
              entry={entry}
              open={openId === entry.id}
              onToggle={() => setOpenId((current) => (current === entry.id ? null : entry.id))}
              profiles={profiles}
              onInstalled={() => {
                setOpenId(null);
                refreshInstalled();
              }}
            />
          ))}
        </div>
      )}

      {installed && installed.length > 0 ? (
        <div className="stack stack--2">
          <span className="field__label">Installed</span>
          <Card>
            {installed.map((addon) => (
              <InstalledRow key={addon.upstream_key} addon={addon} onChanged={refreshInstalled} />
            ))}
          </Card>
        </div>
      ) : null}
    </section>
  );
}
