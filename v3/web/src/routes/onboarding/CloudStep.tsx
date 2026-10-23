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
import { useEffect, useState } from "react";

import { Field, Input } from "../../components/Field";
import type {
  SelfTestResult,
  SetupStatus,
  TunnelGuidance,
} from "../../lib/api/client";
import { api } from "../../lib/api/client";
import { describeApiError } from "../../lib/errors";
import { waitForRestart } from "../../lib/setup";
import { ArrowRightIcon, CheckIcon, WarningIcon } from "../../shell/icons";
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
  const turnedOn =
    status.configured_mode === "cloud" && status.configured_sign_in;
  const active = status.mode === "cloud" && status.sign_in_active;

  async function skip() {
    await api.updateSetup({ skipped: [...status.skipped, "cloud"] });
    await onDone();
  }

  if (active && !status.restart_required) {
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

  async function showGuidance() {
    try {
      setGuidance(await api.tunnelGuidance({ kind: "tailscale" }));
    } catch (err) {
      setError(describeApiError(err));
    }
  }

  async function turnOn() {
    setBusy(true);
    setError(null);
    try {
      await api.changeMode({
        mode: "cloud",
        oauth_enabled: true,
        oauth_issuer: trimmed,
        public_url: trimmed,
        tunnel:
          hint && trimmed === hint.replace(/\/+$/, "")
            ? "tailscale"
            : undefined,
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
      className="ob__step-body"
      onSubmit={(event) => {
        event.preventDefault();
        if (trimmed && !addressError && !busy) void turnOn();
      }}
    >
      <h1 className="ob__title">Turn on cloud access</h1>
      <p className="t-lead">
        ChatGPT and Claude connect to palaia over the internet. They reach only
        palaia's AI connection, at a secure web address, and each one signs in
        with your account. This dashboard stays on your private network.
      </p>
      <div className="card">
        <div className="card__body stack stack--3">
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
              required
            />
          </Field>
          {!hint ? (
            <details
              className="ob__more"
              onToggle={() => void (guidance ? null : showGuidance())}
            >
              <summary>I don't have an address yet</summary>
              <div className="stack stack--2">
                <p className="t-sm">
                  Run this once on the server. Tailscale then shows the address
                  (it ends in
                  <code> .ts.net</code>); if it prints a link first, open it and
                  allow Funnel.
                </p>
                {guidance
                  ? guidance.commands.map((command) => (
                      <div className="snippet" key={command}>
                        <code>{command}</code>
                      </div>
                    ))
                  : null}
                <p className="t-xs t-muted">
                  Cloudflare Tunnel works too: point it at{" "}
                  <code>http://127.0.0.1:8422</code> on the server.
                </p>
              </div>
            </details>
          ) : null}
        </div>
      </div>
      <p className="t-sm t-muted">
        palaia then restarts once and asks you to sign in with the account you
        just created.
      </p>
      {error ? <p className="field__error">{error}</p> : null}
      <div className="ob__foot">
        <button
          type="button"
          className="btn"
          onClick={() => void onSkip()}
          disabled={busy}
        >
          Not now
        </button>
        <button
          type="submit"
          className="btn btn--primary btn--lg"
          disabled={busy || !trimmed || Boolean(addressError)}
        >
          {busy ? "Turning on…" : "Turn on cloud access"}
          <ArrowRightIcon className="icon--sm" />
        </button>
      </div>
    </form>
  );
}

function CloudRestart({ status }: { status: SetupStatus }) {
  const [restarting, setRestarting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function restart() {
    setRestarting(true);
    setError(null);
    try {
      await api.restartHub();
      const back = await waitForRestart();
      if (!back) {
        setError(
          "palaia did not come back within two minutes. Check the server, then reload.",
        );
        setRestarting(false);
        return;
      }
      // The dashboard now asks for the account; the sign-in page brings the
      // browser back here.
      window.location.reload();
    } catch (err) {
      setError(describeApiError(err));
      setRestarting(false);
    }
  }

  return (
    <section className="ob__step-body">
      <h1 className="ob__title">Restart palaia to turn on cloud access</h1>
      <p className="t-lead">
        Cloud access is saved for{" "}
        <strong>
          {status.configured_issuer ??
            status.public_url ??
            "your public address"}
        </strong>
        . After the restart, palaia asks you to sign in, then setup continues
        here.
      </p>
      {status.restart_supported ? (
        <div className="ob__foot">
          <button
            type="button"
            className="btn btn--primary btn--lg"
            onClick={() => void restart()}
            disabled={restarting}
          >
            {restarting ? "Restarting palaia…" : "Restart palaia"}
          </button>
        </div>
      ) : (
        <RestartByHand />
      )}
      {error ? <p className="field__error">{error}</p> : null}
    </section>
  );
}

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
  const [rechecking, setRechecking] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const address = status.public_url ?? status.issuer ?? "";
  const checking = rechecking || (result === null && error === null);

  async function check() {
    setRechecking(true);
    setError(null);
    try {
      setResult(await api.selfTest(address));
      await refresh();
    } catch (err) {
      setError(describeApiError(err));
    } finally {
      setRechecking(false);
    }
  }

  // Checked once when the step opens; "Check again" repeats it.
  useEffect(() => {
    if (!address) return;
    let cancelled = false;
    api
      .selfTest(address)
      .then((next) => {
        if (cancelled) return;
        setResult(next);
        void refresh();
      })
      .catch((err: unknown) => {
        if (!cancelled) setError(describeApiError(err));
      });
    return () => {
      cancelled = true;
    };
  }, [address, refresh]);

  const works = Boolean(result?.reachable);
  return (
    <section className="ob__step-body">
      <h1 className="ob__title">
        {works ? "Cloud access works" : "Checking cloud access"}
      </h1>
      <p className="t-lead">
        palaia checks its public address <strong>{address}</strong> the way
        ChatGPT and Claude reach it.
      </p>
      <ul className="ob__checks">
        {(result?.checks ?? []).map((item) => (
          <li
            key={item.id}
            className={item.passed ? "ob__check--ok" : "ob__check--fail"}
          >
            {item.passed ? (
              <CheckIcon className="icon icon--sm" />
            ) : (
              <WarningIcon className="icon icon--sm" />
            )}
            <span>
              <strong>{CHECK_LABELS[item.id] ?? item.id}</strong>
              <span className="t-sm t-muted"> — {item.detail}</span>
            </span>
          </li>
        ))}
        {checking && !result ? <li className="t-muted">Checking…</li> : null}
      </ul>
      {result && !works ? (
        <div className="banner banner--warn" role="status">
          <WarningIcon className="icon icon--sm" />
          <div>
            <p className="banner__title">Not working yet</p>
            <p className="t-sm t-muted">{result.error}</p>
          </div>
        </div>
      ) : null}
      {error ? <p className="field__error">{error}</p> : null}
      <div className="ob__foot">
        <button
          type="button"
          className="btn"
          onClick={() => void check()}
          disabled={checking}
        >
          {checking ? "Checking…" : "Check again"}
        </button>
        <button
          type="button"
          className="btn btn--primary btn--lg"
          onClick={() => void onDone()}
          disabled={!works}
        >
          Continue
          <ArrowRightIcon className="icon--sm" />
        </button>
      </div>
    </section>
  );
}
