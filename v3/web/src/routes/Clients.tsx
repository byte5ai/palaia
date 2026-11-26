/**
 * AI apps › Apps (SPEC-110 #3, report §3.5): every app palaia supports as one
 * table row — name, how it connects, status, last request — with the apps in
 * use first. A row's button opens that app's way to connect in a side panel
 * (`/apps?app=<id>`, so the panel can be linked to). An app that cannot work
 * in the current mode says why and links to the setting that fixes it;
 * nothing here is a dead end.
 */
import { useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";

import "./apps.css";

import { AddToClaudeButton } from "../components/AddToClaudeButton";
import { Button, LinkButton } from "../components/Button";
import { Callout } from "../components/Callout";
import { Card, CardBody, CardFoot, CardHeader } from "../components/Card";
import { ConnectPanel, ToolSetPicker } from "../components/ConnectPanel";
import { ConfirmDialog, Dialog } from "../components/Dialog";
import { Disclosure } from "../components/Disclosure";
import { ErrorState, LoadingState } from "../components/EmptyState";
import { SkillPanel } from "../components/SkillPanel";
import { StatusPill, type StatusTone } from "../components/StatusPill";
import { useToast } from "../components/Toast";
import type { GatewayProfile, TokenInfo } from "../lib/api/client";
import { api, ApiError } from "../lib/api/client";
import {
  CLIENTS,
  type ClientEntry,
  type DownloadClient,
  type HubMode,
  type NotYetClient,
} from "../lib/clients";
import { saveBlob } from "../lib/download";
import { describeApiError } from "../lib/errors";
import { exactTime, timeAgo } from "../lib/format";
import { CopyIcon, DownloadIcon } from "../shell/icons";
import { MemoryUseCard } from "./MemoryUse";

interface AppStatus {
  tone: StatusTone;
  label: string;
  line: string;
  /** How the app connects, in a few words: the table's second column. */
  how: string;
  /** Nothing has happened with this app yet. The table says "Not connected"
   * in plain text instead of repeating a pill on every such row. */
  untouched: boolean;
  lastUsed: string | null;
}

/** The live keys of an app, newest use first. */
function liveKeys(tokens: TokenInfo[], name: string): TokenInfo[] {
  return tokens
    .filter((t) => t.name === name && !t.revoked_at)
    .sort((a, b) => (b.last_used_at ?? "").localeCompare(a.last_used_at ?? ""));
}

function capitalize(text: string): string {
  return text.charAt(0).toUpperCase() + text.slice(1);
}

function statusOf(
  client: ClientEntry,
  keys: TokenInfo[],
  mode: HubMode | null,
  cloudReady: boolean,
): AppStatus {
  const lastUsed = keys.find((k) => k.last_used_at)?.last_used_at ?? null;
  if (client.kind === "notYet") {
    const base = { how: "Connects from the internet", untouched: false, lastUsed: null };
    if (cloudReady && client.oauthConnect) {
      return {
        ...base,
        tone: "neutral",
        label: "Ready to connect",
        line: "Signs in with your palaia account",
        how: "Signs in with your palaia account",
        untouched: true,
      };
    }
    if (mode === "locked") {
      return { ...base, tone: "warn", label: "Needs Cloud mode", line: "Connects from the internet" };
    }
    if (mode === null) {
      return { ...base, tone: "neutral", label: "Connects from the internet", line: client.subtitle, untouched: true };
    }
    return { ...base, tone: "warn", label: "Needs sign-in", line: "Turn on sign-in for AI apps first" };
  }
  const how = client.kind === "download" ? "One-click download" : capitalize(client.estimate);
  if (lastUsed) {
    return { tone: "ok", label: "Connected", line: `Last request ${timeAgo(lastUsed)}`, how, untouched: false, lastUsed };
  }
  if (keys.length > 0) {
    return {
      tone: "info",
      label: "Waiting for first use",
      line: "Access key created, no request yet",
      how,
      untouched: false,
      lastUsed,
    };
  }
  return { tone: "neutral", label: "Ready to connect", line: how, how, untouched: true, lastUsed };
}

/** Two letters that stand for an app in its row. Not a logo: palaia shows no
 * third-party marks (system.md §1.5). */
function monogram(client: ClientEntry): string {
  if (client.id === "generic") return "+";
  const words = client.name.split(/[^A-Za-z0-9]+/).filter(Boolean);
  const letters = words.length > 1 ? words[0]![0]! + words[1]![0]! : words[0]!.slice(0, 2);
  return letters.charAt(0).toUpperCase() + letters.charAt(1);
}

/** What a row's button says: what opening the panel is for. */
function actionLabel(client: ClientEntry, keys: TokenInfo[], status: AppStatus): string {
  if (keys.length > 0) return "Manage";
  if (client.kind === "notYet" && !status.untouched) return "How to connect";
  return "Connect";
}

/** Claude Desktop (SPEC-306): a signed extension built for this palaia on
 * every download, with the address and a new access key inside. Fetched
 * through the API client, so an expired session goes to sign-in and a
 * refusal is shown in palaia's words (issue 382). */
function DesktopCard({
  client,
  keys,
  status,
  profiles,
  onDownloaded,
  onRevoked,
}: {
  client: DownloadClient;
  keys: TokenInfo[];
  status: AppStatus;
  profiles: GatewayProfile[];
  /** A download may have made a new access key: look again. */
  onDownloaded: () => void;
  onRevoked: (ids: string[]) => void;
}) {
  const toast = useToast();
  const [profile, setProfile] = useState(profiles[0]?.path ?? "default");
  const [downloading, setDownloading] = useState(false);
  const [confirm, setConfirm] = useState(false);
  const [busy, setBusy] = useState(false);
  const lastUsed = keys.find((k) => k.last_used_at)?.last_used_at ?? null;
  const toolSet = profiles.some((p) => p.path === profile) ? profile : (profiles[0]?.path ?? "default");

  async function download() {
    setDownloading(true);
    try {
      const file = await api.downloadFile(client.downloadUrl("", toolSet));
      saveBlob(file.blob, file.filename ?? "palaia.mcpb");
      onDownloaded();
    } catch (err) {
      toast.show(describeApiError(err));
    } finally {
      setDownloading(false);
    }
  }

  async function revoke() {
    setBusy(true);
    const revoked: string[] = [];
    try {
      // The keys that exist now, not the ones this page loaded: every
      // download makes a new one, and each must stop working.
      const live = (await api.listTokens()).filter(
        (t) => t.name === client.name && !t.revoked_at,
      );
      for (const key of live) {
        await api.revokeToken(key.id);
        revoked.push(key.id);
      }
      toast.show(`${client.name} can no longer use palaia.`);
    } catch (err) {
      toast.show(describeApiError(err));
    } finally {
      if (revoked.length > 0) onRevoked(revoked);
      setBusy(false);
      setConfirm(false);
    }
  }

  return (
    <Card>
      <CardHeader
        title={`Connect ${client.name}`}
        description="Download the Claude Desktop extension, then open it."
        actions={<StatusPill tone={status.tone}>{status.label}</StatusPill>}
      />
      <CardBody className="stack stack--4">
        <p className="t-muted">
          Claude Desktop shows palaia&rsquo;s address and a new access key. Click Install.
        </p>
        <div className="row row--wrap">
          <Button variant="primary" onClick={download} loading={downloading}>
            {downloading ? (
              "Preparing the file…"
            ) : (
              <>
                <DownloadIcon className="icon" />
                Download extension
              </>
            )}
          </Button>
        </div>
        {lastUsed ? (
          <p className="t-sm" title={exactTime(lastUsed)}>
            Connected — last request {timeAgo(lastUsed)}.
          </p>
        ) : keys.length > 0 ? (
          <p className="t-sm t-muted">
            An extension was downloaded. This turns green when Claude Desktop sends its first request.
          </p>
        ) : null}
        {profiles.length > 1 ? (
          <Disclosure summary="Advanced">
            <ToolSetPicker
              id="desktop-toolset"
              profiles={profiles}
              value={toolSet}
              onChange={setProfile}
              appName={client.name}
            />
          </Disclosure>
        ) : null}
      </CardBody>
      {keys.length > 0 ? (
        <CardFoot>
          <Button size="sm" variant="destructive" onClick={() => setConfirm(true)} disabled={busy}>
            Revoke access
          </Button>
        </CardFoot>
      ) : null}
      <ConfirmDialog
        open={confirm}
        onCancel={() => setConfirm(false)}
        onConfirm={() => void revoke()}
        title={`Revoke access for ${client.name}?`}
        confirmLabel="Revoke access"
        destructive
        busy={busy}
      >
        <p>
          Every extension downloaded for {client.name} stops working right away. Download a new
          one to connect it again.
        </p>
      </ConfirmDialog>
    </Card>
  );
}

/** claude.ai, ChatGPT, Grok: they connect from the internet and sign in with
 * the owner's palaia account, so they need Cloud mode and sign-in for AI
 * apps — said plainly, with the way to turn it on (SPEC-205 #3). */
function CloudAppCard({
  client,
  status,
  mode,
  issuer,
  profiles,
}: {
  client: NotYetClient;
  status: AppStatus;
  mode: HubMode | null;
  issuer: string | null;
  profiles: GatewayProfile[];
}) {
  const toast = useToast();
  const [profile, setProfile] = useState(profiles[0]?.path ?? "default");
  const toolSet = profiles.some((p) => p.path === profile) ? profile : (profiles[0]?.path ?? "default");
  const connect = issuer ? client.oauthConnect?.(issuer, toolSet) : undefined;
  const note = client.planNote;

  return (
    <Card>
      <CardHeader
        title={`Connect ${client.name}`}
        description={client.subtitle}
        actions={<StatusPill tone={status.tone}>{status.label}</StatusPill>}
      />
      <CardBody className="stack stack--4">
        {connect ? (
          <>
            {connect.installLink ? (
              <div>
                <AddToClaudeButton href={connect.installLink} />
              </div>
            ) : null}
            <p>
              {connect.installLink ? "Or paste" : "Paste"} this address into {client.name}&rsquo;s
              custom connector settings, then sign in with your palaia account when it asks.
            </p>
            <div className="snippet snippet--wrap">
              <code>{connect.url}</code>
              <Button
                size="sm"
                onClick={() =>
                  navigator.clipboard.writeText(connect.url).then(
                    () => toast.show("Address copied."),
                    () => toast.show("Couldn't copy. Select the address and copy it yourself."),
                  )
                }
              >
                <CopyIcon className="icon--sm" />
                Copy
              </Button>
            </div>
            {profiles.length > 1 ? (
              <Disclosure summary="Advanced">
                <ToolSetPicker
                  id={`${client.id}-toolset`}
                  profiles={profiles}
                  value={toolSet}
                  onChange={setProfile}
                  appName={client.name}
                />
              </Disclosure>
            ) : null}
          </>
        ) : mode === "locked" ? (
          <Callout
            tone="warn"
            title={`${client.name} needs Cloud mode`}
            actions={
              <LinkButton to="/settings/access" variant="primary" size="sm">
                Set up Cloud mode
              </LinkButton>
            }
          >
            {client.name} connects from the internet. Set up Cloud mode to give it a public
            address; your dashboard stays private.
          </Callout>
        ) : (
          <Callout
            tone={mode === null ? "info" : "warn"}
            title={
              mode === null
                ? `${client.name} connects from the internet`
                : `${client.name} needs sign-in for AI apps`
            }
            actions={
              <LinkButton to="/settings/access" variant="primary" size="sm">
                Open Access &amp; sign-in
              </LinkButton>
            }
          >
            {mode === null
              ? "It needs Cloud mode and sign-in for AI apps. Access & sign-in shows what this palaia has turned on."
              : `${client.name} signs in with your palaia account. Turn on sign-in for AI apps, then come back here.`}
          </Callout>
        )}
        {note ? <p className="t-sm t-muted">{note}</p> : null}
      </CardBody>
    </Card>
  );
}

export function Clients() {
  const [params, setParams] = useSearchParams();
  const [mode, setMode] = useState<HubMode | null>(null);
  // SPEC-205 #3: the address cloud apps sign in through, once Cloud or
  // Public mode has sign-in for AI apps turned on.
  const [issuer, setIssuer] = useState<string | null>(null);
  const [tokens, setTokens] = useState<TokenInfo[] | null>(null);
  const [tokensError, setTokensError] = useState<string | null>(null);
  const [keyStoreMissing, setKeyStoreMissing] = useState(false);
  const [profiles, setProfiles] = useState<GatewayProfile[]>([]);
  const [attempt, setAttempt] = useState(0);

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
        setIssuer(ready ? status.oauth_issuer : null);
      })
      .catch(() => {
        // Unknown mode: cloud apps say what they need without claiming which
        // mode this palaia is in.
      });
    api
      .listGatewayProfiles()
      .then((list) => {
        if (!cancelled) setProfiles(list);
      })
      .catch(() => {
        // No gateway: every address uses the default tool set.
      });
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    let cancelled = false;
    api
      .listTokens()
      .then((list) => {
        if (cancelled) return;
        setTokens(list);
        setTokensError(null);
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        if (err instanceof ApiError && err.status === 404) {
          // No access key store at all (create_app's opt-in wiring).
          setKeyStoreMissing(true);
          setTokens([]);
        } else {
          setTokensError(describeApiError(err));
        }
      });
    return () => {
      cancelled = true;
    };
  }, [attempt]);

  function refreshTokens() {
    api
      .listTokens()
      .then(setTokens)
      .catch(() => {
        // a passing failure: the list stays as it was
      });
  }

  function upsert(info: TokenInfo) {
    setTokens((prev) => [...(prev ?? []).filter((t) => t.id !== info.id), info]);
  }

  function markRevoked(ids: string[]) {
    const now = new Date().toISOString();
    setTokens((prev) =>
      (prev ?? []).map((t) => (ids.includes(t.id) ? { ...t, revoked_at: t.revoked_at ?? now } : t)),
    );
  }

  function open(id: string) {
    setParams((prev) => {
      const next = new URLSearchParams(prev);
      next.set("app", id);
      return next;
    });
  }

  function close() {
    setParams(
      (prev) => {
        const next = new URLSearchParams(prev);
        next.delete("app");
        return next;
      },
      { replace: true },
    );
  }

  if (tokensError) {
    return (
      <ErrorState
        title="Couldn't load your AI apps"
        details={tokensError}
        onRetry={() => {
          setTokensError(null);
          setAttempt((n) => n + 1);
        }}
      >
        palaia didn&rsquo;t say which apps are connected, so this page can&rsquo;t show them yet.
      </ErrorState>
    );
  }

  const cloudReady = issuer !== null;
  const selected = CLIENTS.find((c) => c.id === params.get("app")) ?? null;
  const keysOf = (client: ClientEntry) => liveKeys(tokens ?? [], client.name);
  const statusFor = (client: ClientEntry) => statusOf(client, keysOf(client), mode, cloudReady);
  const rows = CLIENTS.map((client) => {
    const keys = keysOf(client);
    return { client, keys, status: statusOf(client, keys, mode, cloudReady) };
  });
  const connectedCount = rows.filter((row) => row.status.lastUsed).length;
  const groups = [
    { title: "In use", empty: "No app connected yet. Pick one below.", rows: rows.filter((row) => row.keys.length > 0) },
    { title: "Available", empty: "Every supported app is in use.", rows: rows.filter((row) => row.keys.length === 0) },
  ];
  const selectedStatus = selected ? statusFor(selected) : null;

  return (
    <div className="stack">
      <Card>
        {tokens === null ? (
          <div className="card__body">
            <LoadingState label="Loading your AI apps…" lines={4} />
          </div>
        ) : (
          <div className="table-wrap">
            <table className="table table--flush apps-table">
              <caption className="apps-table__caption">
                {connectedCount} of {CLIENTS.length} connected
              </caption>
              <thead>
                <tr>
                  <th scope="col">App</th>
                  <th scope="col" className="apps-table__wide">
                    How it connects
                  </th>
                  <th scope="col" className="apps-table__status">
                    Status
                  </th>
                  <th scope="col" className="apps-table__wide">
                    Last request
                  </th>
                  <th scope="col">
                    <span className="sr-only">Action</span>
                  </th>
                </tr>
              </thead>
              {groups.map((group) => (
                <tbody key={group.title}>
                  <tr className="table__group">
                    <th colSpan={5} scope="rowgroup">
                      {group.title} · {group.rows.length}
                    </th>
                  </tr>
                  {group.rows.length === 0 ? (
                    <tr>
                      <td colSpan={5} className="t-muted">
                        {group.empty}
                      </td>
                    </tr>
                  ) : (
                    group.rows.map(({ client, keys, status }) => {
                      const action = actionLabel(client, keys, status);
                      const state = status.untouched ? (
                        <span className="t-sm t-muted">Not connected</span>
                      ) : (
                        <StatusPill tone={status.tone}>{status.label}</StatusPill>
                      );
                      return (
                        <tr key={client.id} className={client.id === selected?.id ? "table__row--selected" : undefined}>
                          <th scope="row">
                            <span className="apps-table__app">
                              <span className="monogram" aria-hidden="true">
                                {monogram(client)}
                              </span>
                              <span className="apps-table__name">
                                {client.name}
                                {/* On a phone the status shows under the name, so
                                    the row's button always fits. Assistive
                                    technology reads the Status cell instead. */}
                                <span className="apps-table__narrow" aria-hidden="true">
                                  {state}
                                </span>
                              </span>
                            </span>
                          </th>
                          <td className="apps-table__wide t-muted">{status.how}</td>
                          <td className="apps-table__status">{state}</td>
                          <td className="apps-table__wide t-meta" title={status.lastUsed ? exactTime(status.lastUsed) : undefined}>
                            {status.lastUsed ? capitalize(timeAgo(status.lastUsed)) : "–"}
                          </td>
                          <td className="apps-table__action">
                            <Button size="sm" onClick={() => open(client.id)} aria-label={`${action}: ${client.name}`}>
                              {action}
                            </Button>
                          </td>
                        </tr>
                      );
                    })
                  )}
                </tbody>
              ))}
            </table>
          </div>
        )}
      </Card>

      <MemoryUseCard />

      {selected && selectedStatus ? (
        <Dialog open onClose={close} size="side" title={selected.name} description={selectedStatus.how}>
          {keyStoreMissing && selected.kind !== "notYet" ? (
            <Callout tone="neutral" title="This palaia can't create access keys">
              Its access key store is turned off, so {selected.name} can&rsquo;t be connected from here.
            </Callout>
          ) : selected.kind === "guided" ? (
            <ConnectPanel
              // Remounted per app: the panel reads its starting state once.
              key={selected.id}
              client={selected}
              onTokenIssued={upsert}
              onTokenRevoked={markRevoked}
            />
          ) : selected.kind === "download" ? (
            <DesktopCard
              key={selected.id}
              client={selected}
              keys={keysOf(selected)}
              status={selectedStatus}
              profiles={profiles}
              onDownloaded={refreshTokens}
              onRevoked={markRevoked}
            />
          ) : (
            <CloudAppCard
              key={selected.id}
              client={selected}
              status={selectedStatus}
              mode={mode}
              issuer={issuer}
              profiles={profiles}
            />
          )}
          {/* A skill is installed in the app, not in palaia, so it is offered
              whether or not the connection is ready yet (SPEC-207). */}
          <SkillPanel clientId={selected.id} clientName={selected.name} />
        </Dialog>
      ) : null}
    </div>
  );
}
