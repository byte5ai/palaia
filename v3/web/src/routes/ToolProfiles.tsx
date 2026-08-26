/**
 * SPEC-305: the "Tool profiles" screen — MASTERPLAN §5.2's per-client
 * profiles ("Codex gets memory only; Claude Desktop gets everything") as a
 * screen, not a YAML exercise. Everything here reads and writes SPEC-301's
 * REST surface (`/api/gateway/profiles`, `/api/gateway/vaults`) — this
 * screen adds no second write path of its own.
 */
import { useEffect, useState } from "react";

import {
  Badge,
  Button,
  Card,
  CardBody,
  CardFoot,
  CardHead,
  EmptyState,
  LabeledInput,
  SwitchRow,
  useToast,
} from "../components";
import type {
  GatewayProfile,
  GatewayTool,
  GatewayUpstream,
  GatewayVaultIdentity,
  VaultSummary,
} from "../lib/api/client";
import { api, ApiError } from "../lib/api/client";
import { CopyIcon, InfoIcon, ToolsIcon, WarningIcon } from "../shell/icons";

// The eight base actions every vault's memory-tool family carries, and the
// only ones a rename applies to (`palaia_hub.gateway.vault_protocol.
// MEMORY_TOOL_ACTIONS`) — mirrored here as a literal list rather than
// fetched, since it is a closed, versioned set the server itself treats as
// stable API surface (a new action needs its own SPEC either way).
const RENAMEABLE_ACTIONS = [
  "search",
  "read",
  "write",
  "edit",
  "move",
  "delete",
  "list",
  "recent_activity",
] as const;

/** Mirrors `palaia_hub.gateway.naming.sanitize_tool_name` for an *inline*
 * preview only — the server's own sanitization (returned in
 * `GatewayVaultIdentity.sanitized` after a save) is always the source of
 * truth; this just avoids a round-trip for the common case of typing. */
function previewSanitize(raw: string): string {
  let value = raw.replace(/[^a-zA-Z0-9_]+/g, "_").replace(/^_+|_+$/g, "");
  if (/^[0-9]/.test(value)) value = `t_${value}`;
  return value || "tool";
}

function sanitizeProfilePath(raw: string): string {
  const lowered = raw.toLowerCase().replace(/[^a-z0-9-_]+/g, "-");
  return lowered.replace(/^-+|-+$/g, "") || "profile";
}

function describeError(err: unknown): string {
  if (err instanceof ApiError) {
    const body = err.body as { detail?: string } | undefined;
    if (body?.detail) return body.detail;
    return `The hub answered ${err.status}.`;
  }
  return "Could not reach the hub.";
}

function ToolVisibilityList({
  tools,
  hidden,
  onToggle,
}: {
  tools: GatewayTool[];
  hidden: Set<string>;
  onToggle: (name: string, visible: boolean) => void;
}) {
  if (tools.length === 0) {
    return <p className="t-xs t-muted">No tools yet — add a vault first.</p>;
  }
  return (
    <div className="stack stack--2">
      {tools.map((tool) => (
        <label key={tool.name} className="row" style={{ gap: 8, alignItems: "flex-start" }}>
          <input
            type="checkbox"
            checked={!hidden.has(tool.name)}
            onChange={(event) => onToggle(tool.name, event.target.checked)}
          />
          <span className="stack stack--1">
            <span className="t-sm t-mono">{tool.name}</span>
            {tool.description ? (
              <span className="t-xs t-muted">{tool.description.split("\n")[0]}</span>
            ) : null}
          </span>
        </label>
      ))}
    </div>
  );
}

/** SPEC-304 follow-up: the checkbox section next to the vault list — an
 * installed marketplace add-on (or any server connected under Tools &
 * skills) becomes usable by a profile here, the same way a vault does.
 * "Connected tools" rather than "upstream servers": the latter is this
 * codebase's own internal name for the thing, not a word a person reading
 * this screen needs. */
function ConnectedToolsList({
  upstreams,
  selected,
  onToggle,
}: {
  upstreams: GatewayUpstream[];
  selected: Set<string>;
  onToggle: (key: string, on: boolean) => void;
}) {
  if (upstreams.length === 0) {
    return <span className="t-xs t-muted">No external tools connected yet.</span>;
  }
  return (
    <div className="stack stack--2">
      {upstreams.map((upstream) => (
        <label key={upstream.key} className="row" style={{ gap: 8 }}>
          <input
            type="checkbox"
            checked={selected.has(upstream.key)}
            onChange={(event) => onToggle(upstream.key, event.target.checked)}
          />
          <span className="t-sm">{upstream.display_name}</span>
          <span className="t-xs t-subtle">{upstream.up ? "connected" : "not responding"}</span>
        </label>
      ))}
    </div>
  );
}

function ProfileEditForm({
  profile,
  vaults,
  upstreams,
  onSaved,
  onCancel,
}: {
  profile: GatewayProfile;
  vaults: VaultSummary[];
  upstreams: GatewayUpstream[];
  onSaved: () => void;
  onCancel: () => void;
}) {
  const toast = useToast();
  const [label, setLabel] = useState(profile.label ?? "");
  const [selectedVaults, setSelectedVaults] = useState<Set<string>>(new Set(profile.vaults));
  const [selectedUpstreams, setSelectedUpstreams] = useState<Set<string>>(
    new Set(profile.upstreams),
  );
  const [stash, setStash] = useState(profile.stash);
  const [semanticRouting, setSemanticRouting] = useState(profile.semantic_routing);
  const [tools, setTools] = useState<GatewayTool[] | null>(null);
  const [hidden, setHidden] = useState<Set<string>>(new Set(profile.hidden_tools));
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    api
      .listGatewayProfileTools(profile.path)
      .then((list) => {
        if (!cancelled) setTools(list);
      })
      .catch(() => {
        if (!cancelled) setTools([]);
      });
    return () => {
      cancelled = true;
    };
  }, [profile.path]);

  function toggleVault(key: string, on: boolean) {
    setSelectedVaults((prev) => {
      const next = new Set(prev);
      if (on) next.add(key);
      else next.delete(key);
      return next;
    });
  }

  function toggleUpstream(key: string, on: boolean) {
    setSelectedUpstreams((prev) => {
      const next = new Set(prev);
      if (on) next.add(key);
      else next.delete(key);
      return next;
    });
  }

  function toggleTool(name: string, visible: boolean) {
    setHidden((prev) => {
      const next = new Set(prev);
      if (visible) next.delete(name);
      else next.add(name);
      return next;
    });
  }

  async function save() {
    setSaving(true);
    setError(null);
    try {
      await api.updateGatewayProfile(profile.path, {
        label: label.trim() || null,
        vaults: [...selectedVaults],
        stash,
        hidden_tools: [...hidden],
        semantic_routing: semanticRouting,
        upstreams: [...selectedUpstreams],
      });
      toast.show(`${profile.path} saved.`);
      onSaved();
    } catch (err) {
      setError(describeError(err));
    } finally {
      setSaving(false);
    }
  }

  return (
    <CardBody className="stack stack--4">
      <LabeledInput
        label="Display name"
        placeholder={profile.path}
        hint="Cosmetic only — the address stays the same."
        value={label}
        onChange={(event) => setLabel(event.target.value)}
      />

      <div className="stack stack--2">
        <span className="field__label">Vaults this profile can see</span>
        <div className="stack stack--2">
          {vaults.map((vault) => (
            <label key={vault.key} className="row" style={{ gap: 8 }}>
              <input
                type="checkbox"
                checked={selectedVaults.has(vault.key)}
                onChange={(event) => toggleVault(vault.key, event.target.checked)}
              />
              <span className="t-sm">{vault.key}</span>
              {vault.purpose ? <span className="t-xs t-muted">— {vault.purpose}</span> : null}
            </label>
          ))}
          {vaults.length === 0 ? (
            <span className="t-xs t-muted">No vaults exist yet.</span>
          ) : null}
        </div>
      </div>

      <div className="stack stack--2">
        <span className="field__label">Connected tools this profile can use</span>
        <ConnectedToolsList
          upstreams={upstreams}
          selected={selectedUpstreams}
          onToggle={toggleUpstream}
        />
      </div>

      <SwitchRow
        label="Also carry the built-in stash tools"
        consequence="Five extra tools: a small shared key/value scratchpad, not tied to any vault."
        checked={stash}
        onChange={setStash}
      />

      <SwitchRow
        label="Semantic tool routing (experimental)"
        consequence="For very large tool collections: this client sees only find_tool and invoke_tool instead of the full list above, and searches by plain language to find the real tool to run."
        checked={semanticRouting}
        onChange={setSemanticRouting}
      />

      <div className="stack stack--2">
        <span className="field__label">Per-tool visibility</span>
        <p className="t-xs t-muted">
          Uncheck a tool to mount its vault without exposing that one action. A hidden tool
          disappears from this client&rsquo;s tool list entirely — it is not just tucked away.
        </p>
        {tools === null ? (
          <p className="t-xs t-muted">Loading…</p>
        ) : (
          <ToolVisibilityList tools={tools} hidden={hidden} onToggle={toggleTool} />
        )}
      </div>

      {error ? <p className="field__error">{error}</p> : null}

      <div className="row row--wrap">
        <Button variant="primary" onClick={save} disabled={saving}>
          {saving ? "Saving…" : "Save"}
        </Button>
        <Button variant="ghost" onClick={onCancel} disabled={saving}>
          Cancel
        </Button>
      </div>
    </CardBody>
  );
}

function DeleteProfileControl({
  profile,
  onDeleted,
}: {
  profile: GatewayProfile;
  onDeleted: () => void;
}) {
  const toast = useToast();
  const [confirming, setConfirming] = useState(false);
  const isDefault = profile.path === "default";

  if (isDefault) {
    return (
      <span className="t-xs t-subtle" title="Every client that has not chosen a profile lands here — palaia keeps at least one profile around.">
        Cannot delete the default profile
      </span>
    );
  }

  if (!confirming) {
    return (
      <Button variant="risk" size="sm" onClick={() => setConfirming(true)}>
        Delete
      </Button>
    );
  }

  return (
    <div className="stack stack--2" style={{ alignItems: "flex-end" }}>
      <span className="t-xs t-muted" style={{ textAlign: "right" }}>
        Any client connected at this address stops working immediately, and its token becomes
        useless. This cannot be undone.
      </span>
      <div className="row" style={{ gap: 6 }}>
        <Button variant="ghost" size="sm" onClick={() => setConfirming(false)}>
          Never mind
        </Button>
        <Button
          variant="risk"
          size="sm"
          onClick={() =>
            api
              .deleteGatewayProfile(profile.path)
              .then(() => {
                toast.show(`${profile.path} deleted.`);
                onDeleted();
              })
              .catch((err) => toast.show(describeError(err)))
          }
        >
          Yes, delete it
        </Button>
      </div>
    </div>
  );
}

function ProfileCard({
  profile,
  vaults,
  upstreams,
  onChanged,
}: {
  profile: GatewayProfile;
  vaults: VaultSummary[];
  upstreams: GatewayUpstream[];
  onChanged: () => void;
}) {
  const toast = useToast();
  const [editing, setEditing] = useState(false);
  const origin = typeof window !== "undefined" ? window.location.origin : "";
  const url = `${origin}/mcp/${profile.path}`;

  return (
    <Card>
      <CardHead
        title={profile.label ?? profile.path}
        meta={`${profile.tool_count} tool${profile.tool_count === 1 ? "" : "s"}`}
      />
      <CardBody className="stack stack--3">
        <div className="row row--wrap" style={{ gap: 6 }}>
          {profile.managed ? <Badge variant="info">curator — managed elsewhere</Badge> : null}
          {profile.semantic_routing ? <Badge variant="warn">semantic routing</Badge> : null}
          {profile.stash ? <Badge variant="neutral">stash</Badge> : null}
          {profile.vaults.length === 0 ? (
            <span className="t-xs t-muted">No vaults mounted.</span>
          ) : (
            profile.vaults.map((v) => (
              <span className="chip" key={v}>
                {v}
              </span>
            ))
          )}
        </div>
        <div className="snippet snippet--wrap">
          <code>{url}</code>
          <Button
            size="sm"
            onClick={() =>
              navigator.clipboard.writeText(url).then(() => toast.show("Address copied."))
            }
          >
            <CopyIcon className="icon--sm" />
            Copy
          </Button>
        </div>

        {profile.managed ? (
          <p className="t-xs t-muted">
            The curator&rsquo;s profile is edited through <code>curator:</code> settings, not
            here — see Settings.
          </p>
        ) : editing ? (
          <ProfileEditForm
            profile={profile}
            vaults={vaults}
            upstreams={upstreams}
            onSaved={() => {
              setEditing(false);
              onChanged();
            }}
            onCancel={() => setEditing(false)}
          />
        ) : null}
      </CardBody>
      {profile.managed ? null : (
        <CardFoot>
          <div className="row" style={{ justifyContent: "space-between", width: "100%" }}>
            {editing ? (
              <span className="t-xs t-subtle">Editing above.</span>
            ) : (
              <Button size="sm" onClick={() => setEditing(true)}>
                Edit
              </Button>
            )}
            <DeleteProfileControl profile={profile} onDeleted={onChanged} />
          </div>
        </CardFoot>
      )}
    </Card>
  );
}

function CreateProfileCard({
  vaults,
  upstreams,
  existingPaths,
  onCreated,
}: {
  vaults: VaultSummary[];
  upstreams: GatewayUpstream[];
  existingPaths: Set<string>;
  onCreated: () => void;
}) {
  const toast = useToast();
  const [open, setOpen] = useState(false);
  const [path, setPath] = useState("");
  const [label, setLabel] = useState("");
  const [selectedVaults, setSelectedVaults] = useState<Set<string>>(new Set());
  const [selectedUpstreams, setSelectedUpstreams] = useState<Set<string>>(new Set());
  const [stash, setStash] = useState(false);
  const [creating, setCreating] = useState(false);
  const [error, setError] = useState<string | null>(null);

  if (!open) {
    return (
      <Button variant="primary" onClick={() => setOpen(true)}>
        New tool profile
      </Button>
    );
  }

  const cleanPath = sanitizeProfilePath(path);
  const pathTaken = existingPaths.has(cleanPath);

  function toggleVault(key: string, on: boolean) {
    setSelectedVaults((prev) => {
      const next = new Set(prev);
      if (on) next.add(key);
      else next.delete(key);
      return next;
    });
  }

  function toggleUpstream(key: string, on: boolean) {
    setSelectedUpstreams((prev) => {
      const next = new Set(prev);
      if (on) next.add(key);
      else next.delete(key);
      return next;
    });
  }

  async function create() {
    if (!cleanPath || pathTaken) return;
    setCreating(true);
    setError(null);
    try {
      await api.createGatewayProfile({
        path: cleanPath,
        label: label.trim() || null,
        vaults: [...selectedVaults],
        stash,
        upstreams: [...selectedUpstreams],
      });
      toast.show(`${cleanPath} created.`);
      setOpen(false);
      setPath("");
      setLabel("");
      setSelectedVaults(new Set());
      setSelectedUpstreams(new Set());
      setStash(false);
      onCreated();
    } catch (err) {
      setError(describeError(err));
    } finally {
      setCreating(false);
    }
  }

  return (
    <Card>
      <CardHead title="new tool profile" />
      <CardBody className="stack stack--3">
        <LabeledInput
          label="Address segment"
          hint={`Becomes /mcp/${cleanPath || "…"} — cannot be changed later; create a new profile instead.`}
          value={path}
          onChange={(event) => setPath(event.target.value)}
          invalid={pathTaken}
        />
        {pathTaken ? <p className="field__error">A profile at this address already exists.</p> : null}
        <LabeledInput
          label="Display name"
          placeholder={cleanPath}
          value={label}
          onChange={(event) => setLabel(event.target.value)}
        />
        <div className="stack stack--2">
          <span className="field__label">Vaults</span>
          {vaults.map((vault) => (
            <label key={vault.key} className="row" style={{ gap: 8 }}>
              <input
                type="checkbox"
                checked={selectedVaults.has(vault.key)}
                onChange={(event) => toggleVault(vault.key, event.target.checked)}
              />
              <span className="t-sm">{vault.key}</span>
            </label>
          ))}
        </div>
        <div className="stack stack--2">
          <span className="field__label">Connected tools</span>
          <ConnectedToolsList
            upstreams={upstreams}
            selected={selectedUpstreams}
            onToggle={toggleUpstream}
          />
        </div>
        <SwitchRow
          label="Also carry the built-in stash tools"
          checked={stash}
          onChange={setStash}
        />
        {error ? <p className="field__error">{error}</p> : null}
        <div className="row row--wrap">
          <Button
            variant="primary"
            onClick={create}
            disabled={creating || !cleanPath || pathTaken}
          >
            {creating ? "Creating…" : "Create"}
          </Button>
          <Button variant="ghost" onClick={() => setOpen(false)} disabled={creating}>
            Cancel
          </Button>
        </div>
      </CardBody>
    </Card>
  );
}

function VaultRenameRow({ vault, onSaved }: { vault: GatewayVaultIdentity; onSaved: () => void }) {
  const toast = useToast();
  const [draft, setDraft] = useState<Record<string, string>>(vault.tool_renames);
  const [saving, setSaving] = useState(false);
  const [warning, setWarning] = useState<string | null>(null);

  function setValue(action: string, value: string) {
    setDraft((prev) => {
      const next = { ...prev };
      if (value.trim()) next[action] = value.trim();
      else delete next[action];
      return next;
    });
  }

  async function save() {
    setSaving(true);
    setWarning(null);
    try {
      const result = await api.updateGatewayVault(vault.key, { tool_renames: draft });
      if (result.sanitized.length > 0) {
        setWarning(
          result.sanitized
            .map((s) => `"${s.requested}" was not a valid tool name — saved as "${s.applied}".`)
            .join(" "),
        );
      }
      toast.show(`${vault.key} tools renamed.`);
      onSaved();
    } catch {
      toast.show("Could not save the rename.");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="card" style={{ padding: 0 }}>
      <div className="card__body stack stack--3">
        <div className="row" style={{ justifyContent: "space-between" }}>
          <span className="t-sm">{vault.name}</span>
          <span className="t-xs t-subtle">its tools start with {vault.namespace}_</span>
        </div>
        <div className="banner banner--warn">
          <WarningIcon className="icon icon--sm" />
          <p className="t-xs t-muted">
            Renaming a tool a client already approved may make it re-prompt for approval the
            next time it is used.
          </p>
        </div>
        <div className="stack stack--2">
          {RENAMEABLE_ACTIONS.map((action) => {
            const value = draft[action] ?? "";
            const preview = value ? previewSanitize(value) : action;
            return (
              <div key={action} className="row row--wrap" style={{ gap: 8, alignItems: "baseline" }}>
                <span className="t-xs t-mono" style={{ minWidth: 110 }}>
                  {action}
                </span>
                <input
                  className="input"
                  style={{ maxWidth: 180 }}
                  placeholder={action}
                  value={value}
                  onChange={(event) => setValue(action, event.target.value)}
                />
                <span className="t-xs t-subtle">
                  → {vault.namespace}_{preview}
                </span>
              </div>
            );
          })}
        </div>
        {warning ? (
          <div className="banner banner--warn">
            <InfoIcon className="icon icon--sm" />
            <p className="t-xs t-muted">{warning}</p>
          </div>
        ) : null}
        <div className="row">
          <Button size="sm" variant="primary" onClick={save} disabled={saving}>
            {saving ? "Saving…" : "Save renames"}
          </Button>
        </div>
      </div>
    </div>
  );
}

export function ToolProfiles() {
  const [profiles, setProfiles] = useState<GatewayProfile[] | null>(null);
  const [vaultIdentities, setVaultIdentities] = useState<GatewayVaultIdentity[]>([]);
  const [vaultSummaries, setVaultSummaries] = useState<VaultSummary[]>([]);
  const [upstreams, setUpstreams] = useState<GatewayUpstream[]>([]);
  const [available, setAvailable] = useState(true);

  function refresh() {
    api
      .listGatewayProfiles()
      .then((list) => {
        setProfiles(list);
        setAvailable(true);
      })
      .catch((err) => {
        if (err instanceof ApiError && err.status === 404) setAvailable(false);
      });
    api.listGatewayVaults().then(setVaultIdentities).catch(() => setVaultIdentities([]));
    api.listVaults().then(setVaultSummaries).catch(() => setVaultSummaries([]));
    api.listGatewayUpstreams().then(setUpstreams).catch(() => setUpstreams([]));
  }

  useEffect(refresh, []);

  if (!available) {
    return (
      <section className="stack stack--4">
        <Card>
          <CardBody>
            <p className="t-sm t-muted">
              This hub has no gateway attached, so there is nothing to edit here yet.
            </p>
          </CardBody>
        </Card>
      </section>
    );
  }

  return (
    <section className="stack stack--4">
      <div className="row" style={{ justifyContent: "space-between" }}>
        <p className="t-sm t-muted" style={{ maxWidth: 560 }}>
          Each connected client gets its own tool profile — its own address, its own set of
          vaults, and (optionally) its own hidden tools. A hundred tools in one conversation
          ruins an agent; this is where you decide who sees what.
        </p>
        <CreateProfileCard
          vaults={vaultSummaries}
          upstreams={upstreams}
          existingPaths={new Set((profiles ?? []).map((p) => p.path))}
          onCreated={refresh}
        />
      </div>

      {profiles && profiles.length === 0 ? (
        <EmptyState mark={<ToolsIcon className="icon--lg" />} title="No tool profiles yet.">
          Every vault mounts on the default profile until you create your own — add one above
          once you have a client that should see less than everything.
        </EmptyState>
      ) : (
        <div className="stack stack--3">
          {(profiles ?? []).map((profile) => (
            <ProfileCard
              key={profile.path}
              profile={profile}
              vaults={vaultSummaries}
              upstreams={upstreams}
              onChanged={refresh}
            />
          ))}
        </div>
      )}

      {vaultIdentities.length > 0 ? (
        <div className="stack stack--3">
          <span className="field__label">Vault tool names</span>
          <p className="t-xs t-muted">
            Renaming here changes the tool everywhere it is mounted — across every profile that
            includes this vault, live.
          </p>
          {vaultIdentities.map((vault) => (
            <VaultRenameRow key={vault.key} vault={vault} onSaved={refresh} />
          ))}
        </div>
      ) : null}
    </section>
  );
}
