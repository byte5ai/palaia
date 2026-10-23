/**
 * Settings › About & updates: which palaia this is, whether a newer one
 * exists and how to get it, and how the owner signs in to this dashboard
 * (SPEC-204 #4: in words a non-developer reads, "Sign in with GitHub",
 * never a protocol name).
 */
import { useEffect, useState } from "react";

import {
  Card,
  CardHeader,
  ErrorState,
  ListRow,
  LoadingState,
  PageHeader,
  StatusPill,
} from "../../components";
import type { InfoResponse, SignInInfo, UpdateCheckResponse } from "../../lib/api/client";
import { api } from "../../lib/api/client";
import { docsUrl } from "../../lib/docs";
import { __version__ } from "../../version";

function signInSummary(signIn: SignInInfo): { label: string; detail: string } {
  if (signIn.method === "idp" && signIn.provider_name) {
    return {
      label: `Sign in with ${signIn.provider_name}`,
      detail: "The owner account signs in through this provider, set up on the server.",
    };
  }
  if (signIn.method === "password") {
    return {
      label: "Sign in with a password",
      detail: "The owner account signs in with a username and password.",
    };
  }
  return {
    label: "No sign-in configured",
    detail: "No owner account can sign in yet. Create one in setup.",
  };
}

function updateLine(check: UpdateCheckResponse): { tone: "ok" | "info" | "neutral"; label: string } {
  if (check.state === "update_available") return { tone: "info", label: "Update available" };
  if (check.state === "up_to_date") return { tone: "ok", label: "Up to date" };
  return { tone: "neutral", label: "Couldn't check" };
}

const HEADER = <PageHeader title="About & updates" back={{ to: "/settings", label: "Settings" }} />;

export function About() {
  const [info, setInfo] = useState<InfoResponse | null | undefined>(undefined);
  const [check, setCheck] = useState<UpdateCheckResponse | null | undefined>(undefined);
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    let cancelled = false;
    api
      .info()
      .then((value) => {
        if (!cancelled) setInfo(value);
      })
      .catch(() => {
        if (!cancelled) setInfo(null);
      });
    api
      .updateCheck()
      .then((value) => {
        if (!cancelled) setCheck(value);
      })
      .catch(() => {
        if (!cancelled) setCheck(null);
      });
    return () => {
      cancelled = true;
    };
  }, [attempt]);

  if (info === undefined) {
    return (
      <div className="stack narrow">
        {HEADER}
        <LoadingState label="Loading…" />
      </div>
    );
  }
  if (info === null) {
    return (
      <div className="stack narrow">
        {HEADER}
        <ErrorState title="Couldn't load palaia's details" onRetry={() => setAttempt((n) => n + 1)}>
          palaia didn't answer. It may be restarting.
        </ErrorState>
      </div>
    );
  }

  const signIn = (info as { sign_in?: SignInInfo }).sign_in ?? null;
  const version = typeof info.version === "string" ? info.version : __version__;
  const channel = typeof info.channel === "string" ? info.channel : null;
  const update = check ? updateLine(check) : null;

  return (
    <div className="stack narrow">
      {HEADER}
      <Card>
        <CardHeader
          title="Version"
          actions={update ? <StatusPill tone={update.tone}>{update.label}</StatusPill> : undefined}
        />
        <ListRow
          title={`palaia ${version}`}
          description={channel ? `Release channel: ${channel}` : undefined}
        />
        {check?.state === "update_available" ? (
          <div className="card__body stack stack--3">
            <p>
              Version {check.latest_version} is available. {check.guidance.message}
            </p>
            {check.guidance.commands.length > 0 ? (
              <pre className="snippet snippet--block">
                <code>{check.guidance.commands.join("\n")}</code>
              </pre>
            ) : null}
          </div>
        ) : null}
        <div className="card__foot">
          <a href={docsUrl("/")} target="_blank" rel="noreferrer">
            Documentation
          </a>
        </div>
      </Card>

      <Card>
        <CardHeader
          title="Dashboard sign-in"
          actions={
            signIn ? (
              <StatusPill tone={signIn.method === "none" ? "warn" : "ok"}>
                {signIn.method === "none" ? "Not set up" : "Set up"}
              </StatusPill>
            ) : undefined
          }
        />
        {signIn ? (
          <ListRow
            title={signInSummary(signIn).label}
            description={
              <>
                {signInSummary(signIn).detail}{" "}
                {signIn.required
                  ? "This dashboard asks you to sign in."
                  : "This dashboard doesn't ask anyone to sign in."}
              </>
            }
          />
        ) : (
          <ListRow title="No sign-in configured" description="No owner account can sign in yet." />
        )}
      </Card>
    </div>
  );
}
