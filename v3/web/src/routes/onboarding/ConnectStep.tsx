/**
 * Connect an AI app (issue 565): the apps the owner actually uses, by the
 * goal they chose — ChatGPT and the Claude app (Mac, Windows, phones and
 * claude.ai share custom connectors) through cloud access, and apps on
 * their own computers (the Claude Desktop extension, Claude Code, Codex …)
 * over the private network. A cloud connector is offered as ready only once
 * cloud access works; before that it says what is missing, and choosing it
 * never quietly turns into a different app.
 */
import { useState } from "react";

import { Button } from "../../components/Button";
import { Card, CardBody } from "../../components/Card";
import { ConnectPanel } from "../../components/ConnectPanel";
import { StatusPill } from "../../components/StatusPill";
import { StepperPanel } from "../../components/Stepper";
import type { SetupStatus } from "../../lib/api/client";
import { api } from "../../lib/api/client";
import {
  type DownloadClient,
  type GuidedClient,
  type NotYetClient,
  wizardClients,
} from "../../lib/clients";
import { saveBlob } from "../../lib/download";
import { describeApiError } from "../../lib/errors";
import { ArrowRightIcon, CopyIcon } from "../../shell/icons";
import { goalOf } from "./steps";

type Pick = NotYetClient | GuidedClient | DownloadClient;

const CONNECT_STEPS: Record<string, string[]> = {
  "claude-ai": [
    "In the Claude app or on claude.ai, open Settings → Connectors.",
    "Choose Add custom connector, name it palaia and paste the address.",
    "Click Connect, sign in with your palaia account and allow access.",
  ],
  chatgpt: [
    "In ChatGPT, turn on developer mode in the connector settings.",
    "Create a connector named palaia with this address; choose OAuth sign-in.",
    "Sign in with your palaia account and allow access.",
  ],
};

export function ConnectStep({
  status,
  onDone,
  onWantCloud,
}: {
  status: SetupStatus;
  onDone: () => Promise<void>;
  onWantCloud: () => Promise<void>;
}) {
  const goal = goalOf(status);
  const { cloud, local } = wizardClients();
  const ordered: Pick[] =
    goal === "cloud" ? [...cloud, ...local] : [...local, ...cloud];
  const [picked, setPicked] = useState<string>(ordered[0]!.id);
  const client = ordered.find((c) => c.id === picked) ?? ordered[0]!;
  const profile = status.profiles.includes("default")
    ? "default"
    : (status.profiles[0] ?? "default");

  async function skip() {
    await api.updateSetup({ skipped: [...status.skipped, "client"] });
    await onDone();
  }

  return (
    <StepperPanel
      title="Connect your AI app"
      description="Pick the app you use most. You can add more later."
      back={
        <Button variant="secondary" onClick={() => void skip()}>
          Later
        </Button>
      }
      primary={
        <Button variant="primary" size="lg" onClick={() => void onDone()}>
          {status.client_connected ? "Continue" : "Finish"}
          <ArrowRightIcon className="icon--sm" />
        </Button>
      }
    >
      <div className="clientgrid" role="radiogroup" aria-label="AI app">
        {ordered.map((item) => {
          const needsCloud = item.kind === "notYet" && !status.cloud_ready;
          return (
            <button
              type="button"
              role="radio"
              aria-checked={item.id === client.id}
              key={item.id}
              className={["clientcard", item.id === client.id ? "clientcard--on" : ""]
                .filter(Boolean)
                .join(" ")}
              onClick={() => setPicked(item.id)}
            >
              <span className="row">
                <item.icon className="icon--sm" />
                <span className="clientcard__name">{item.name}</span>
              </span>
              <span className="t-sm t-muted">
                {item.kind === "notYet"
                  ? needsCloud
                    ? "Needs cloud access"
                    : "Through cloud access"
                  : item.kind === "download"
                    ? "Download the extension"
                    : item.estimate}
              </span>
            </button>
          );
        })}
      </div>

      {client.kind === "notYet" ? (
        <CloudConnector
          client={client}
          status={status}
          profile={profile}
          onWantCloud={onWantCloud}
        />
      ) : client.kind === "download" ? (
        <ExtensionDownload client={client} profile={profile} />
      ) : (
        <ConnectPanel key={client.id} client={client} defaultProfile={profile} />
      )}

      <p className="ob__connected" role="status">
        {status.client_connected ? (
          <>
            <StatusPill tone="ok">Connected</StatusPill>
            palaia received the first request.
          </>
        ) : (
          <>
            <StatusPill tone="info">Waiting</StatusPill>
            Waiting for the first request from your AI app…
          </>
        )}
      </p>
    </StepperPanel>
  );
}

function CloudConnector({
  client,
  status,
  profile,
  onWantCloud,
}: {
  client: NotYetClient;
  status: SetupStatus;
  profile: string;
  onWantCloud: () => Promise<void>;
}) {
  const [copied, setCopied] = useState(false);
  if (!status.cloud_ready || !status.issuer) {
    return (
      <Card>
        <CardBody className="stack stack--3">
          <p>
            {client.name} connects from the internet, so it needs cloud access. Your dashboard
            stays on your private network either way.
          </p>
          <div>
            <Button variant="primary" onClick={() => void onWantCloud()}>
              Turn on cloud access
            </Button>
          </div>
        </CardBody>
      </Card>
    );
  }
  const connect = client.oauthConnect?.(status.issuer, profile);
  if (!connect) return null;
  const steps = CONNECT_STEPS[client.id] ?? [connect.note];
  return (
    <Card>
      <CardBody className="stack stack--3">
        <div className="snippet snippet--wrap">
          <code>{connect.url}</code>
          <Button
            size="sm"
            onClick={() =>
              void navigator.clipboard
                ?.writeText(connect.url)
                .then(() => setCopied(true))
                .catch(() => setCopied(false))
            }
          >
            <CopyIcon className="icon--sm" />
            {copied ? "Copied" : "Copy"}
          </Button>
        </div>
        <ol className="ob__howto">
          {steps.map((line) => (
            <li key={line}>{line}</li>
          ))}
        </ol>
      </CardBody>
    </Card>
  );
}

function ExtensionDownload({
  client,
  profile,
}: {
  client: DownloadClient;
  profile: string;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  async function download() {
    setBusy(true);
    setError(null);
    try {
      const file = await api.downloadFile(client.downloadUrl("", profile));
      saveBlob(file.blob, file.filename ?? "palaia.mcpb");
    } catch (err) {
      setError(describeApiError(err));
    } finally {
      setBusy(false);
    }
  }
  return (
    <Card>
      <CardBody className="stack stack--3">
        <ol className="ob__howto">
          <li>Download the palaia extension for Claude Desktop.</li>
          <li>
            Open the file. Claude Desktop shows palaia's address and a new
            access key.
          </li>
          <li>Click Install.</li>
        </ol>
        <p className="t-sm t-muted">
          For a computer on your private network. For the Claude app on your
          phone, use cloud access with the Claude connector.
        </p>
        <div>
          <Button variant="primary" onClick={() => void download()} loading={busy}>
            {busy ? "Preparing…" : "Download extension"}
          </Button>
        </div>
        {error ? <p className="field__error">{error}</p> : null}
      </CardBody>
    </Card>
  );
}
