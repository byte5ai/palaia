/**
 * Settings › Advanced (SPEC-305, issues 570 and 571): tool sets and tool
 * names — the settings most setups never need.
 *
 * A tool set (a "tool profile" in config.yaml) is a named address that
 * limits which memories and add-ons an AI app sees: "Codex gets the work
 * memory only; Claude Desktop gets everything". Everything here reads and
 * writes SPEC-301's REST surface (`/api/gateway/profiles`,
 * `/api/gateway/vaults`) — no second write path of its own.
 */
import { useEffect, useState } from "react";

import {
  Button,
  Card,
  CardHeader,
  ConfirmDialog,
  Dialog,
  Disclosure,
  ErrorState,
  InlineEmpty,
  LabeledInput,
  ListRow,
  LoadingState,
  PageHeader,
  StatusPill,
  Switch,
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
import { describeApiError } from "../lib/errors";
import { count } from "../lib/format";
import { CopyIcon } from "../shell/icons";
import "./settings.css";

// The eight base actions every memory's tool family carries, and the only
// ones a rename applies to (`palaia_hub.gateway.vault_protocol.
// MEMORY_TOOL_ACTIONS`) — a closed, versioned set the server treats as stable.
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

const STASH_COPY = {
  title: "Include scratchpad tools",
  description: "5 tools for short shared values that don't belong in a memory.",
};

/** Issue 463: the flag, with what it does and does not grant. */
const TELEGRAM_COPY = {
  title: "Include Telegram tools",
  description:
    "Lets AI apps send, reply to, edit and delete Telegram messages — only in the bots and chats Settings › Telegram allows this tool set.",
};

const ROUTING_COPY = {
  title: "Search for tools instead of listing them (experimental)",
  description:
    "For apps with many add-ons: the app sees 2 tools and finds the right one by description.",
};

/** Mirrors `palaia_hub.gateway.naming.sanitize_tool_name` for an inline
 * preview only — the server's own answer after a save is authoritative. */
function previewSanitize(raw: string): string {
  let value = raw.replace(/[^a-zA-Z0-9_]+/g, "_").replace(/^_+|_+$/g, "");
  if (/^[0-9]/.test(value)) value = `t_${value}`;
  return value || "tool";
}

function sanitizeProfilePath(raw: string): string {
  const lowered = raw.toLowerCase().replace(/[^a-z0-9-_]+/g, "-");
  return lowered.replace(/^-+|-+$/g, "") || "";
}

function toggled(set: Set<string>, key: string, on: boolean): Set<string> {
  const next = new Set(set);
  if (on) next.add(key);
  else next.delete(key);
  return next;
}

/** A switch with its title and one line, inside a form. */
function SwitchSetting({
  id,
  title,
  description,
  checked,
  onChange,
}: {
  id: string;
  title: string;
  description: string;
  checked: boolean;
  onChange: (on: boolean) => void;
}) {
  return (
    <ListRow
      setting
      labelId={id}
      title={title}
      description={description}
      trailing={<Switch checked={checked} onChange={onChange} labelledBy={id} />}
    />
  );
}

function MemoryChoices({
  vaults,
  selected,
  onToggle,
}: {
  vaults: VaultSummary[];
  selected: Set<string>;
  onToggle: (key: string, on: boolean) => void;
}) {
  if (vaults.length === 0) return <p className="t-sm t-muted">No memories yet.</p>;
  return (
    <div className="stack stack--2">
      {vaults.map((vault) => (
        <label key={vault.key} className="checkrow">
          <input
            type="checkbox"
            checked={selected.has(vault.key)}
            onChange={(event) => onToggle(vault.key, event.target.checked)}
          />
          <span className="t-sm">{vault.key}</span>
          {vault.purpose ? <span className="t-sm t-muted">— {vault.purpose}</span> : null}
        </label>
      ))}
    </div>
  );
}

/** Add-ons (installed from Add-ons, or added by hand) a tool set can use. */
function AddonChoices({
  upstreams,
  selected,
  onToggle,
}: {
  upstreams: GatewayUpstream[];
  selected: Set<string>;
  onToggle: (key: string, on: boolean) => void;
}) {
  if (upstreams.length === 0) return <p className="t-sm t-muted">No add-ons installed yet.</p>;
  return (
    <div className="stack stack--2">
      {upstreams.map((upstream) => (
        <label key={upstream.key} className="checkrow">
          <input
            type="checkbox"
            checked={selected.has(upstream.key)}
            onChange={(event) => onToggle(upstream.key, event.target.checked)}
          />
          <span className="t-sm">{upstream.display_name}</span>
          <StatusPill tone={upstream.up ? "ok" : "warn"}>
            {upstream.up ? "Working" : "Not responding"}
          </StatusPill>
        </label>
      ))}
    </div>
  );
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
  if (tools.length === 0) return <p className="t-sm t-muted">No tools yet. Add a memory first.</p>;
  return (
    <div className="stack stack--2">
      {tools.map((tool) => (
        <label key={tool.name} className="checkrow">
          <input
            type="checkbox"
            checked={!hidden.has(tool.name)}
            onChange={(event) => onToggle(tool.name, event.target.checked)}
          />
          <span className="stack stack--1">
            <span className="t-mono">{tool.name}</span>
            {tool.description ? (
              <span className="t-sm t-muted">{tool.description.split("\n")[0]}</span>
            ) : null}
          </span>
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
  onDeleted,
}: {
  profile: GatewayProfile;
  vaults: VaultSummary[];
  upstreams: GatewayUpstream[];
  onSaved: () => void;
  onCancel: () => void;
  onDeleted: () => void;
}) {
  const toast = useToast();
  const [label, setLabel] = useState(profile.label ?? "");
  const [selectedVaults, setSelectedVaults] = useState(new Set(profile.vaults));
  const [selectedUpstreams, setSelectedUpstreams] = useState(new Set(profile.upstreams));
  const [stash, setStash] = useState(profile.stash);
  const [telegram, setTelegram] = useState(profile.telegram);
  const [semanticRouting, setSemanticRouting] = useState(profile.semantic_routing);
  const [tools, setTools] = useState<GatewayTool[] | null>(null);
  const [hidden, setHidden] = useState(new Set(profile.hidden_tools));
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const origin = typeof window !== "undefined" ? window.location.origin : "";
  const address = `${origin}/mcp/${profile.path}`;

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

  async function save() {
    setSaving(true);
    setError(null);
    try {
      await api.updateGatewayProfile(profile.path, {
        label: label.trim() || null,
        vaults: [...selectedVaults],
        stash,
        telegram,
        hidden_tools: [...hidden],
        semantic_routing: semanticRouting,
        upstreams: [...selectedUpstreams],
      });
      toast.show(`Tool set ${profile.label ?? profile.path} saved.`);
      onSaved();
    } catch (err) {
      setError(describeApiError(err));
    } finally {
      setSaving(false);
    }
  }

  async function remove() {
    setConfirmDelete(false);
    try {
      await api.deleteGatewayProfile(profile.path);
      toast.show(`Tool set ${profile.path} deleted.`);
      onDeleted();
    } catch (err) {
      setError(describeApiError(err));
    }
  }

  return (
    <div className="settings-form" data-testid={`tool-set-form-${profile.path}`}>
      <div className="stack stack--2">
        <span className="field__label">Address</span>
        <div className="snippet snippet--wrap">
          <code>{address}</code>
          <Button
            size="sm"
            onClick={() =>
              navigator.clipboard.writeText(address).then(
                () => toast.show("Address copied."),
                () => toast.show("Couldn't copy. Select the address and copy it yourself."),
              )
            }
          >
            <CopyIcon className="icon" />
            Copy
          </Button>
        </div>
        <span className="field__hint">AI apps that use this tool set connect to this address.</span>
      </div>
      <LabeledInput
        label="Display name"
        optional
        placeholder={profile.path}
        hint="Only shown here; the address stays the same."
        value={label}
        onChange={(event) => setLabel(event.target.value)}
      />
      <div className="stack stack--2">
        <span className="field__label">Memories this tool set can see</span>
        <MemoryChoices
          vaults={vaults}
          selected={selectedVaults}
          onToggle={(key, on) => setSelectedVaults((prev) => toggled(prev, key, on))}
        />
      </div>
      <div className="stack stack--2">
        <span className="field__label">Add-ons this tool set can use</span>
        <AddonChoices
          upstreams={upstreams}
          selected={selectedUpstreams}
          onToggle={(key, on) => setSelectedUpstreams((prev) => toggled(prev, key, on))}
        />
      </div>
      <div className="card card--flat">
        <SwitchSetting id={`stash-${profile.path}`} {...STASH_COPY} checked={stash} onChange={setStash} />
        <SwitchSetting
          id={`telegram-${profile.path}`}
          {...TELEGRAM_COPY}
          checked={telegram}
          onChange={setTelegram}
        />
        <SwitchSetting
          id={`routing-${profile.path}`}
          {...ROUTING_COPY}
          checked={semanticRouting}
          onChange={setSemanticRouting}
        />
      </div>
      <Disclosure summary="Hide single tools">
        <p>Unchecked tools disappear from the AI app's list entirely.</p>
        {tools === null ? (
          <LoadingState label="Loading tools…" lines={2} />
        ) : (
          <ToolVisibilityList
            tools={tools}
            hidden={hidden}
            onToggle={(name, visible) => setHidden((prev) => toggled(prev, name, !visible))}
          />
        )}
      </Disclosure>
      {error ? <p className="field__error">{error}</p> : null}
      <div className="settings-form__actions">
        <Button variant="primary" onClick={() => void save()} loading={saving}>
          {saving ? "Saving…" : "Save"}
        </Button>
        <Button onClick={onCancel} disabled={saving}>
          Cancel
        </Button>
        {/* The default set catches every AI app that chose none; palaia keeps it. */}
        {profile.path === "default" ? null : (
          <Button variant="destructive" onClick={() => setConfirmDelete(true)} disabled={saving}>
            Delete tool set
          </Button>
        )}
      </div>
      <ConfirmDialog
        open={confirmDelete}
        onCancel={() => setConfirmDelete(false)}
        onConfirm={() => void remove()}
        title={`Delete the tool set ${profile.label ?? profile.path}?`}
        confirmLabel="Delete tool set"
        destructive
      >
        <p>
          AI apps connected at this address stop working right away, and their access keys stop
          working with it. This can't be undone.
        </p>
      </ConfirmDialog>
    </div>
  );
}

function ProfileRow({
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
  const [editing, setEditing] = useState(false);
  const traits = [
    profile.vaults.length === 0
      ? "No memories"
      : `Memories: ${profile.vaults.join(", ")}`,
    profile.upstreams.length > 0 ? count(profile.upstreams.length, "add-on", "add-ons") : null,
  ].filter(Boolean);

  return (
    <li data-testid={`tool-set-${profile.path}`}>
      <ListRow
        title={profile.label ?? profile.path}
        description={traits.join(" · ")}
        meta={count(profile.tool_count, "tool", "tools")}
        trailing={
          <>
            {profile.managed ? <StatusPill tone="info">Managed by the curator</StatusPill> : null}
            {profile.semantic_routing ? <StatusPill tone="warn">Tool search</StatusPill> : null}
            {profile.stash ? <StatusPill tone="neutral">Scratchpad</StatusPill> : null}
            {profile.telegram ? <StatusPill tone="neutral">Telegram</StatusPill> : null}
            {profile.managed || editing ? null : (
              <Button size="sm" onClick={() => setEditing(true)}>
                Edit
              </Button>
            )}
          </>
        }
      />
      {profile.managed ? (
        <p className="setting-note t-sm t-muted">
          The curator's tool set follows the curator's settings in config.yaml.
        </p>
      ) : null}
      {editing ? (
        <ProfileEditForm
          profile={profile}
          vaults={vaults}
          upstreams={upstreams}
          onSaved={() => {
            setEditing(false);
            onChanged();
          }}
          onCancel={() => setEditing(false)}
          onDeleted={() => {
            setEditing(false);
            onChanged();
          }}
        />
      ) : null}
    </li>
  );
}

function CreateProfileDialog({
  open,
  onClose,
  vaults,
  upstreams,
  existingPaths,
  onCreated,
}: {
  open: boolean;
  onClose: () => void;
  vaults: VaultSummary[];
  upstreams: GatewayUpstream[];
  existingPaths: Set<string>;
  onCreated: () => void;
}) {
  const toast = useToast();
  const [path, setPath] = useState("");
  const [label, setLabel] = useState("");
  const [selectedVaults, setSelectedVaults] = useState<Set<string>>(new Set());
  const [selectedUpstreams, setSelectedUpstreams] = useState<Set<string>>(new Set());
  const [stash, setStash] = useState(false);
  const [telegram, setTelegram] = useState(false);
  const [creating, setCreating] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const cleanPath = sanitizeProfilePath(path);
  const pathTaken = existingPaths.has(cleanPath);

  function reset() {
    setPath("");
    setLabel("");
    setSelectedVaults(new Set());
    setSelectedUpstreams(new Set());
    setStash(false);
    setTelegram(false);
    setError(null);
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
        telegram,
        upstreams: [...selectedUpstreams],
      });
      toast.show(`Tool set ${cleanPath} created.`);
      reset();
      onClose();
      onCreated();
    } catch (err) {
      setError(describeApiError(err));
    } finally {
      setCreating(false);
    }
  }

  return (
    <Dialog
      open={open}
      onClose={onClose}
      size="form"
      title="New tool set"
      description="AI apps that connect at its address see only what you choose here."
      footer={
        <>
          <Button onClick={onClose} disabled={creating}>
            Cancel
          </Button>
          <Button
            variant="primary"
            onClick={() => void create()}
            disabled={!cleanPath || pathTaken}
            loading={creating}
          >
            {creating ? "Creating…" : "Create"}
          </Button>
        </>
      }
    >
      <LabeledInput
        label="Address name"
        placeholder="codex"
        hint={
          pathTaken
            ? undefined
            : `Used in the app's address (…/mcp/${cleanPath || "name"}). Can't be changed later.`
        }
        error={pathTaken ? "A tool set with this address already exists." : undefined}
        value={path}
        onChange={(event) => setPath(event.target.value)}
        invalid={pathTaken}
      />
      <LabeledInput
        label="Display name"
        optional
        placeholder={cleanPath || "Codex"}
        value={label}
        onChange={(event) => setLabel(event.target.value)}
      />
      <div className="stack stack--2">
        <span className="field__label">Memories</span>
        <MemoryChoices
          vaults={vaults}
          selected={selectedVaults}
          onToggle={(key, on) => setSelectedVaults((prev) => toggled(prev, key, on))}
        />
      </div>
      <div className="stack stack--2">
        <span className="field__label">Add-ons</span>
        <AddonChoices
          upstreams={upstreams}
          selected={selectedUpstreams}
          onToggle={(key, on) => setSelectedUpstreams((prev) => toggled(prev, key, on))}
        />
      </div>
      <div className="card card--flat">
        <SwitchSetting id="new-stash" {...STASH_COPY} checked={stash} onChange={setStash} />
        <SwitchSetting id="new-telegram" {...TELEGRAM_COPY} checked={telegram} onChange={setTelegram} />
      </div>
      {error ? <p className="field__error">{error}</p> : null}
    </Dialog>
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
      toast.show(`Tool names for ${vault.name} saved.`);
      onSaved();
    } catch (err) {
      toast.show(`Couldn't save the tool names: ${describeApiError(err)}`);
    } finally {
      setSaving(false);
    }
  }

  return (
    <Disclosure summary={vault.name}>
      <div className="stack stack--2">
        {RENAMEABLE_ACTIONS.map((action) => {
          const value = draft[action] ?? "";
          const preview = value ? previewSanitize(value) : action;
          return (
            <div key={action} className="row row--wrap">
              <input
                className="input input--mono"
                style={{ maxWidth: 220 }}
                aria-label={`New name for ${action}`}
                placeholder={action}
                value={value}
                onChange={(event) => setValue(action, event.target.value)}
              />
              <span className="t-mono t-muted">
                → {vault.namespace}_{preview}
              </span>
            </div>
          );
        })}
      </div>
      {warning ? <p className="t-sm">{warning}</p> : null}
      <div>
        <Button size="sm" onClick={() => void save()} loading={saving}>
          {saving ? "Saving…" : "Save names"}
        </Button>
      </div>
    </Disclosure>
  );
}

const HEADER = (
  <PageHeader
    title="Advanced"
    description="Tool sets and tool names. Most setups never need these."
    back={{ to: "/settings", label: "Settings" }}
  />
);

export function ToolProfiles() {
  const [profiles, setProfiles] = useState<GatewayProfile[] | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [vaultIdentities, setVaultIdentities] = useState<GatewayVaultIdentity[]>([]);
  const [vaultSummaries, setVaultSummaries] = useState<VaultSummary[]>([]);
  const [upstreams, setUpstreams] = useState<GatewayUpstream[]>([]);
  const [available, setAvailable] = useState(true);
  const [creating, setCreating] = useState(false);

  function refresh() {
    api
      .listGatewayProfiles()
      .then((list) => {
        setProfiles(list);
        setAvailable(true);
        setLoadError(null);
      })
      .catch((err) => {
        if (err instanceof ApiError && err.status === 404) setAvailable(false);
        else setLoadError(describeApiError(err));
      });
    api.listGatewayVaults().then(setVaultIdentities).catch(() => setVaultIdentities([]));
    api.listVaults().then(setVaultSummaries).catch(() => setVaultSummaries([]));
    api.listGatewayUpstreams().then(setUpstreams).catch(() => setUpstreams([]));
  }

  useEffect(refresh, []);

  if (!available) {
    return (
      <div className="stack narrow">
        {HEADER}
        <Card>
          <CardHeader title="Tool sets" />
          <InlineEmpty>
            This palaia doesn't serve tool sets (it runs without its AI connection), so there is
            nothing to change here.
          </InlineEmpty>
        </Card>
      </div>
    );
  }

  const nonDefault = (profiles ?? []).filter((profile) => profile.path !== "default");

  return (
    <div className="stack narrow">
      {HEADER}
      <Card>
        <CardHeader
          title="Tool sets"
          description="A tool set is a named address that limits which memories and tools an AI app sees."
          actions={
            <Button onClick={() => setCreating(true)} disabled={profiles === null}>
              New tool set
            </Button>
          }
        />
        {loadError && profiles === null ? (
          <div className="settings-body">
            <ErrorState title="Couldn't load the tool sets" details={loadError} onRetry={refresh} />
          </div>
        ) : profiles === null ? (
          <div className="settings-body">
            <LoadingState label="Loading tool sets…" lines={2} />
          </div>
        ) : (
          <>
            {profiles.length > 0 ? (
              <ul className="settings-rows">
                {profiles.map((profile) => (
                  <ProfileRow
                    key={profile.path}
                    profile={profile}
                    vaults={vaultSummaries}
                    upstreams={upstreams}
                    onChanged={refresh}
                  />
                ))}
              </ul>
            ) : null}
            {nonDefault.length === 0 ? (
              <InlineEmpty>
                Only the default tool set exists. It includes every memory, and most setups
                only need it.
              </InlineEmpty>
            ) : null}
          </>
        )}
      </Card>

      {vaultIdentities.length > 0 ? (
        <Card data-testid="tool-names">
          <CardHeader
            title="Tool names"
            description="Rename what AI apps see. Apps may ask you to approve renamed tools again."
          />
          <div className="settings-body">
            {vaultIdentities.map((vault) => (
              <VaultRenameRow key={vault.key} vault={vault} onSaved={refresh} />
            ))}
          </div>
        </Card>
      ) : null}

      <CreateProfileDialog
        open={creating}
        onClose={() => setCreating(false)}
        vaults={vaultSummaries}
        upstreams={upstreams}
        existingPaths={new Set((profiles ?? []).map((p) => p.path))}
        onCreated={refresh}
      />
    </div>
  );
}
