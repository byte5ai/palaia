/**
 * One guided client's connect flow (SPEC-110): issue a real per-client
 * token (SPEC-108's already-built `/api/auth/tokens`), show the
 * copy-command / paste-prompt pair, and detect the client's first
 * successful tool call without a page reload — this SPEC's acceptance
 * criterion "connect page detects and shows a client's first successful
 * tool call".
 *
 * If a live, non-revoked token already exists for this client (matched by
 * name), this panel finds it itself on mount and starts from step 2: no
 * second token is minted just because the page was revisited. That lookup
 * deliberately happens here rather than depending on a parent-supplied
 * prop that might resolve later than this panel's own mount — see the
 * `useEffect` below.
 *
 * As of SPEC-210, the `default` profile this panel suggests really is
 * mounted live once any vault exists (see
 * `palaia_hub.gateway.dynamic.DynamicGateway` / `palaia_hub.serve` on the
 * server side, and `Onboarding.tsx`'s step 3, which creates that vault) —
 * issuing a token here and reaching the endpoint it names both work with
 * no hub restart in between. A caller can still name a different,
 * unmounted profile path by hand; step 3 below tells the truth about
 * whichever path is actually in play by polling for a real first call
 * rather than faking one.
 *
 * Issue 270: step 1 also offers a per-vault read/save picker (checkboxes
 * next to each vault the target tool profile mounts), all checked by
 * default — the same "every vault, read and save" shape `palaia_hub.auth.
 * routes`'s empty-`scopes` default already grants, so a caller who never
 * touches the picker sends exactly what it always has: no `scopes` field
 * at all, letting that server-side default do the work. Only unchecking a
 * box switches this panel to sending an explicit, narrower list — see
 * `explicitScopes` below. The picker never sends an empty explicit list on
 * purpose: an empty `scopes` array is the server's "use the default"
 * sentinel (that module's docstring), so "everything unchecked" would
 * silently grant full access instead of none — `wouldGrantNothing` below
 * blocks Issue token in that one case rather than let it widen access.
 */
import { useEffect, useMemo, useState } from "react";

import type { CreatedToken, GatewayProfile, TokenInfo } from "../lib/api/client";
import { api } from "../lib/api/client";
import type { GuidedClient } from "../lib/clients";
import { describeApiError } from "../lib/errors";
import { CheckIcon, CopyIcon } from "../shell/icons";
import { Badge } from "./Badge";
import { Button } from "./Button";
import { Card, CardBody, CardFoot, CardHead, CardSubject } from "./Card";
import { Input } from "./Field";
import { Waiting } from "./Skeleton";
import { useToast } from "./Toast";

export function formatAge(iso: string): string {
  const seconds = Math.max(0, (Date.now() - new Date(iso).getTime()) / 1000);
  if (seconds < 60) return `${Math.round(seconds)} s ago`;
  if (seconds < 3600) return `${Math.round(seconds / 60)} min ago`;
  if (seconds < 86400) return `${Math.round(seconds / 3600)} h ago`;
  return `${Math.round(seconds / 86400)} d ago`;
}

export function ConnectPanel({
  client,
  defaultProfile = "default",
  onTokenIssued,
}: {
  client: GuidedClient;
  defaultProfile?: string;
  /** Called once a token for this client is known — freshly minted, or
   * found already existing on mount — so a parent showing its own token
   * list (the sidebar's connection dots) can pick it up without a
   * separate fetch of its own. */
  onTokenIssued?: (info: TokenInfo) => void;
}) {
  const toast = useToast();
  const [profileDraft, setProfileDraft] = useState(defaultProfile);
  const [issuing, setIssuing] = useState(false);
  const [plaintext, setPlaintext] = useState<string | null>(null);
  const [token, setToken] = useState<TokenInfo | null>(null);
  const [tab, setTab] = useState<"command" | "prompt" | "file">("command");
  const [error, setError] = useState<string | null>(null);
  const [profiles, setProfiles] = useState<GatewayProfile[] | null>(null);
  // Every entry a caller has explicitly *un*checked, as `vault-key:read` /
  // `vault-key:write`. Absence means checked — so a vault this panel has
  // never rendered a checkbox for (the profile isn't known yet, or has no
  // vaults) never ends up narrower by accident.
  const [unchecked, setUnchecked] = useState<Set<string>>(new Set());

  // Look for an already-issued, non-revoked token for this client on
  // mount — inside the effect's own promise callback, never synchronously
  // in the effect body (react-hooks/set-state-in-effect), and scoped to
  // `client.name` so switching which client this panel is for (a fresh
  // mount — Clients.tsx/Onboarding.tsx both key it by client id) looks
  // again rather than keeping the previous client's token.
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
        // no token store mounted, or a transient fetch failure — either
        // way this panel just starts from step 1, same as a client that
        // genuinely has never been issued a token
      });
    return () => {
      cancelled = true;
    };
    // Intentionally scoped to `client.name` only: this must re-run when
    // the client this panel is for changes, not on every render where the
    // parent happens to pass a new `onTokenIssued` closure identity.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [client.name]);

  // Which vaults the target tool profile mounts, for the read/save picker
  // below — the same `/api/gateway/profiles` listing the tool-profile
  // editor already reads (ToolProfiles.tsx), not a new endpoint. Fetched
  // once on mount: this panel only needs to look a profile name up in an
  // already-fetched list, not refetch on every keystroke in the profile
  // field.
  useEffect(() => {
    let cancelled = false;
    api
      .listGatewayProfiles()
      .then((list) => {
        if (!cancelled) setProfiles(list);
      })
      .catch(() => {
        // no gateway attached, or a transient failure — the picker simply
        // stays hidden and issuing a token behaves exactly as it did
        // before this panel could show one (no explicit scopes, ever).
      });
    return () => {
      cancelled = true;
    };
  }, []);

  // A caller can retype the profile name before issuing; whatever was
  // unchecked for the previous name shouldn't silently narrow a different
  // profile's vaults once it resolves. Adjusted during render rather than
  // in an effect — the pattern React's own docs recommend for "reset some
  // state when a prop changes" (react.dev/learn/you-might-not-need-an-
  // effect#adjusting-some-state-when-a-prop-changes) — since a `useEffect`
  // that calls `setState` unconditionally on every commit is exactly the
  // cascading-render shape `react-hooks/set-state-in-effect` flags.
  const [previousProfileDraft, setPreviousProfileDraft] = useState(profileDraft);
  if (profileDraft !== previousProfileDraft) {
    setPreviousProfileDraft(profileDraft);
    setUnchecked(new Set());
  }

  const targetProfile = profiles?.find((candidate) => candidate.path === profileDraft) ?? null;
  const mountedVaults = targetProfile?.vaults ?? [];

  function isChecked(vaultKey: string, permission: "read" | "write"): boolean {
    return !unchecked.has(`${vaultKey}:${permission}`);
  }

  function togglePermission(vaultKey: string, permission: "read" | "write", checked: boolean) {
    setUnchecked((prev) => {
      const next = new Set(prev);
      const id = `${vaultKey}:${permission}`;
      if (checked) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  // Nothing has been unchecked: this is today's behavior, so no explicit
  // list is built at all (see `issueToken` below).
  const pickerTouched = unchecked.size > 0;
  const explicitScopes = pickerTouched
    ? mountedVaults.flatMap((key) => {
        const scopes: string[] = [];
        if (isChecked(key, "read")) scopes.push(`vault:${key}:read`);
        if (isChecked(key, "write")) scopes.push(`vault:${key}:write`);
        return scopes;
      })
    : [];
  // Every box unchecked would resolve to an empty list — which the server
  // reads as "no explicit scopes were sent, use the default" (see this
  // file's header comment), the opposite of what an operator unchecking
  // everything means. Block issuing rather than silently grant more than
  // shown.
  const wouldGrantNothing = pickerTouched && explicitScopes.length === 0;

  const origin = typeof window !== "undefined" ? window.location.origin : "";
  const profile = token?.profile ?? profileDraft;
  const connected = Boolean(token?.last_used_at);

  // SPEC-306 deliverable #3: a one-click "download config file" tab, for
  // the clients whose real install path is "put this file there" rather
  // than "run this command" (their real formats — SPEC-209-corrected).
  const configFile = client.configFile?.(origin, profile);
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

  async function issueToken() {
    setIssuing(true);
    setError(null);
    try {
      // No `scopes` field at all unless the picker was actually touched —
      // this is what keeps the one-click flow byte-for-byte what it always
      // sent, so the server's own "empty scopes = everything this profile
      // mounts" default (still the no-touch path) is the one deciding
      // what a caller who never opens the picker gets.
      const body =
        pickerTouched && explicitScopes.length > 0
          ? { name: client.name, profile: profileDraft, scopes: explicitScopes }
          : { name: client.name, profile: profileDraft };
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

  // Poll for the first successful call once a token exists — the same
  // "no refresh button anywhere" rule the SSE-backed shell follows
  // (system.md §0); this endpoint just isn't event-stream-backed yet.
  useEffect(() => {
    if (!token || token.last_used_at) return;
    const id = window.setInterval(() => {
      api
        .listTokens()
        .then((tokens) => {
          const mine = tokens.find((t) => t.id === token.id);
          if (mine) setToken(mine);
        })
        .catch(() => {
          // a transient fetch failure just means the next tick tries again
        });
    }, 3000);
    return () => window.clearInterval(id);
  }, [token]);

  function copy(text: string, what: string) {
    navigator.clipboard.writeText(text).then(
      () => toast.show(`${what} copied.`),
      () => toast.show("Could not copy — select and copy manually."),
    );
  }

  const Icon = client.icon;

  return (
    <Card>
      <CardHead>
        <div className="row" style={{ gap: 10 }}>
          {connected ? (
            <span className="empty__mark" style={{ width: 34, height: 34, borderRadius: 10 }}>
              <CheckIcon className="icon--sm" />
            </span>
          ) : null}
          <div>
            <CardSubject>{connected ? `${client.name} is connected` : client.name}</CardSubject>
            <p className="t-xs t-muted" style={{ marginTop: 2 }}>
              {connected && token?.last_used_at
                ? `Last seen ${formatAge(token.last_used_at)}`
                : token
                  ? "Token issued — palaia is watching for its first call."
                  : "Issue this client its own token, then paste one thing."}
            </p>
          </div>
        </div>
        {connected ? (
          <Badge variant="ok" live>
            live
          </Badge>
        ) : (
          <span className="badge">
            <Icon className="icon--sm" style={{ marginRight: 4 }} />
            {client.estimate}
          </span>
        )}
      </CardHead>
      <CardBody className="stack">
        {!token ? (
          <div className="numstep">
            <span className="numstep__num numstep__num--on">1</span>
            <div className="grow stack stack--3">
              <div>
                <p className="numstep__title">Name the tool profile it should see</p>
                <p className="t-sm t-muted">
                  A hundred tools in one conversation ruins an agent. This becomes part of the
                  address, so this client cannot see anything else.
                </p>
              </div>
              <div className="row row--wrap">
                <Input
                  value={profileDraft}
                  onChange={(event) => setProfileDraft(event.target.value.trim() || "default")}
                  style={{ maxWidth: 220 }}
                  aria-label="Tool profile name"
                />
              </div>
              {mountedVaults.length > 0 ? (
                <div className="stack stack--2">
                  <span className="field__label">What {client.name} can read or save</span>
                  <p className="t-xs t-muted">
                    Every vault below is included, both ways, by default — the same as today.
                    Uncheck a box to leave a vault out, or to give read-only access to it.
                  </p>
                  <div className="stack stack--2">
                    {mountedVaults.map((vaultKey) => (
                      <div key={vaultKey} className="row row--wrap" style={{ gap: 14 }}>
                        <span className="t-sm t-mono">{vaultKey}</span>
                        <label className="row" style={{ gap: 4 }}>
                          <input
                            type="checkbox"
                            checked={isChecked(vaultKey, "read")}
                            onChange={(event) =>
                              togglePermission(vaultKey, "read", event.target.checked)
                            }
                          />
                          <span className="t-xs">Read</span>
                        </label>
                        <label className="row" style={{ gap: 4 }}>
                          <input
                            type="checkbox"
                            checked={isChecked(vaultKey, "write")}
                            onChange={(event) =>
                              togglePermission(vaultKey, "write", event.target.checked)
                            }
                          />
                          <span className="t-xs">Save</span>
                        </label>
                      </div>
                    ))}
                  </div>
                  {wouldGrantNothing ? (
                    <p className="field__error">
                      Check at least one box — leaving every vault unchecked would give this
                      client full access instead of none.
                    </p>
                  ) : null}
                </div>
              ) : null}
              <div className="row row--wrap">
                <Button
                  variant="primary"
                  onClick={issueToken}
                  disabled={issuing || wouldGrantNothing}
                >
                  {issuing ? "Issuing…" : "Issue token"}
                </Button>
              </div>
              {error ? <p className="field__error">{error}</p> : null}
            </div>
          </div>
        ) : (
          <div className="numstep">
            <span className="numstep__num numstep__num--done">
              <CheckIcon className="icon--sm" />
            </span>
            <div className="grow">
              <p className="numstep__title">Paste one thing</p>
              <Card variant="flat" style={{ marginTop: 8 }}>
                <div className="card__head" style={{ borderBottom: 0, padding: "0 16px" }}>
                  <div className="tabbar" role="tablist">
                    <button
                      type="button"
                      role="tab"
                      aria-selected={tab === "command"}
                      onClick={() => setTab("command")}
                    >
                      Copy the command
                    </button>
                    <button
                      type="button"
                      role="tab"
                      aria-selected={tab === "prompt"}
                      onClick={() => setTab("prompt")}
                    >
                      Or paste a prompt
                    </button>
                    {configFile ? (
                      <button
                        type="button"
                        role="tab"
                        aria-selected={tab === "file"}
                        onClick={() => setTab("file")}
                      >
                        Or download the file
                      </button>
                    ) : null}
                  </div>
                </div>
                <CardBody className="stack stack--3">
                  {tab === "command" ? (
                    <div className="snippet snippet--wrap">
                      <code>{client.command(origin, profile)}</code>
                      <Button size="sm" onClick={() => copy(client.command(origin, profile), "Command")}>
                        <CopyIcon className="icon--sm" />
                        Copy
                      </Button>
                    </div>
                  ) : tab === "file" && configFile ? (
                    <div className="snippet snippet--block">
                      <code>{configFile.content}</code>
                    </div>
                  ) : (
                    <div className="snippet snippet--block">
                      <code>{client.prompt(origin, profile)}</code>
                    </div>
                  )}
                  {tab === "prompt" ? (
                    <div className="row row--wrap">
                      <Button size="sm" onClick={() => copy(client.prompt(origin, profile), "Prompt")}>
                        <CopyIcon className="icon--sm" />
                        Copy prompt
                      </Button>
                      <span className="t-xs t-muted">The agent configures itself and reports back.</span>
                    </div>
                  ) : null}
                  {tab === "file" && configFile && configFileHref ? (
                    <div className="row row--wrap">
                      <a className="btn btn--sm" href={configFileHref} download={configFile.filename}>
                        Download {configFile.filename}
                      </a>
                      <span className="t-xs t-muted">
                        Save it where {client.name} reads its MCP config from.
                      </span>
                    </div>
                  ) : null}
                  {plaintext ? (
                    <div className="row row--wrap" style={{ gap: 6 }}>
                      <span className="t-xs t-muted">Its token (shown once):</span>
                      <span className="chip chip--mono">{plaintext}</span>
                      <Button size="sm" variant="quiet" onClick={() => copy(plaintext, "Token")}>
                        <CopyIcon className="icon--sm" />
                      </Button>
                    </div>
                  ) : null}
                </CardBody>
              </Card>
            </div>
          </div>
        )}

        {token ? (
          <div className="numstep">
            <span className={["numstep__num", connected ? "numstep__num--done" : ""].join(" ")}>
              {connected ? <CheckIcon className="icon--sm" /> : "3"}
            </span>
            <div className="grow">
              <p className="numstep__title">palaia watches for the first call</p>
              {connected ? (
                <p className="t-sm t-muted">
                  Connected. This line updated on its own — no refresh needed.
                </p>
              ) : (
                <>
                  <div className="row row--wrap" style={{ marginTop: 4 }}>
                    <Waiting>Waiting for this client to say hello…</Waiting>
                    <span className="t-xs t-subtle">No refresh needed.</span>
                  </div>
                  <p className="t-xs t-muted" style={{ marginTop: 8 }}>
                    Once a gateway profile named <span className="t-mono">{profile}</span> exposes a
                    vault, ask it <em>&ldquo;what do you remember about this project?&rdquo;</em> and
                    this line changes on its own.
                  </p>
                </>
              )}
            </div>
          </div>
        ) : null}
      </CardBody>
      <CardFoot>
        <span className="t-xs t-subtle">
          Every client gets its own token and its own tool profile. Revoking one never touches the
          others.
        </span>
      </CardFoot>
    </Card>
  );
}
