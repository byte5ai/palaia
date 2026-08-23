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
 * Honest about what this does and does not wire up yet: issuing a token
 * here does not, by itself, mount an MCP gateway profile at the URL the
 * copy-command names — that still needs a `GatewayConfig` naming this
 * profile path (`palaia-hub`'s own config surface, SPEC-105/107/108's, not
 * this SPEC's REST additions). Until that profile exists, the command is
 * correct in *shape* but the endpoint 404s. Step 3 tells the truth about
 * this by polling for a real first call rather than faking one.
 */
import { useEffect, useState } from "react";

import type { CreatedToken, TokenInfo } from "../lib/api/client";
import { api, ApiError } from "../lib/api/client";
import type { GuidedClient } from "../lib/clients";
import { CheckIcon, CopyIcon } from "../shell/icons";
import { Badge } from "./Badge";
import { Button } from "./Button";
import { Card, CardBody, CardFoot, CardHead, CardSubject } from "./Card";
import { Input } from "./Field";
import { Waiting } from "./Skeleton";
import { useToast } from "./Toast";

function describeError(err: unknown): string {
  if (err instanceof ApiError) {
    const body = err.body as { detail?: string } | undefined;
    if (body?.detail) return body.detail;
    return `The hub answered ${err.status}.`;
  }
  return "Could not reach the hub.";
}

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
  const [tab, setTab] = useState<"command" | "prompt">("command");
  const [error, setError] = useState<string | null>(null);

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

  const origin = typeof window !== "undefined" ? window.location.origin : "";
  const profile = token?.profile ?? profileDraft;
  const connected = Boolean(token?.last_used_at);

  async function issueToken() {
    setIssuing(true);
    setError(null);
    try {
      const result: CreatedToken = await api.createToken({ name: client.name, profile: profileDraft });
      setToken(result.info);
      setPlaintext(result.token);
      onTokenIssued?.(result.info);
    } catch (err) {
      setError(describeError(err));
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
                <Button variant="primary" onClick={issueToken} disabled={issuing}>
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
