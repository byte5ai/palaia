/**
 * Connecting one AI app that talks to this palaia directly (SPEC-110): choose
 * what it may use, create its access key, paste one thing into the app, and
 * watch for its first request — no reload. Used by AI apps › Apps and by
 * the first-run setup.
 *
 * If a live access key for this app already exists (matched by name), the
 * panel finds it on mount and starts at "paste": no second key is created
 * because the page was opened again. The key's plaintext lives only in this
 * component's state, for as long as it is mounted; a panel that only *found*
 * a key cannot know it, so its snippets show the placeholder and the copy
 * says how to get a new key (issue 318).
 *
 * What the app may use (issue 270): every memory of the chosen tool set, Read
 * and Save, all checked. Untouched, no `scopes` are sent and the server's own
 * default decides — the same request as before the picker existed. Unchecking
 * a box sends an explicit, narrower list; unchecking everything is blocked,
 * because an empty list is the server's "use the default" and would grant
 * more, not less. The tool set itself is under Advanced and only offers tool
 * sets that exist — a free-text name used to create keys for a tool set
 * nobody had made (report §3.4).
 *
 * Revoke access and Replace access key (report §5.5) use the existing token
 * routes: revoking takes back every live key of this app; replacing creates
 * a new key with the same tool set and permissions, then revokes the old one.
 */
import { useEffect, useMemo, useState } from "react";

import "../routes/apps.css";

import type { CreatedToken, GatewayProfile, TokenInfo } from "../lib/api/client";
import { api } from "../lib/api/client";
import type { GuidedClient } from "../lib/clients";
import { describeApiError } from "../lib/errors";
import { exactTime, timeAgo } from "../lib/format";
import { nextPollDelay, POLL_INITIAL_MS } from "../lib/polling";
import { CheckIcon, CopyIcon } from "../shell/icons";
import { Button } from "./Button";
import { Card, CardFoot, CardHeader } from "./Card";
import { ConfirmDialog } from "./Dialog";
import { Disclosure } from "./Disclosure";
import { Waiting } from "./Skeleton";
import { StatusPill } from "./StatusPill";
import { Tabs } from "./Tabs";
import { useToast } from "./Toast";

type SnippetTab = "command" | "prompt" | "file";

/**
 * Choose a tool set — only ones that exist. Shown under "Advanced"
 * wherever an app's address is built (the connect panel, the Claude Desktop
 * download, the address for a cloud app).
 */
export function ToolSetPicker({
  id,
  profiles,
  value,
  onChange,
  appName,
}: {
  id: string;
  profiles: GatewayProfile[];
  value: string;
  onChange: (path: string) => void;
  appName: string;
}) {
  return (
    <div className="field">
      <label className="field__label" htmlFor={id}>
        Tool set
      </label>
      <select
        id={id}
        className="input"
        style={{ maxWidth: 320 }}
        value={value}
        onChange={(event) => onChange(event.target.value)}
      >
        {profiles.map((p) => (
          <option key={p.path} value={p.path}>
            {p.label ?? p.path} · {p.tool_count} tools
          </option>
        ))}
      </select>
      <span className="field__hint">
        Tool sets limit which memories and tools {appName} sees. Fewer tools help an AI pick the
        right one. Change them under Settings › Advanced.
      </span>
    </div>
  );
}

function StepNumber({ n, done }: { n: number; done: boolean }) {
  return (
    <span className={["numstep__num", done ? "numstep__num--done" : "numstep__num--on"].join(" ")}>
      {done ? <CheckIcon className="icon--sm" /> : n}
    </span>
  );
}

export function ConnectPanel({
  client,
  defaultProfile = "default",
  onTokenIssued,
  onTokenRevoked,
}: {
  client: GuidedClient;
  defaultProfile?: string;
  /** Called once an access key for this app is known — freshly created, or
   * found already existing on mount — so a parent showing its own list of
   * apps can update its status without a separate fetch. */
  onTokenIssued?: (info: TokenInfo) => void;
  /** Called with the ids of the keys this panel revoked (Revoke access, or
   * the old key after Replace access key). */
  onTokenRevoked?: (ids: string[]) => void;
}) {
  const toast = useToast();
  const [profileChoice, setProfileChoice] = useState(defaultProfile);
  const [issuing, setIssuing] = useState(false);
  const [plaintext, setPlaintext] = useState<string | null>(null);
  const [token, setToken] = useState<TokenInfo | null>(null);
  const [tab, setTab] = useState<SnippetTab>("command");
  const [error, setError] = useState<string | null>(null);
  const [profiles, setProfiles] = useState<GatewayProfile[] | null>(null);
  const [confirm, setConfirm] = useState<"revoke" | "replace" | null>(null);
  const [busy, setBusy] = useState(false);
  // Every box a person explicitly *un*checked, as `memory:read` /
  // `memory:write`. Absence means checked — so a memory this panel never
  // rendered a box for never ends up narrower by accident.
  const [unchecked, setUnchecked] = useState<Set<string>>(new Set());

  // Look for a live key for this app on mount, scoped to `client.name`, so a
  // panel opened again starts at "paste" instead of creating a second key.
  useEffect(() => {
    let cancelled = false;
    api
      .listTokens()
      .then((tokens) => {
        if (cancelled) return;
        const mine = tokens.find((t) => t.name === client.name && !t.revoked_at);
        if (mine) {
          setToken(mine);
          onTokenIssued?.(mine);
        }
      })
      .catch(() => {
        // No key store, or a passing failure: start at step 1.
      });
    return () => {
      cancelled = true;
    };
    // Intentionally scoped to `client.name`: re-run when the app changes, not
    // when the parent passes a new `onTokenIssued` closure.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [client.name]);

  // The tool sets and the memories each one includes, for the picker.
  useEffect(() => {
    let cancelled = false;
    api
      .listGatewayProfiles()
      .then((list) => {
        if (!cancelled) setProfiles(list);
      })
      .catch(() => {
        // No gateway attached: no picker; creating a key works as before.
      });
    return () => {
      cancelled = true;
    };
  }, []);

  // A different tool set has different memories: what was unchecked for the
  // previous one must not narrow the next (reset during render, as React's
  // docs recommend for "reset state when a value changes").
  const [previousChoice, setPreviousChoice] = useState(profileChoice);
  if (profileChoice !== previousChoice) {
    setPreviousChoice(profileChoice);
    setUnchecked(new Set());
  }

  // Only a tool set that exists: when the suggested one is not among them,
  // the first one that is.
  const toolSet =
    profiles && profiles.length > 0 && !profiles.some((p) => p.path === profileChoice)
      ? profiles[0]!.path
      : profileChoice;
  const targetProfile = profiles?.find((candidate) => candidate.path === toolSet) ?? null;
  const memories = targetProfile?.vaults ?? [];
  const canPickToolSet = (profiles?.length ?? 0) > 1 && targetProfile !== null;

  function isChecked(memory: string, permission: "read" | "write"): boolean {
    return !unchecked.has(`${memory}:${permission}`);
  }

  function toggle(memory: string, permission: "read" | "write", checked: boolean) {
    setUnchecked((prev) => {
      const next = new Set(prev);
      const id = `${memory}:${permission}`;
      if (checked) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  const pickerTouched = unchecked.size > 0;
  const explicitScopes = pickerTouched
    ? memories.flatMap((key) => {
        const scopes: string[] = [];
        if (isChecked(key, "read")) scopes.push(`vault:${key}:read`);
        if (isChecked(key, "write")) scopes.push(`vault:${key}:write`);
        return scopes;
      })
    : [];
  const wouldGrantNothing = pickerTouched && explicitScopes.length === 0;

  const origin = typeof window !== "undefined" ? window.location.origin : "";
  const profile = token?.profile ?? toolSet;
  const connected = Boolean(token?.last_used_at);
  const snippetToken = plaintext ?? undefined;
  const command = client.command(origin, profile, snippetToken);
  const prompt = client.prompt(origin, profile, snippetToken);
  const configFile = client.configFile?.(origin, profile, snippetToken);
  const configFileHref = useMemo(
    () =>
      configFile
        ? URL.createObjectURL(new Blob([configFile.content], { type: configFile.mimeType }))
        : null,
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [configFile?.content, configFile?.mimeType],
  );
  useEffect(() => {
    return () => {
      if (configFileHref) URL.revokeObjectURL(configFileHref);
    };
  }, [configFileHref]);

  async function createKey() {
    setIssuing(true);
    setError(null);
    try {
      // No `scopes` unless the picker was touched: the server's default
      // ("everything this tool set includes") decides the untouched case.
      const body =
        pickerTouched && explicitScopes.length > 0
          ? { name: client.name, profile: toolSet, scopes: explicitScopes }
          : { name: client.name, profile: toolSet };
      const result: CreatedToken = await api.createToken(body);
      setToken(result.info);
      setPlaintext(result.token);
      onTokenIssued?.(result.info);
    } catch (err) {
      setError(describeApiError(err));
    } finally {
      setIssuing(false);
    }
  }

  /** Every live key of this app except `keep`. */
  async function liveKeysOfThisApp(keep?: string): Promise<string[]> {
    const all = await api.listTokens();
    return all
      .filter((t) => t.name === client.name && !t.revoked_at && t.id !== keep)
      .map((t) => t.id);
  }

  async function revokeAccess() {
    setBusy(true);
    setError(null);
    try {
      const ids = await liveKeysOfThisApp();
      if (token && !ids.includes(token.id)) ids.push(token.id);
      for (const id of ids) await api.revokeToken(id);
      setToken(null);
      setPlaintext(null);
      onTokenRevoked?.(ids);
      toast.show(`${client.name} can no longer use palaia.`);
    } catch (err) {
      setError(describeApiError(err));
    } finally {
      setBusy(false);
      setConfirm(null);
    }
  }

  async function replaceKey() {
    if (!token) return;
    setBusy(true);
    setError(null);
    let result: CreatedToken;
    try {
      result = await api.createToken(
        token.scopes.length > 0
          ? { name: client.name, profile: token.profile, scopes: token.scopes }
          : { name: client.name, profile: token.profile },
      );
    } catch (err) {
      setError(describeApiError(err));
      setBusy(false);
      setConfirm(null);
      return;
    }
    // The new key works from here on, and this answer is the only place its
    // plaintext exists: show it before anything else can fail.
    setToken(result.info);
    setPlaintext(result.token);
    setTab("command");
    onTokenIssued?.(result.info);
    const revoked: string[] = [];
    try {
      const old = await liveKeysOfThisApp(result.info.id);
      for (const id of old) {
        await api.revokeToken(id);
        revoked.push(id);
      }
      toast.show("New access key created. Paste the new command into the app.");
    } catch (err) {
      setError(
        `New access key created, but the old one may still work. ${describeApiError(err)} ` +
          "Replace the access key again to turn it off.",
      );
    } finally {
      if (revoked.length > 0) onTokenRevoked?.(revoked);
      setBusy(false);
      setConfirm(null);
    }
  }

  // Watch for the first request once a key exists (no reload). Backs off
  // 3 s → … → 30 s (issue 384).
  const tokenId = token?.id ?? null;
  const tokenUsedAt = token?.last_used_at ?? null;
  useEffect(() => {
    if (!tokenId || tokenUsedAt) return;
    let cancelled = false;
    let delay = POLL_INITIAL_MS;
    let timer = 0;
    const tick = () => {
      api
        .listTokens()
        .then((tokens) => {
          const mine = tokens.find((t) => t.id === tokenId);
          if (!cancelled && mine?.last_used_at) setToken(mine);
        })
        .catch(() => {
          // a passing failure: the next tick tries again
        })
        .finally(() => {
          if (cancelled) return;
          delay = nextPollDelay(delay);
          timer = window.setTimeout(tick, delay);
        });
    };
    timer = window.setTimeout(tick, delay);
    return () => {
      cancelled = true;
      window.clearTimeout(timer);
    };
  }, [tokenId, tokenUsedAt]);

  function copy(text: string, what: string) {
    navigator.clipboard.writeText(text).then(
      () => toast.show(`${what} copied.`),
      () => toast.show("Couldn't copy. Select the text and copy it yourself."),
    );
  }

  const status = connected
    ? { tone: "ok" as const, label: "Connected" }
    : token
      ? { tone: "info" as const, label: "Waiting for first use" }
      : { tone: "neutral" as const, label: "Ready to connect" };
  const description =
    connected && token?.last_used_at
      ? `Connected — last request ${timeAgo(token.last_used_at)}.`
      : token
        ? "Access key created. Paste it into the app, then test the connection."
        : `Create an access key for ${client.name}, then paste one command.`;
  const tabs: { id: SnippetTab; label: string }[] = [
    { id: "command", label: "Command" },
    { id: "prompt", label: "Prompt" },
    ...(configFile ? [{ id: "file" as const, label: "Config file" }] : []),
  ];
  const idPrefix = `connect-${client.id}`;

  return (
    <Card>
      <CardHeader
        title={`Connect ${client.name}`}
        description={description}
        actions={<StatusPill tone={status.tone}>{status.label}</StatusPill>}
      />

      {!token ? (
        <div className="connect-step">
          <StepNumber n={1} done={false} />
          <div className="connect-step__body">
            <p className="connect-step__title">Choose what {client.name} can use</p>
            {memories.length > 0 ? (
              <>
                <div className="permgrid" role="group" aria-label={`What ${client.name} can use`}>
                  <span className="permgrid__head">Memory</span>
                  <span className="permgrid__head">Read</span>
                  <span className="permgrid__head">Save</span>
                  {memories.map((memory) => (
                    <PermissionRow
                      key={memory}
                      memory={memory}
                      read={isChecked(memory, "read")}
                      save={isChecked(memory, "write")}
                      onToggle={toggle}
                    />
                  ))}
                </div>
                <p className="field__hint">Uncheck Save for read-only access.</p>
                {wouldGrantNothing ? (
                  <p className="field__error" role="alert">
                    Select at least one memory.
                  </p>
                ) : null}
              </>
            ) : profiles !== null && targetProfile ? (
              <p className="t-sm t-muted">
                This tool set has no memory yet. The key works as soon as you create one.
              </p>
            ) : (
              <p className="t-sm t-muted">Every memory, read and save.</p>
            )}
            {canPickToolSet && profiles ? (
              <Disclosure summary="Advanced">
                <ToolSetPicker
                  id={`${idPrefix}-toolset`}
                  profiles={profiles}
                  value={toolSet}
                  onChange={setProfileChoice}
                  appName={client.name}
                />
              </Disclosure>
            ) : null}
            <div className="row row--wrap">
              <Button
                variant="primary"
                onClick={createKey}
                loading={issuing}
                disabled={wouldGrantNothing}
              >
                {issuing ? "Creating access key…" : "Create access key"}
              </Button>
            </div>
            {error ? (
              <p className="field__error" role="alert">
                {error}
              </p>
            ) : null}
          </div>
        </div>
      ) : (
        <>
          <div className="connect-step">
            <StepNumber n={2} done={connected} />
            <div className="connect-step__body">
              <p className="connect-step__title">Paste into {client.name}</p>
              <Tabs
                label={`How to connect ${client.name}`}
                items={tabs}
                value={tab}
                onChange={setTab}
                idPrefix={idPrefix}
              />
              <div
                role="tabpanel"
                id={`${idPrefix}-${tab}-panel`}
                aria-labelledby={`${idPrefix}-${tab}`}
                className="stack stack--3"
              >
                {tab === "command" ? (
                  <div className="snippet snippet--wrap">
                    <code>{command}</code>
                    <Button size="sm" onClick={() => copy(command, "Command")}>
                      <CopyIcon className="icon--sm" />
                      Copy
                    </Button>
                  </div>
                ) : tab === "file" && configFile ? (
                  <>
                    <div className="snippet snippet--block">
                      <code>{configFile.content}</code>
                    </div>
                    {configFileHref ? (
                      <div className="row row--wrap">
                        <a className="btn btn--sm" href={configFileHref} download={configFile.filename}>
                          Download {configFile.filename}
                        </a>
                        <span className="t-sm t-muted">
                          Save it where {client.name} reads its settings.
                        </span>
                      </div>
                    ) : null}
                  </>
                ) : (
                  <>
                    <div className="snippet snippet--block">
                      <code>{prompt}</code>
                    </div>
                    <div className="row row--wrap">
                      <Button size="sm" onClick={() => copy(prompt, "Prompt")}>
                        <CopyIcon className="icon--sm" />
                        Copy prompt
                      </Button>
                      <span className="t-sm t-muted">The app sets itself up and reports back.</span>
                    </div>
                  </>
                )}
              </div>
              {plaintext ? (
                <div className="stack stack--2">
                  <div className="keyline">
                    <span className="t-sm t-muted">Access key (shown once)</span>
                    <code>{plaintext}</code>
                    <Button size="sm" variant="plain" onClick={() => copy(plaintext, "Access key")}>
                      <CopyIcon className="icon--sm" />
                      Copy
                    </Button>
                  </div>
                  <p className="t-sm t-muted">
                    It&rsquo;s already in the command above. Copy it now — palaia can&rsquo;t show it
                    again.
                  </p>
                </div>
              ) : (
                <p className="t-sm t-muted">
                  This command needs the access key shown when it was created. Lost it? Replace the
                  access key below — the old one stops working.
                </p>
              )}
            </div>
          </div>
          <div className="connect-step">
            <StepNumber n={3} done={connected} />
            <div className="connect-step__body">
              <p className="connect-step__title">Test the connection</p>
              {connected && token?.last_used_at ? (
                <p className="t-sm" title={exactTime(token.last_used_at)}>
                  Connected — last request {timeAgo(token.last_used_at)}.
                </p>
              ) : (
                <>
                  <p className="t-sm t-muted">
                    Ask {client.name}: &ldquo;What do you remember about this project?&rdquo; This
                    turns green when palaia receives the request.
                  </p>
                  <Waiting>Waiting for the first request…</Waiting>
                </>
              )}
            </div>
          </div>
          {error ? (
            <p className="field__error" role="alert" style={{ padding: "0 var(--space-5) var(--space-4)" }}>
              {error}
            </p>
          ) : null}
          <CardFoot>
            <Button size="sm" onClick={() => setConfirm("replace")} disabled={busy}>
              Replace access key
            </Button>
            <Button size="sm" variant="destructive" onClick={() => setConfirm("revoke")} disabled={busy}>
              Revoke access
            </Button>
          </CardFoot>
        </>
      )}

      <ConfirmDialog
        open={confirm === "revoke"}
        onCancel={() => setConfirm(null)}
        onConfirm={() => void revokeAccess()}
        title={`Revoke access for ${client.name}?`}
        confirmLabel="Revoke access"
        destructive
        busy={busy}
      >
        <p>
          {client.name} stops reading and saving your memories right away. You can connect it
          again later with a new access key.
        </p>
      </ConfirmDialog>
      <ConfirmDialog
        open={confirm === "replace"}
        onCancel={() => setConfirm(null)}
        onConfirm={() => void replaceKey()}
        title={`Replace the access key for ${client.name}?`}
        confirmLabel="Replace access key"
        busy={busy}
      >
        <p>
          palaia creates a new key with the same permissions and turns the old one off.{" "}
          {client.name} stops working until you paste the new command.
        </p>
      </ConfirmDialog>
    </Card>
  );
}

function PermissionRow({
  memory,
  read,
  save,
  onToggle,
}: {
  memory: string;
  read: boolean;
  save: boolean;
  onToggle: (memory: string, permission: "read" | "write", checked: boolean) => void;
}) {
  return (
    <>
      <span className="permgrid__name">{memory}</span>
      <span className="permgrid__cell">
        <input
          type="checkbox"
          aria-label={`Read ${memory}`}
          checked={read}
          onChange={(event) => onToggle(memory, "read", event.target.checked)}
        />
      </span>
      <span className="permgrid__cell">
        <input
          type="checkbox"
          aria-label={`Save to ${memory}`}
          checked={save}
          onChange={(event) => onToggle(memory, "write", event.target.checked)}
        />
      </span>
    </>
  );
}
