/**
 * Settings › Access & sign-in (SPEC-205, issues 570 and 571).
 *
 * Three questions, in this order: where palaia can be reached (Private,
 * Cloud, Public — each with what it means for the person choosing it), who
 * has to sign in to this dashboard, and whether AI apps need an access key.
 * The last two used to be one switch labelled "Require sign-in" that in fact
 * controlled AI apps' access keys (`auth_enabled`) while the dashboard's own
 * sign-in (`dashboard.require_sign_in`) had no control at all; they are two
 * rows now, each saying what it changes.
 *
 * Every change is written to config.yaml and applies after a restart; the
 * page says so and offers the restart where palaia can do it itself.
 * Deliberately dashboard-only — no MCP App surface (principles.md §4:
 * access and sign-in change the attack surface).
 */
import { type ReactNode, useEffect, useState } from "react";
import { Link } from "react-router-dom";

import { Button } from "../components/Button";
import { Card, CardHeader } from "../components/Card";
import { Callout } from "../components/Callout";
import { ConfirmDialog } from "../components/Dialog";
import { Disclosure } from "../components/Disclosure";
import { ErrorState, LoadingState } from "../components/EmptyState";
import { Field, Input, Segmented, Switch } from "../components/Field";
import { ListRow } from "../components/ListRow";
import { PageHeader } from "../components/PageHeader";
import { RestartCallout } from "../components/RestartHub";
import { StatusPill, type StatusTone } from "../components/StatusPill";
import { useToast } from "../components/Toast";
import type {
  ChecklistItem,
  ModeChangeRequest,
  ModeStatus,
  SelfTestResult,
  SetupStatus,
  TunnelGuidance,
} from "../lib/api/client";
import { api } from "../lib/api/client";
import { describeApiError } from "../lib/errors";
import { isHubMode, MODE_LABEL, MODE_OUTCOME, notifyModeChanged, type HubMode } from "../lib/mode";
import { SEARCH_DEBOUNCE_MS, useDebouncedValue } from "../lib/useDebouncedValue";
import { CopyIcon } from "../shell/icons";
import "./settings.css";

const MODES: HubMode[] = ["locked", "cloud", "open"];

/** Whether the dashboard asks for sign-in with this configuration: always in
 * Public, otherwise the explicit setting, otherwise what the mode implies
 * (on in Cloud, off in Private) — `admin_session.sign_in_required`. */
function dashboardSignInWanted(status: ModeStatus): boolean {
  if (status.configured_mode === "open") return true;
  if (status.dashboard_require_sign_in !== null) return status.dashboard_require_sign_in;
  return status.configured_mode === "cloud";
}

/** The self-test's checks, named for the person reading them. */
const CHECK_LABEL: Record<string, string> = {
  discovery: "Sign-in details",
  mcp: "AI connection",
  admin_private: "Admin stays private",
  dashboard_private: "Dashboard stays private",
};

/** The Public-mode checklist's items, in plain words. Unknown items keep the
 * hub's own wording. */
const CHECKLIST_COPY: Record<string, { title: string; detail: string }> = {
  auth_mandatory: {
    title: "AI apps need a key or sign-in",
    detail: "No AI app connects without an access key or signing in.",
  },
  rate_limited: {
    title: "Repeated sign-in attempts are slowed down",
    detail: "Guessing a password or a key gets slower with every attempt.",
  },
  tls: {
    title: "The public address uses https",
    detail: "Run “Check it from the internet” below to confirm.",
  },
  owner_account: {
    title: "The owner account has its own password",
    detail: "Nobody can sign in with a default password.",
  },
};

function copyText(text: string, toast: ReturnType<typeof useToast>, what: string) {
  navigator.clipboard.writeText(text).then(
    () => toast.show(`${what} copied.`),
    () => toast.show("Couldn't copy. Select the text and copy it yourself."),
  );
}

const HEADER = (
  <PageHeader
    title="Access & sign-in"
    description="Who can reach palaia, and who has to sign in."
    back={{ to: "/settings", label: "Settings" }}
  />
);

export function Exposure() {
  const toast = useToast();
  const [status, setStatus] = useState<ModeStatus | null>(null);
  const [setup, setSetup] = useState<SetupStatus | null>(null);
  const [owner, setOwner] = useState<boolean | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    let cancelled = false;
    api
      .mode()
      .then((body) => {
        if (!cancelled) setStatus(body);
      })
      .catch((err: unknown) => {
        // Issue 378: never sit on a loading state, never guess a mode.
        if (!cancelled) setLoadError(describeApiError(err));
      });
    api
      .setupStatus()
      .then((body) => {
        if (!cancelled) setSetup(body);
      })
      .catch(() => {
        // Restart support is a convenience; without it the page names the command.
      });
    api
      .ownerAccount()
      .then((body) => {
        if (!cancelled) setOwner(body.configured);
      })
      .catch(() => {
        if (!cancelled) setOwner(null);
      });
    return () => {
      cancelled = true;
    };
  }, [attempt]);

  /** Write one change; the hub answers with the new status, or why not. */
  async function change(body: ModeChangeRequest, done: string): Promise<string | null> {
    try {
      const next = await api.changeMode(body);
      setStatus(next);
      if (isHubMode(next.active_mode)) notifyModeChanged(next.active_mode);
      api
        .setupStatus()
        .then(setSetup)
        .catch(() => {});
      toast.show(next.restart_required ? `${done} Restart palaia to apply it.` : done);
      return null;
    } catch (err) {
      return describeApiError(err);
    }
  }

  if (!status) {
    return (
      <div className="stack narrow">
        {HEADER}
        {loadError ? (
          <ErrorState
            title="Couldn't load how palaia is reached"
            details={loadError}
            onRetry={() => {
              setLoadError(null);
              setAttempt((n) => n + 1);
            }}
          >
            palaia didn't answer. It may be restarting.
          </ErrorState>
        ) : (
          <LoadingState label="Loading how palaia is reached…" />
        )}
      </div>
    );
  }

  const configured = (isHubMode(status.configured_mode) ? status.configured_mode : "locked") as HubMode;
  const dashboardOn = dashboardSignInWanted(status);

  return (
    <div className="stack narrow">
      {HEADER}

      <Card>
        <div className="settings-summary" data-testid="access-summary">
          <div className="settings-summary__main">
            <p className="settings-summary__title">{MODE_LABEL[configured]}</p>
            <p className="t-sm t-muted">{MODE_OUTCOME[configured]}</p>
            <div className="settings-summary__pills">
              <StatusPill tone={dashboardOn ? "ok" : "neutral"}>
                {dashboardOn ? "Dashboard sign-in on" : "Dashboard sign-in off"}
              </StatusPill>
              <StatusPill tone={status.auth_enabled ? "ok" : "warn"}>
                {status.auth_enabled ? "AI apps need an access key" : "AI apps connect without a key"}
              </StatusPill>
            </div>
          </div>
        </div>
      </Card>

      {status.restart_required ? (
        <RestartCallout supported={setup?.restart_supported ?? false}>
          <p>Your changes are saved. palaia uses them after a restart.</p>
        </RestartCallout>
      ) : null}

      <ModeCard status={status} setup={setup} onChange={change} />

      <SignInCard status={status} owner={owner} onChange={change} />
    </div>
  );
}

type ChangeFn = (body: ModeChangeRequest, done: string) => Promise<string | null>;

function ModeCard({
  status,
  setup,
  onChange,
}: {
  status: ModeStatus;
  setup: SetupStatus | null;
  onChange: ChangeFn;
}) {
  const configured = (isHubMode(status.configured_mode) ? status.configured_mode : "locked") as HubMode;
  const [draft, setDraft] = useState<HubMode>(configured);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [confirmPrivate, setConfirmPrivate] = useState(false);

  async function apply(body: ModeChangeRequest, done: string) {
    setBusy(true);
    setError(null);
    const problem = await onChange(body, done);
    setBusy(false);
    if (problem) setError(problem);
  }

  return (
    <Card>
      <CardHeader
        title="Where palaia can be reached"
        description="Choose where your AI apps connect from. You can change this any time."
      />
      <div className="settings-body">
        <div className="mode-choice radiocards" role="radiogroup" aria-label="Access mode">
          {MODES.map((mode) => (
            <button
              key={mode}
              type="button"
              role="radio"
              aria-checked={draft === mode}
              className={["radiocard", draft === mode ? "radiocard--on" : ""].filter(Boolean).join(" ")}
              onClick={() => {
                setDraft(mode);
                setError(null);
              }}
            >
              <span className="radiocard__pick" aria-hidden="true" />
              <span>
                <span className="radiocard__name">{MODE_LABEL[mode]}</span>
                <span className="radiocard__when">
                  {MODE_OUTCOME[mode]}
                </span>
                {mode === configured ? (
                  <span className="mode-choice__current">
                    <StatusPill tone="ok">Current</StatusPill>
                  </span>
                ) : null}
              </span>
            </button>
          ))}
        </div>

        {error ? (
          <Callout tone="error" title="palaia didn't save this" role="alert">
            {error}
          </Callout>
        ) : null}

        {draft === "locked" && configured !== "locked" ? (
          <div className="row row--wrap">
            <Button variant="primary" loading={busy} onClick={() => setConfirmPrivate(true)}>
              {busy ? "Saving…" : "Switch to Private"}
            </Button>
          </div>
        ) : null}

        {draft === "cloud" || draft === "open" ? (
          <PublicAddressSetup
            mode={draft}
            status={status}
            setup={setup}
            busy={busy}
            onApply={(address, tunnel) =>
              void apply(
                {
                  mode: draft,
                  oauth_enabled: true,
                  oauth_issuer: address,
                  public_url: address,
                  ...(tunnel ? { tunnel } : {}),
                },
                draft === "cloud" ? "Cloud access saved." : "Public access saved.",
              )
            }
          />
        ) : null}
      </div>
      <ConfirmDialog
        open={confirmPrivate}
        onCancel={() => setConfirmPrivate(false)}
        onConfirm={() => {
          setConfirmPrivate(false);
          void apply({ mode: "locked" }, "Private access saved.");
        }}
        title="Switch to Private?"
        confirmLabel="Switch to Private"
      >
        <p>
          Only devices on your network or VPN can reach palaia afterwards. claude.ai, ChatGPT and
          other apps that connect from the internet stop working.
        </p>
      </ConfirmDialog>
    </Card>
  );
}

/** The host part of a valid https address, for the tunnel commands. */
function hostnameOf(address: string, invalid: string | undefined): string {
  if (!address || invalid) return "";
  try {
    return new URL(address).hostname;
  } catch {
    return "";
  }
}

function PublicAddressSetup({
  mode,
  status,
  setup,
  busy,
  onApply,
}: {
  mode: "cloud" | "open";
  status: ModeStatus;
  setup: SetupStatus | null;
  busy: boolean;
  onApply: (address: string, tunnel: "tailscale" | "cloudflared" | "reverse_proxy" | undefined) => void;
}) {
  const configuredHere = status.configured_mode === mode;
  const [address, setAddress] = useState(status.public_url ?? setup?.cloud_url_hint ?? "");
  const [kind, setKind] = useState<"tailscale" | "cloudflared" | "reverse_proxy">(
    status.tunnel === "cloudflared" || status.tunnel === "reverse_proxy" ? status.tunnel : "tailscale",
  );
  const [acknowledged, setAcknowledged] = useState(false);

  const trimmed = address.trim().replace(/\/+$/, "");
  const addressError =
    trimmed && !/^https:\/\/[^/\s]+$/.test(trimmed)
      ? "Use the full https:// address, without a path."
      : undefined;
  const ready = Boolean(trimmed) && !addressError && (mode === "cloud" || acknowledged);
  const unchanged =
    configuredHere && trimmed === (status.public_url ?? "").replace(/\/+$/, "") && status.oauth_enabled;

  const hostname = hostnameOf(trimmed, addressError);

  return (
    <div className="stack stack--4" data-testid={`setup-${mode}`}>
      <div className="stack stack--1">
        <p className="t-strong">
          {mode === "cloud" ? "Set up a public address" : "Set up a public address for everything"}
        </p>
        <p className="t-sm t-muted">
          {mode === "cloud"
            ? "AI apps on the internet connect to palaia at a secure https address. That address leads only to palaia's AI connection; this dashboard stays on your private network. Each app signs in with your owner account."
            : "The address leads to all of palaia, this dashboard included. Everyone who opens it has to sign in with the owner account."}
        </p>
      </div>

      <Field
        label="Public address"
        hint={
          setup?.cloud_url_hint && trimmed === setup.cloud_url_hint.replace(/\/+$/, "")
            ? "Set up during installation."
            : "The https address your tunnel or proxy gives palaia."
        }
        error={addressError}
      >
        <Input
          value={address}
          onChange={(event) => setAddress(event.target.value)}
          placeholder="https://palaia.your-tailnet.ts.net"
          inputMode="url"
          autoComplete="off"
          invalid={Boolean(addressError)}
        />
      </Field>

      <Disclosure summary="I don't have a public address yet">
        <TunnelGuide mode={mode} kind={kind} onKind={setKind} hostname={hostname} />
      </Disclosure>

      {mode === "open" ? (
        <>
          <ChecklistBlock />
          <label className="checkrow">
            <input
              type="checkbox"
              checked={acknowledged}
              onChange={(event) => setAcknowledged(event.target.checked)}
            />
            <span className="t-sm">
              I understand that this dashboard, my memories and the access keys can be reached
              from the internet, behind the owner sign-in.
            </span>
          </label>
        </>
      ) : null}

      <div className="row row--wrap">
        <Button
          variant="primary"
          loading={busy}
          disabled={!ready || unchanged}
          onClick={() => onApply(trimmed, kind)}
        >
          {busy
            ? "Saving…"
            : unchanged
              ? mode === "cloud"
                ? "Cloud is set up"
                : "Public is set up"
              : mode === "cloud"
                ? "Switch to Cloud"
                : "Switch to Public"}
        </Button>
        <span className="t-sm t-muted">palaia restarts once to apply it.</span>
      </div>

      {configuredHere && status.public_url ? <SelfTest address={status.public_url} /> : null}
    </div>
  );
}

function TunnelGuide({
  mode,
  kind,
  onKind,
  hostname,
}: {
  mode: "cloud" | "open";
  kind: "tailscale" | "cloudflared" | "reverse_proxy";
  onKind: (kind: "tailscale" | "cloudflared" | "reverse_proxy") => void;
  hostname: string;
}) {
  const toast = useToast();
  const [guidance, setGuidance] = useState<TunnelGuidance | null>(null);
  // Issue 384: one request per pause in typing, the previous one aborted.
  const debouncedHostname = useDebouncedValue(hostname, SEARCH_DEBOUNCE_MS);
  useEffect(() => {
    if (kind === "reverse_proxy") return;
    const controller = new AbortController();
    api
      .tunnelGuidance({ kind, hostname: debouncedHostname || undefined }, controller.signal)
      .then((body) => {
        if (!controller.signal.aborted) setGuidance(body);
      })
      .catch(() => {
        // No answer: no commands rather than stale or made-up ones.
      });
    return () => controller.abort();
  }, [kind, debouncedHostname, mode]);

  return (
    <div className="stack stack--3">
      <Segmented
        ariaLabel="How the public address is made"
        value={kind}
        onChange={onKind}
        options={[
          { value: "tailscale", label: "Tailscale" },
          { value: "cloudflared", label: "Cloudflare Tunnel" },
          { value: "reverse_proxy", label: "My own proxy" },
        ]}
      />
      {kind === "reverse_proxy" ? (
        <p>
          Point your proxy at port {mode === "cloud" ? "8422" : "8420"} on the server palaia runs
          on, with an https address in front. Then enter that address above.
        </p>
      ) : guidance ? (
        <>
          <div className="command-list">
            <span className="command-list__label">Run this on the server palaia runs on:</span>
            {guidance.commands.map((command) => (
              <div className="snippet" key={command}>
                <code>{command}</code>
                {command.startsWith("#") ? null : (
                  <Button size="sm" onClick={() => copyText(command, toast, "Command")}>
                    <CopyIcon className="icon" />
                    Copy
                  </Button>
                )}
              </div>
            ))}
          </div>
          <p>{guidance.note}</p>
          {guidance.config ? (
            <Disclosure summary="Show configuration">
              <div className="snippet snippet--block">
                <code>{guidance.config}</code>
              </div>
              <div>
                <Button size="sm" onClick={() => copyText(guidance.config, toast, "Configuration")}>
                  <CopyIcon className="icon" />
                  Copy configuration
                </Button>
              </div>
            </Disclosure>
          ) : null}
        </>
      ) : null}
    </div>
  );
}

function SelfTest({ address }: { address: string }) {
  const [result, setResult] = useState<SelfTestResult | null>(null);
  const [testing, setTesting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function run() {
    setTesting(true);
    setResult(null);
    setError(null);
    try {
      setResult(await api.selfTest(address));
    } catch (err) {
      // The check itself could not run — never a made-up "unreachable".
      setError(describeApiError(err));
    } finally {
      setTesting(false);
    }
  }

  return (
    <div className="stack stack--3" data-testid="self-test">
      <div className="row row--wrap">
        <Button onClick={() => void run()} loading={testing}>
          {testing ? "Checking…" : "Check it from the internet"}
        </Button>
        {result ? (
          <StatusPill tone={result.reachable ? "ok" : "error"}>
            {result.reachable ? "Works" : "Doesn't work yet"}
          </StatusPill>
        ) : null}
      </div>
      {error ? <p className="field__error">{error}</p> : null}
      {result ? (
        result.checks.length > 0 ? (
          <ul className="check-list">
            {result.checks.map((check) => (
              <li className="check-list__item" key={check.id}>
                <StatusPill tone={check.passed ? "ok" : "error"}>
                  {check.passed ? "Passed" : "Failed"}
                </StatusPill>
                <span className="check-list__text">
                  <span className="check-list__title">{CHECK_LABEL[check.id] ?? check.id}</span>
                  <span className="check-list__detail">{check.detail}</span>
                </span>
              </li>
            ))}
          </ul>
        ) : result.reachable ? null : (
          <p className="t-sm t-muted">{result.error}</p>
        )
      ) : null}
    </div>
  );
}

function ChecklistBlock() {
  const [items, setItems] = useState<ChecklistItem[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    let cancelled = false;
    api
      .exposure()
      .then((body) => {
        if (!cancelled) setItems(body.checklist);
      })
      .catch((err: unknown) => {
        if (!cancelled) setError(describeApiError(err));
      });
    return () => {
      cancelled = true;
    };
  }, [attempt]);

  const shown = (items ?? []).filter((item) => item.id !== "dashboard_exposure_acknowledged");

  return (
    <div className="stack stack--2" data-testid="public-checklist">
      <p className="t-strong">Before the dashboard goes on the internet</p>
      {error && !items ? (
        <ErrorState
          title="Couldn't run the checks"
          details={error}
          onRetry={() => {
            setError(null);
            setAttempt((n) => n + 1);
          }}
        />
      ) : items === null ? (
        <LoadingState label="Checking…" lines={2} />
      ) : (
        <ul className="check-list">
          {shown.map((item) => {
            const copy = CHECKLIST_COPY[item.id] ?? { title: item.title, detail: item.detail };
            const tone: StatusTone = !item.auto ? "neutral" : item.passed ? "ok" : "error";
            const word = !item.auto ? "Check yourself" : item.passed ? "Done" : "Not yet";
            return (
              <li className="check-list__item" key={item.id}>
                <StatusPill tone={tone}>{word}</StatusPill>
                <span className="check-list__text">
                  <span className="check-list__title">{copy.title}</span>
                  <span className="check-list__detail">{copy.detail}</span>
                </span>
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}

function SignInCard({
  status,
  owner,
  onChange,
}: {
  status: ModeStatus;
  owner: boolean | null;
  onChange: ChangeFn;
}) {
  const [busy, setBusy] = useState<"keys" | "dashboard" | null>(null);
  const [error, setError] = useState<{ row: "keys" | "dashboard"; text: string } | null>(null);
  const [confirmKeysOff, setConfirmKeysOff] = useState(false);

  const isPublic = status.configured_mode === "open";
  const dashboardOn = dashboardSignInWanted(status);
  // Turning the dashboard's sign-in on needs an owner account to sign in
  // with; without one the gate would stay open (admin_session.py).
  const needsOwner = !dashboardOn && owner === false;

  async function run(row: "keys" | "dashboard", body: ModeChangeRequest, done: string) {
    setBusy(row);
    setError(null);
    const problem = await onChange(body, done);
    setBusy(null);
    if (problem) setError({ row, text: problem });
  }

  function setDashboard(on: boolean) {
    const body: ModeChangeRequest = { dashboard_require_sign_in: on };
    if (on && !status.oauth_enabled) {
      // The sign-in page is served by palaia's sign-in server; switch it on
      // for this dashboard's own address (the same call setup makes).
      body.oauth_enabled = true;
      body.oauth_issuer = status.oauth_issuer ?? window.location.origin;
    }
    void run(
      "dashboard",
      body,
      on ? "Dashboard sign-in turned on." : "Dashboard sign-in turned off.",
    );
  }

  let keysNote: ReactNode = null;
  if (error?.row === "keys") {
    keysNote = <p className="field__error">{error.text}</p>;
  }
  let dashboardNote: ReactNode = null;
  if (error?.row === "dashboard") {
    dashboardNote = <p className="field__error">{error.text}</p>;
  } else if (needsOwner) {
    dashboardNote = (
      <Callout
        tone="info"
        title="Create the owner account first"
        actions={
          <Link className="btn btn--sm" to="/onboarding">
            Continue setup
          </Link>
        }
      >
        The dashboard asks for this account's password once sign-in is on.
      </Callout>
    );
  }

  return (
    <Card>
      <CardHeader title="Sign-in" />
      <ListRow
        setting
        labelId="row-dashboard-sign-in"
        title="Require sign-in for this dashboard"
        description={
          isPublic
            ? "Always on in Public mode."
            : dashboardOn
              ? "Anyone who opens the dashboard signs in with the owner account."
              : "Anyone who can open this address can use the dashboard."
        }
        trailing={
          <Switch
            checked={dashboardOn}
            onChange={setDashboard}
            disabled={isPublic || needsOwner || busy !== null}
            labelledBy="row-dashboard-sign-in"
          />
        }
      />
      {dashboardNote ? <div className="setting-note">{dashboardNote}</div> : null}
      <ListRow
        setting
        labelId="row-access-keys"
        title="AI apps need an access key"
        description={
          status.auth_enabled
            ? "Each AI app connects with its own key, which you can revoke."
            : status.oauth_enabled
              ? "Access keys don't work; AI apps connect only by signing in."
              : "Any AI app on your network can read and change your memories."
        }
        trailing={
          <Switch
            checked={status.auth_enabled}
            onChange={(on) => {
              if (on) {
                void run("keys", { auth_enabled: true }, "Access keys turned on.");
              } else {
                setConfirmKeysOff(true);
              }
            }}
            disabled={busy !== null}
            labelledBy="row-access-keys"
          />
        }
      />
      {keysNote ? <div className="setting-note">{keysNote}</div> : null}
      <ListRow
        title="Owner account"
        description={
          owner === null
            ? "palaia couldn't say whether it exists."
            : owner
              ? "Set up. It is the account you sign in to this dashboard with."
              : "Not set up yet."
        }
        trailing={
          owner === false ? (
            <Link className="btn btn--sm" to="/onboarding">
              Set up
            </Link>
          ) : owner ? (
            <StatusPill tone="ok">Set up</StatusPill>
          ) : null
        }
      />
      <ConfirmDialog
        open={confirmKeysOff}
        onCancel={() => setConfirmKeysOff(false)}
        onConfirm={() => {
          setConfirmKeysOff(false);
          void run("keys", { auth_enabled: false }, "Access keys turned off.");
        }}
        title="Let AI apps connect without an access key?"
        confirmLabel="Turn off access keys"
        destructive
      >
        <p>
          {status.oauth_enabled
            ? "The access keys you created stop working. AI apps can then only connect by signing in to palaia."
            : "Anyone on your network could read and change your memories. The access keys you created stop being checked."}
        </p>
      </ConfirmDialog>
    </Card>
  );
}
