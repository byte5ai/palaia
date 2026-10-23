/**
 * Cloud access (issues 561, 566, 567): one public HTTPS address for the
 * AI connection only — palaia's cloud entry — while this dashboard stays on
 * the private network. Three states, all read from the hub:
 *
 * 1. Not turned on: the public address (prefilled when the installer set up
 *    Tailscale Funnel) and one button that writes mode, sign-in and address.
 * 2. Turned on, not active: one restart — done here where the hub can
 *    restart itself. Sign-in follows, then the wizard resumes.
 * 3. Active: the hub checks its own public address the way ChatGPT and
 *    Claude do (the self-test) and shows each result.
 */
import { useEffect, useRef, useState } from "react";

import { Button } from "../../components/Button";
import { Callout } from "../../components/Callout";
import { Disclosure } from "../../components/Disclosure";
import { Field, Input } from "../../components/Field";
import { RestartButton } from "../../components/RestartHub";
import { StatusPill } from "../../components/StatusPill";
import { StepperPanel } from "../../components/Stepper";
import type { SelfTestResult, SetupStatus, TunnelGuidance } from "../../lib/api/client";
import { api } from "../../lib/api/client";
import { describeApiError } from "../../lib/errors";
import { ArrowRightIcon } from "../../shell/icons";
import { RestartByHand } from "./RestartByHand";

const CHECK_LABELS: Record<string, string> = {
  discovery: "Sign-in details",
  mcp: "AI connection",
  admin_private: "Admin stays private",
  dashboard_private: "Dashboard stays private",
};

export function CloudStep({
  status,
  refresh,
  onDone,
}: {
  status: SetupStatus;
  refresh: () => Promise<SetupStatus | null>;
  onDone: () => Promise<void>;
}) {
  const turnedOn = status.configured_mode === "cloud" && status.configured_sign_in;
  const active = status.mode === "cloud" && status.sign_in_active;

  async function skip() {
    await api.updateSetup({ skipped: [...status.skipped, "cloud"] });
    await onDone();
  }

  if (active && !status.restart_required) {
    // Cloud mode is on; the step completes once the self-test passes.
    return <CloudCheck status={status} refresh={refresh} onDone={onDone} />;
  }
  if (turnedOn) return <CloudRestart status={status} />;
  return <CloudTurnOn status={status} refresh={refresh} onSkip={skip} />;
}

function CloudTurnOn({
  status,
  refresh,
  onSkip,
}: {
  status: SetupStatus;
  refresh: () => Promise<SetupStatus | null>;
  onSkip: () => Promise<void>;
}) {
  const hint = status.cloud_url_hint;
  const [address, setAddress] = useState(status.public_url ?? hint ?? "");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [guidance, setGuidance] = useState<TunnelGuidance | null>(null);

  const trimmed = address.trim().replace(/\/+$/, "");
  const addressError =
    trimmed && !/^https:\/\/[^/\s]+$/.test(trimmed)
      ? "Use the https:// address only, without a path."
      : undefined;

  // The commands for "I don't have an address yet"; without them the
  // section still names the port to point a tunnel at.
  useEffect(() => {
    if (hint) return;
    let cancelled = false;
    api
      // For Cloud by name: the hub otherwise answers for the configured
      // mode, which on a hub set to Public is the whole hub.
      .tunnelGuidance({ kind: "tailscale", mode: "cloud" })
      .then((next) => {
        if (!cancelled) setGuidance(next);
      })
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, [hint]);

  async function turnOn() {
    setBusy(true);
    setError(null);
    try {
      await api.changeMode({
        mode: "cloud",
        oauth_enabled: true,
        oauth_issuer: trimmed,
        public_url: trimmed,
        tunnel: hint && trimmed === hint.replace(/\/+$/, "") ? "tailscale" : undefined,
      });
      await refresh();
    } catch (err) {
      setError(describeApiError(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <form
      onSubmit={(event) => {
        event.preventDefault();
        if (trimmed && !addressError && !busy) void turnOn();
      }}
    >
      <StepperPanel
        title="Turn on cloud access"
        description={
          "ChatGPT and Claude connect to palaia over the internet. They reach only palaia's " +
          "AI connection, at a secure web address, and each one signs in with your account. " +
          "This dashboard stays on your private network."
        }
        back={
          <Button variant="secondary" onClick={() => void onSkip()} disabled={busy}>
            Not now
          </Button>
        }
        primary={
          <Button
            type="submit"
            variant="primary"
            size="lg"
            loading={busy}
            disabled={!trimmed || Boolean(addressError)}
          >
            Turn on cloud access
            <ArrowRightIcon className="icon--sm" />
          </Button>
        }
      >
        <div className="stack stack--4">
          <Field
            label="Public address"
            hint={
              hint
                ? "Set up during installation (Tailscale Funnel)."
                : "The https address that leads to palaia's cloud entry on the server."
            }
            error={addressError}
          >
            <Input
              value={address}
              onChange={(e) => setAddress(e.target.value)}
              placeholder="https://palaia-hub.your-tailnet.ts.net"
              inputMode="url"
              autoComplete="off"
              invalid={Boolean(addressError)}
              required
            />
          </Field>
          {!hint ? (
            <Disclosure summary="I don't have an address yet">
                <div className="stack stack--2">
                  <p>
                    Run this once on the server. Tailscale then shows the address (it ends in{" "}
                    <code>.ts.net</code>); if it prints a link first, open it and allow Funnel.
                  </p>
                  {guidance
                    ? guidance.commands.map((command) => (
                        <div className="snippet snippet--wrap" key={command}>
                          <code>{command}</code>
                        </div>
                      ))
                    : null}
                  <p className="t-sm t-muted">
                    Cloudflare Tunnel works too: point it at <code>http://127.0.0.1:8422</code>{" "}
                    on the server.
                  </p>
                </div>
            </Disclosure>
          ) : null}
          <p className="t-sm t-muted">
            palaia then restarts once and asks you to sign in with the account you just created.
          </p>
          {error ? <p className="field__error">{error}</p> : null}
        </div>
      </StepperPanel>
    </form>
  );
}

function CloudRestart({ status }: { status: SetupStatus }) {
  return (
    <StepperPanel
      title="Restart palaia to turn on cloud access"
      description={
        <>
          Cloud access is saved for{" "}
          <strong>{status.configured_issuer ?? status.public_url ?? "your public address"}</strong>.
          After the restart, palaia asks you to sign in, then setup continues here.
        </>
      }
      primary={
        status.restart_supported ? <RestartButton variant="primary" confirm={false} /> : null
      }
    >
      {status.restart_supported ? null : <RestartByHand />}
    </StepperPanel>
  );
}

/** A new public address (Tailscale Funnel, a fresh tunnel) can take a few
 * minutes before it answers. The step keeps checking by itself this often,
 * for this long, before it asks the person to look. */
const RECHECK_EVERY_MS = 10_000;
const RECHECK_FOR_MS = 180_000;

function CloudCheck({
  status,
  refresh,
  onDone,
}: {
  status: SetupStatus;
  refresh: () => Promise<SetupStatus | null>;
  onDone: () => Promise<void>;
}) {
  const [result, setResult] = useState<SelfTestResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  // Each check has a number; `attempt` asks for one, `finished` is the
  // last one that answered, so "checking" needs no state of its own.
  const [attempt, setAttempt] = useState(0);
  const [finished, setFinished] = useState(-1);
  const [autoRecheck, setAutoRecheck] = useState(false);
  const since = useRef(0);
  const address = status.public_url ?? status.issuer ?? "";
  const checking = finished !== attempt;

  function check() {
    since.current = 0;
    setAttempt((n) => n + 1);
  }

  // Checked when the step opens and again every few seconds while the
  // address does not answer yet; "Check again" starts a new round.
  useEffect(() => {
    if (!address) return;
    let cancelled = false;
    let timer = 0;
    if (since.current === 0) since.current = Date.now();
    api
      .selfTest(address)
      .then((next) => {
        if (cancelled) return;
        const again = !next.reachable && Date.now() - since.current < RECHECK_FOR_MS;
        setResult(next);
        setError(null);
        setAutoRecheck(again);
        setFinished(attempt);
        void refresh();
        if (again) timer = window.setTimeout(() => setAttempt((n) => n + 1), RECHECK_EVERY_MS);
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        setError(describeApiError(err));
        setAutoRecheck(false);
        setFinished(attempt);
      });
    return () => {
      cancelled = true;
      window.clearTimeout(timer);
    };
  }, [address, refresh, attempt]);

  const works = Boolean(result?.reachable);
  return (
    <StepperPanel
      title={works ? "Cloud access works" : "Checking cloud access"}
      description={
        <>
          palaia checks its public address <strong>{address}</strong> the way ChatGPT and Claude
          reach it.
        </>
      }
      back={
        <Button variant="secondary" onClick={check} loading={checking}>
          {checking ? "Checking…" : "Check again"}
        </Button>
      }
      primary={
        <Button variant="primary" size="lg" onClick={() => void onDone()} disabled={!works}>
          Continue
          <ArrowRightIcon className="icon--sm" />
        </Button>
      }
    >
      <ul className="ob__checks" aria-busy={checking && !result ? "true" : undefined}>
        {(result?.checks ?? []).map((item) => (
          <li key={item.id}>
            <span className="grow">
              <span className="ob__check-name">{CHECK_LABELS[item.id] ?? item.id}</span>
              <span className="t-sm t-muted">{item.detail}</span>
            </span>
            <StatusPill tone={item.passed ? "ok" : "warn"}>
              {item.passed ? "Passed" : "Not yet"}
            </StatusPill>
          </li>
        ))}
        {checking && !result ? <li className="t-muted">Checking…</li> : null}
      </ul>
      {result && !works && autoRecheck ? (
        <Callout tone="info" title="Not reachable yet" role="status">
          <p>
            A new address can take a few minutes to work. palaia checks again by itself every few
            seconds.
          </p>
        </Callout>
      ) : null}
      {result && !works && !autoRecheck ? (
        <Callout tone="warn" title="Not working yet" role="status">
          <p>{result.error}</p>
        </Callout>
      ) : null}
      {error ? <p className="field__error">{error}</p> : null}
    </StepperPanel>
  );
}
