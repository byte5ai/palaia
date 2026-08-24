/**
 * Connect-a-client (SPEC-110 deliverable #3): every §6-matrix client gets
 * a row; a guided one gets the real `ConnectPanel` flow, a not-yet one
 * gets a truthful, mode-aware explanation — never a dead end.
 */
import { useEffect, useState } from "react";

import { Button } from "../components/Button";
import { ConnectPanel, formatAge } from "../components/ConnectPanel";
import { SkillPanel } from "../components/SkillPanel";
import { useToast } from "../components/Toast";
import type { TokenInfo } from "../lib/api/client";
import { api, ApiError } from "../lib/api/client";
import { CLIENTS, type HubMode, type NotYetClient } from "../lib/clients";
import { CopyIcon, InfoIcon, WarningIcon } from "../shell/icons";

/** SPEC-205 deliverable #3: sign-in is turned on and configured — the
 * client's own connector unlocks with the real address filled in, instead
 * of the "not yet" reason. */
function OAuthReadyCard({ client, issuer }: { client: NotYetClient; issuer: string }) {
  const toast = useToast();
  const Icon = client.icon;
  const connect = client.oauthConnect?.(issuer, "default");
  if (!connect) return null;
  return (
    <div className="card">
      <div className="card__head">
        <div>
          <span className="card__subject">{client.name}</span>
          <p className="t-xs t-muted">{client.subtitle}</p>
        </div>
        <span className="badge badge--ok">
          <Icon className="icon icon--sm" style={{ marginRight: 4 }} />
          ready to connect
        </span>
      </div>
      <div className="card__body stack">
        <div className="snippet snippet--wrap">
          <code>{connect.url}</code>
          <Button
            size="sm"
            onClick={() =>
              navigator.clipboard.writeText(connect.url).then(() => toast.show("Address copied."))
            }
          >
            <CopyIcon className="icon--sm" />
            Copy
          </Button>
        </div>
        <p className="t-sm t-muted">{connect.note}</p>
      </div>
    </div>
  );
}

function NotYetCard({ client, mode }: { client: NotYetClient; mode: HubMode }) {
  const Icon = client.icon;
  return (
    <div className="card">
      <div className="card__head">
        <div>
          <span className="card__subject">{client.name}</span>
          <p className="t-xs t-muted">{client.subtitle}</p>
        </div>
        <span className="badge badge--warn">not yet available</span>
      </div>
      <div className="card__body stack">
        <div className="banner banner--warn">
          <WarningIcon className="icon icon--sm" />
          <div>
            <p className="banner__title">Not available yet — and here is exactly why</p>
            <p className="t-sm t-muted">{client.reason(mode)}</p>
          </div>
        </div>
        <div className="row" style={{ gap: 8 }}>
          <Icon className="icon icon--sm" />
          <span className="t-xs t-subtle">
            Tracked in MASTERPLAN.md §6 — this page updates the moment that section does.
          </span>
        </div>
      </div>
    </div>
  );
}

export function Clients() {
  const [mode, setMode] = useState<HubMode>("locked");
  // SPEC-205 deliverable #3: null until known — while null, cloud
  // connectors show their ordinary `reason()`, same as before this SPEC.
  const [oauthIssuer, setOauthIssuer] = useState<string | null>(null);
  const [tokens, setTokens] = useState<TokenInfo[]>([]);
  const [tokenStoreAvailable, setTokenStoreAvailable] = useState(true);
  const [selectedId, setSelectedId] = useState(CLIENTS[0]!.id);

  useEffect(() => {
    let cancelled = false;
    api
      .mode()
      .then((status) => {
        if (cancelled) return;
        setMode(status.active_mode);
        const ready =
          (status.active_mode === "cloud" || status.active_mode === "open") &&
          status.oauth_enabled &&
          status.oauth_issuer;
        setOauthIssuer(ready ? status.oauth_issuer : null);
      })
      .catch(() => {
        // mode is cosmetic here — the not-yet reasons still render, just
        // without the mode-specific half of the sentence
      });
    api
      .listTokens()
      .then((list) => {
        if (!cancelled) setTokens(list);
      })
      .catch((err) => {
        // A 404 means no token store is mounted at all (create_app's
        // opt-in wiring) — every client then honestly reads "not
        // connected" rather than issuing a token nothing will ever check.
        if (!cancelled && err instanceof ApiError && err.status === 404) {
          setTokenStoreAvailable(false);
        }
      });
    return () => {
      cancelled = true;
    };
  }, []);

  function tokenFor(name: string): TokenInfo | undefined {
    return tokens.find((t) => t.name === name && !t.revoked_at);
  }

  const selected = CLIENTS.find((c) => c.id === selectedId) ?? CLIENTS[0]!;
  const connectedCount = new Set(
    tokens.filter((t) => !t.revoked_at && t.last_used_at).map((t) => t.name),
  ).size;

  return (
    <section className="connect">
      <div className="card">
        <div className="card__head">
          <h3 className="card__title">clients</h3>
          <span className="t-meta">
            {connectedCount === 0 ? "none connected" : `${connectedCount} connected`}
          </span>
        </div>
        <div className="clientlist">
          {CLIENTS.map((client) => {
            const token = tokenFor(client.name);
            const Icon = client.icon;
            return (
              <button
                key={client.id}
                type="button"
                className={["clientrow", client.id === selectedId ? "clientrow--on" : ""]
                  .filter(Boolean)
                  .join(" ")}
                onClick={() => setSelectedId(client.id)}
                aria-current={client.id === selectedId ? "true" : undefined}
              >
                <span className="clientrow__mark">
                  <Icon className="icon--sm" />
                </span>
                <span className="grow">
                  <span className="clientrow__name">{client.name}</span>
                  <br />
                  <span className="clientrow__meta">
                    {token
                      ? token.last_used_at
                        ? `connected · ${formatAge(token.last_used_at)}`
                        : "token issued · waiting for first call"
                      : client.kind === "guided"
                        ? "not connected"
                        : oauthIssuer && client.oauthConnect
                          ? "ready to connect"
                          : "not yet available"}
                  </span>
                </span>
                {token?.last_used_at ? <span className="dot dot--ok" /> : null}
              </button>
            );
          })}
        </div>
        <div className="card__foot">
          <span className="t-xs t-subtle">
            Every client gets its own token and its own tool profile. Revoking one never touches
            the others.
          </span>
        </div>
      </div>
      <div className="stack">
        {!tokenStoreAvailable ? (
          <div className="card">
            <div className="card__body">
              <div className="banner banner--warn">
                <InfoIcon className="icon icon--sm" />
                <p className="t-sm t-muted">
                  This hub has no token store mounted, so no client can be issued a token from
                  here yet.
                </p>
              </div>
            </div>
          </div>
        ) : selected.kind === "guided" ? (
          <ConnectPanel
            key={selected.id}
            client={selected}
            onTokenIssued={(info) =>
              setTokens((prev) => [...prev.filter((t) => t.id !== info.id), info])
            }
          />
        ) : oauthIssuer && selected.oauthConnect ? (
          <OAuthReadyCard client={selected} issuer={oauthIssuer} />
        ) : (
          <NotYetCard client={selected} mode={mode} />
        )}
        {/* Offered whether or not the connector itself is ready: a skill is
            installed in the client, not in the hub, so a not-yet client can
            still be taught the habit before its connector lands (SPEC-207). */}
        <SkillPanel clientId={selected.id} clientName={selected.name} />
      </div>
    </section>
  );
}
