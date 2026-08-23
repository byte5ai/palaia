/**
 * Connect-a-client (SPEC-110 deliverable #3): every §6-matrix client gets
 * a row; a guided one gets the real `ConnectPanel` flow, a not-yet one
 * gets a truthful, mode-aware explanation — never a dead end.
 */
import { useEffect, useState } from "react";

import { ConnectPanel, formatAge } from "../components/ConnectPanel";
import type { TokenInfo } from "../lib/api/client";
import { api, ApiError } from "../lib/api/client";
import { CLIENTS, type HubMode, type NotYetClient } from "../lib/clients";
import { InfoIcon, WarningIcon } from "../shell/icons";

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
  const [tokens, setTokens] = useState<TokenInfo[]>([]);
  const [tokenStoreAvailable, setTokenStoreAvailable] = useState(true);
  const [selectedId, setSelectedId] = useState(CLIENTS[0]!.id);

  useEffect(() => {
    let cancelled = false;
    api
      .info()
      .then((info) => {
        if (!cancelled) setMode(info.mode as HubMode);
      })
      .catch(() => {
        // health/mode is cosmetic here — the not-yet reasons still render,
        // just without the mode-specific half of the sentence
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
        ) : (
          <NotYetCard client={selected} mode={mode} />
        )}
      </div>
    </section>
  );
}
