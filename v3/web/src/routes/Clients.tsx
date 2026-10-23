/**
 * AI apps › Apps (SPEC-110 #3, report §3.5): every app palaia supports as one
 * row — name, status, one line — and the selected app's way to connect next
 * to it. An app that cannot work in the current mode says why and links to
 * the setting that fixes it; nothing here is a dead end.
 */
import { useEffect, useRef, useState } from "react";

import "./apps.css";

import { Button, LinkButton } from "../components/Button";
import { Callout } from "../components/Callout";
import { Card, CardBody, CardFoot, CardHeader } from "../components/Card";
import { ConnectPanel, ToolSetPicker } from "../components/ConnectPanel";
import { ConfirmDialog } from "../components/Dialog";
import { Disclosure } from "../components/Disclosure";
import { ErrorState, LoadingState } from "../components/EmptyState";
import { ListRow } from "../components/ListRow";
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
import { PHONE_QUERY, useMediaQuery } from "../lib/useMediaQuery";
import { CopyIcon, DownloadIcon } from "../shell/icons";
import { MemoryUseCard } from "./MemoryUse";

interface AppStatus {
  tone: StatusTone;
  label: string;
  line: string;
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

/** clients.ts states a cloud app's plan limits inside its "not yet"
 * reason; the part after "come back here." is that note on its own. */
function planNote(client: NotYetClient): string {
  const reason = client.reason("cloud");
  const marker = "come back here. ";
  const at = reason.indexOf(marker);
  return at >= 0 ? reason.slice(at + marker.length).trim() : "";
}

function statusOf(
  client: ClientEntry,
  keys: TokenInfo[],
  mode: HubMode | null,
  cloudReady: boolean,
): AppStatus {
  const lastUsed = keys.find((k) => k.last_used_at)?.last_used_at ?? null;
  if (client.kind === "notYet") {
    if (cloudReady && client.oauthConnect) {
      return { tone: "neutral", label: "Ready to connect", line: "Signs in with your palaia account" };
    }
    if (mode === "locked") {
      return { tone: "warn", label: "Needs Cloud mode", line: "Connects from the internet" };
    }
    if (mode === null) {
      return { tone: "neutral", label: "Connects from the internet", line: client.subtitle };
    }
    return { tone: "warn", label: "Needs sign-in", line: "Turn on sign-in for AI apps first" };
  }
  if (lastUsed) return { tone: "ok", label: "Connected", line: `Last request ${timeAgo(lastUsed)}` };
  if (keys.length > 0) {
    return { tone: "info", label: "Waiting for first use", line: "Access key created, no request yet" };
  }
  if (client.kind === "download") {
    return { tone: "neutral", label: "Ready to connect", line: "One-click download" };
  }
  return { tone: "neutral", label: "Ready to connect", line: capitalize(client.estimate) };
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
  onRevoked,
}: {
  client: DownloadClient;
  keys: TokenInfo[];
  status: AppStatus;
  profiles: GatewayProfile[];
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
    } catch (err) {
      toast.show(describeApiError(err));
    } finally {
      setDownloading(false);
    }
  }

  async function revoke() {
    setBusy(true);
    try {
      for (const key of keys) await api.revokeToken(key.id);
      onRevoked(keys.map((k) => k.id));
      toast.show(`${client.name} can no longer use palaia.`);
    } catch (err) {
      toast.show(describeApiError(err));
    } finally {
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
  const note = planNote(client);

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
            <p>
              Paste this address into {client.name}&rsquo;s custom connector settings, then sign in
              with your palaia account when it asks.
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
  const isPhone = useMediaQuery(PHONE_QUERY);
  const detailRef = useRef<HTMLDivElement>(null);
  const [mode, setMode] = useState<HubMode | null>(null);
  // SPEC-205 #3: the address cloud apps sign in through, once Cloud or
  // Public mode has sign-in for AI apps turned on.
  const [issuer, setIssuer] = useState<string | null>(null);
  const [tokens, setTokens] = useState<TokenInfo[] | null>(null);
  const [tokensError, setTokensError] = useState<string | null>(null);
  const [keyStoreMissing, setKeyStoreMissing] = useState(false);
  const [profiles, setProfiles] = useState<GatewayProfile[]>([]);
  const [selectedId, setSelectedId] = useState(CLIENTS[0]!.id);
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

  function upsert(info: TokenInfo) {
    setTokens((prev) => [...(prev ?? []).filter((t) => t.id !== info.id), info]);
  }

  function markRevoked(ids: string[]) {
    const now = new Date().toISOString();
    setTokens((prev) =>
      (prev ?? []).map((t) => (ids.includes(t.id) ? { ...t, revoked_at: t.revoked_at ?? now } : t)),
    );
  }

  function select(id: string) {
    setSelectedId(id);
    if (isPhone) detailRef.current?.scrollIntoView?.({ behavior: "smooth", block: "start" });
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
  const selected = CLIENTS.find((c) => c.id === selectedId) ?? CLIENTS[0]!;
  const keysOf = (client: ClientEntry) => liveKeys(tokens ?? [], client.name);
  const statusFor = (client: ClientEntry) => statusOf(client, keysOf(client), mode, cloudReady);
  const connectedCount = CLIENTS.filter((c) => keysOf(c).some((k) => k.last_used_at)).length;
  const selectedStatus = statusFor(selected);

  return (
    <div className="apps">
      <Card className="apps__list">
        <CardHeader
          title="Apps"
          description={tokens === null ? "Loading…" : `${connectedCount} of ${CLIENTS.length} connected`}
        />
        {tokens === null ? (
          <div className="card__body">
            <LoadingState label="Loading your AI apps…" lines={4} />
          </div>
        ) : (
          <div className="list">
            {CLIENTS.map((client) => {
              const status = statusFor(client);
              const Icon = client.icon;
              return (
                <ListRow
                  key={client.id}
                  onClick={() => select(client.id)}
                  selected={client.id === selectedId}
                  icon={<Icon className="icon" />}
                  title={client.name}
                  description={status.line}
                  trailing={<StatusPill tone={status.tone}>{status.label}</StatusPill>}
                />
              );
            })}
          </div>
        )}
      </Card>

      <div className="apps__detail" ref={detailRef}>
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
      </div>

      <div className="apps__usage">
        <MemoryUseCard />
      </div>
    </div>
  );
}
