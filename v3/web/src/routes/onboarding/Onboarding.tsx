/**
 * The first-run setup (SPEC-110 deliverable #1, reworked for issues 559, 561,
 * 562, 563 and 565 after the 2026-10-23 installation test).
 *
 * One forward journey, in the order the hub needs it:
 *
 *   How you'll use palaia → Your first memory → Your account →
 *   Cloud access (cloud goal only) → Connect an AI app → Done
 *
 * - Every step's state comes from `/api/setup` (the hub), so a reload, a
 *   restart or another browser resume at the first open step; a ticked step
 *   is one the hub confirms.
 * - The goal comes first, because it decides what the rest means: the usual
 *   shared hub (cloud: ChatGPT and Claude connect over a public HTTPS
 *   address and sign in; the dashboard stays private) or private only.
 * - The memory comes before the account and cloud access, because the
 *   sign-in server grants access to memories and has nothing to grant
 *   without one — the order that sent the 2026-10-23 tester back from step
 *   4 to step 1.
 * - Turning cloud access on needs one restart; the wizard says so before,
 *   restarts the hub itself where it can, and continues here after the
 *   sign-in that follows.
 */
import { useEffect, useMemo, useRef, useState } from "react";
import { Link, useNavigate } from "react-router-dom";

import { Field, Input } from "../../components/Field";
import type { SetupStatus } from "../../lib/api/client";
import { api } from "../../lib/api/client";
import { describeApiError } from "../../lib/errors";
import { useSetupStatus, waitForRestart } from "../../lib/setup";
import { ArrowRightIcon, CheckIcon, WarningIcon } from "../../shell/icons";
import { CloudStep } from "./CloudStep";
import { RestartByHand } from "./RestartByHand";
import { ConnectStep } from "./ConnectStep";
import "./onboarding.css";
import {
  firstOpenStep,
  goalOf,
  type Goal,
  type StepId,
  stepViews,
} from "./steps";

const MIN_PASSWORD_LENGTH = 12;

/** Spoken after a step's name: the rail's ticks are not only visual. */
const STATE_LABEL = {
  done: " (done)",
  skipped: " (skipped)",
  attention: " (needs attention)",
  todo: "",
} as const;
const VAULT_KEY_RE = /^[a-z0-9][a-z0-9-]*$/;

export function Onboarding() {
  const navigate = useNavigate();
  const { status, error, refresh } = useSetupStatus(3000);
  // The step on screen. It starts at the first open one and moves only when
  // the person moves (Continue, the rail): a status poll that finds a step
  // done must not pull the page away from the result they are reading.
  const [pinned, setPinned] = useState<StepId | "done" | null>(null);
  const panel = useRef<HTMLDivElement>(null);

  const views = useMemo(() => (status ? stepViews(status) : []), [status]);
  const open = status ? firstOpenStep(views) : null;
  if (status && pinned === null) setPinned(open ?? "done");
  const current: StepId | "done" = pinned ?? open ?? "done";

  // A new step starts at its top, on a phone too.
  useEffect(() => {
    panel.current?.scrollTo?.({ top: 0 });
    window.scrollTo?.({ top: 0 });
  }, [current]);

  async function finish() {
    await api.updateSetup({ completed: true });
    navigate("/", { replace: true });
  }

  async function next() {
    const latest = await refresh();
    if (latest) setPinned(firstOpenStep(stepViews(latest)) ?? "done");
  }

  if (!status) {
    return (
      <div className="ob">
        <div className="ob__panel" ref={panel}>
          <div className="ob__inner">
            {error ? (
              <div className="banner banner--risk" role="alert">
                <WarningIcon className="icon icon--sm" />
                <div>
                  <p className="banner__title">Can't reach palaia</p>
                  <p className="t-sm t-muted">
                    {describeApiError(error)} This page tries again by itself.
                  </p>
                </div>
              </div>
            ) : (
              <p className="t-muted">Loading setup…</p>
            )}
          </div>
        </div>
      </div>
    );
  }

  const index = views.findIndex((view) => view.id === current);
  const position = current === "done" ? views.length : index + 1;

  return (
    <div className="ob">
      <aside className="ob__rail" aria-label="Setup steps">
        <span className="ob__brand">palaia</span>
        <ol className="ob__steps">
          {views.map((view, i) => {
            const isCurrent = view.id === current;
            const reachable = view.state !== "todo" || view.id === open;
            return (
              <li key={view.id}>
                <button
                  type="button"
                  className={[
                    "ob__step",
                    isCurrent ? "ob__step--current" : "",
                    `ob__step--${view.state}`,
                  ]
                    .filter(Boolean)
                    .join(" ")}
                  aria-current={isCurrent ? "step" : undefined}
                  aria-label={`${view.name}${STATE_LABEL[view.state]}`}
                  disabled={!reachable}
                  onClick={() => setPinned(view.id)}
                >
                  <span className="ob__num" aria-hidden="true">
                    {view.state === "done" ? (
                      <CheckIcon className="icon--sm" />
                    ) : (
                      i + 1
                    )}
                  </span>
                  <span className="ob__step-name">{view.name}</span>
                </button>
              </li>
            );
          })}
        </ol>
        <p className="t-xs t-muted ob__rail-note">
          About 5 minutes. You can change everything later in Settings. Your
          data stays on this server.
        </p>
      </aside>

      <main className="ob__panel" ref={panel}>
        <div className="ob__inner">
          <div className="ob__top">
            <span className="t-meta">
              {current === "done"
                ? "Done"
                : `Step ${position} of ${views.length}`}
            </span>
            <button
              type="button"
              className="btn btn--ghost btn--sm"
              onClick={() => void finish()}
            >
              Leave setup
            </button>
          </div>
          <div
            className="ob__progress"
            role="progressbar"
            aria-valuemin={0}
            aria-valuemax={views.length}
            aria-valuenow={
              views.filter((v) => v.state === "done" || v.state === "skipped")
                .length
            }
          >
            <span
              style={{
                width: `${(100 * views.filter((v) => v.state === "done" || v.state === "skipped").length) / views.length}%`,
              }}
            />
          </div>

          {status.problems.length > 0 ? (
            <div className="banner banner--warn" role="status">
              <WarningIcon className="icon icon--sm" />
              <div>
                {status.problems.map((problem) => (
                  <p className="t-sm" key={problem}>
                    {problem}
                  </p>
                ))}
              </div>
            </div>
          ) : null}

          {current === "goal" ? (
            <GoalStep status={status} onDone={next} />
          ) : null}
          {current === "memory" ? (
            <MemoryStep status={status} onDone={next} />
          ) : null}
          {current === "account" ? (
            <AccountStep status={status} onDone={next} />
          ) : null}
          {current === "cloud" ? (
            <CloudStep status={status} refresh={refresh} onDone={next} />
          ) : null}
          {current === "connect" ? (
            <ConnectStep
              status={status}
              onDone={next}
              onWantCloud={async () => {
                await api.updateSetup({ goal: "cloud" });
                await refresh();
                setPinned("cloud");
              }}
            />
          ) : null}
          {current === "done" ? (
            <DoneStep status={status} onFinish={finish} />
          ) : null}
        </div>
      </main>
    </div>
  );
}

// --------------------------------------------------------------------- goal

const GOALS: { goal: Goal; title: string; badge?: string; text: string }[] = [
  {
    goal: "cloud",
    title: "With ChatGPT and Claude",
    badge: "Recommended",
    text:
      "Your AI apps — also the Claude app on your phone or Mac — reach palaia over a secure " +
      "web address and sign in with your account. This dashboard stays on your private network.",
  },
  {
    goal: "private",
    title: "Only on my own devices",
    text:
      "For AI apps on computers in your private network, such as Claude Desktop or Claude " +
      "Code. ChatGPT and claude.ai can't connect.",
  },
];

function GoalStep({
  status,
  onDone,
}: {
  status: SetupStatus;
  onDone: () => Promise<void>;
}) {
  const [goal, setGoal] = useState<Goal>(goalOf(status));
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function save() {
    setBusy(true);
    setError(null);
    try {
      await api.updateSetup({ goal });
      await onDone();
    } catch (err) {
      setError(describeApiError(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="ob__step-body" aria-labelledby="ob-goal-title">
      <h1 id="ob-goal-title" className="ob__title">
        How do you want to use palaia?
      </h1>
      <div
        className="radiocards"
        role="radiogroup"
        aria-label="How you'll use palaia"
      >
        {GOALS.map((card) => (
          <button
            type="button"
            role="radio"
            aria-checked={goal === card.goal}
            key={card.goal}
            className={["radiocard", goal === card.goal ? "radiocard--on" : ""]
              .filter(Boolean)
              .join(" ")}
            onClick={() => setGoal(card.goal)}
          >
            <span className="radiocard__pick" />
            <span className="grow">
              <span className="row" style={{ gap: 8 }}>
                <span className="radiocard__name">{card.title}</span>
                {card.badge ? (
                  <span className="badge badge--ok">{card.badge}</span>
                ) : null}
              </span>
              <span className="radiocard__when">{card.text}</span>
            </span>
          </button>
        ))}
      </div>
      <p className="t-sm t-muted">You can change this later under Access.</p>
      {error ? <p className="field__error">{error}</p> : null}
      <div className="ob__foot">
        <button
          type="button"
          className="btn btn--primary btn--lg"
          onClick={() => void save()}
          disabled={busy}
        >
          Continue
          <ArrowRightIcon className="icon--sm" />
        </button>
      </div>
    </section>
  );
}

// ------------------------------------------------------------------- memory

function MemoryStep({
  status,
  onDone,
}: {
  status: SetupStatus;
  onDone: () => Promise<void>;
}) {
  const [key, setKey] = useState("work");
  const [purpose, setPurpose] = useState("");
  const [path, setPath] = useState("");
  const [template, setTemplate] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  if (status.vaults.length > 0) {
    return (
      <section className="ob__step-body">
        <h1 className="ob__title">Your memory is ready</h1>
        <p className="t-lead">
          {status.vaults.length === 1
            ? `“${status.vaults[0]}” is where your AI apps save and find notes.`
            : `${status.vaults.length} memories are ready for your AI apps.`}
        </p>
        <div className="ob__foot">
          <button
            type="button"
            className="btn btn--primary btn--lg"
            onClick={() => void onDone()}
          >
            Continue
            <ArrowRightIcon className="icon--sm" />
          </button>
        </div>
      </section>
    );
  }

  const keyError =
    key && !VAULT_KEY_RE.test(key)
      ? "Use lowercase letters, numbers and dashes, starting with a letter or number."
      : undefined;

  async function create() {
    setBusy(true);
    setError(null);
    try {
      await api.createVault({
        key,
        purpose: purpose.trim() || undefined,
        path: path.trim() || undefined,
        template,
      });
      await onDone();
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
        if (key && !keyError && !busy) void create();
      }}
    >
      <h1 className="ob__title">Create your first memory</h1>
      <p className="t-lead">
        A memory is a folder of notes your AI apps read and write. You can add
        more later.
      </p>
      <div className="card">
        <div className="card__body stack stack--3">
          <Field
            label="Name"
            hint="Lowercase letters, numbers and dashes, e.g. work."
            error={keyError}
          >
            <Input
              value={key}
              onChange={(e) =>
                setKey(e.target.value.toLowerCase().replace(/\s+/g, "-"))
              }
              required
              autoComplete="off"
            />
          </Field>
          <Field
            label={
              <>
                What it's for <span className="field__optional">Optional</span>
              </>
            }
            hint="AI apps read this to choose the right memory. Leave it empty to add it later."
          >
            <Input
              value={purpose}
              onChange={(e) => setPurpose(e.target.value)}
              placeholder="Projects, decisions and notes"
            />
          </Field>
          <details className="ob__more">
            <summary>More options</summary>
            <div className="stack stack--3">
              <Field
                label={
                  <>
                    Folder <span className="field__optional">Optional</span>
                  </>
                }
                hint="Leave empty to keep it in palaia's data folder."
              >
                <Input value={path} onChange={(e) => setPath(e.target.value)} />
              </Field>
              <label className="ob__check">
                <input
                  type="checkbox"
                  checked={template}
                  onChange={(e) => setTemplate(e.target.checked)}
                />
                <span>
                  Add two example notes{" "}
                  <span className="t-muted">— delete them any time</span>
                </span>
              </label>
            </div>
          </details>
          <p className="t-sm t-muted">
            Every change is saved with its history, so you can undo it.
          </p>
        </div>
      </div>
      {error ? <p className="field__error">{error}</p> : null}
      <div className="ob__foot">
        <button
          type="submit"
          className="btn btn--primary btn--lg"
          disabled={busy || !key || Boolean(keyError)}
        >
          {busy ? "Creating…" : "Create memory"}
          <ArrowRightIcon className="icon--sm" />
        </button>
      </div>
    </form>
  );
}

// ------------------------------------------------------------------ account

function AccountStep({
  status,
  onDone,
}: {
  status: SetupStatus;
  onDone: () => Promise<void>;
}) {
  const goal = goalOf(status);
  const [name, setName] = useState("");
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [restarting, setRestarting] = useState(false);

  const signInPending =
    goal === "private" &&
    status.owner_configured &&
    status.configured_sign_in &&
    !status.sign_in_active;

  if (status.owner_configured && !signInPending) {
    return (
      <section className="ob__step-body">
        <h1 className="ob__title">Your account is set up</h1>
        <p className="t-lead">
          {goal === "cloud"
            ? "You sign in with it to this dashboard and when an AI app connects to palaia."
            : "You sign in with it to this dashboard."}
        </p>
        <div className="ob__foot">
          <button
            type="button"
            className="btn btn--primary btn--lg"
            onClick={() => void onDone()}
          >
            Continue
            <ArrowRightIcon className="icon--sm" />
          </button>
        </div>
      </section>
    );
  }

  if (signInPending) {
    async function restart() {
      setRestarting(true);
      setError(null);
      try {
        await api.restartHub();
        await waitForRestart();
        window.location.reload();
      } catch (err) {
        setError(describeApiError(err));
        setRestarting(false);
      }
    }
    return (
      <section className="ob__step-body">
        <h1 className="ob__title">Restart palaia to turn on sign-in</h1>
        <p className="t-lead">
          After the restart, palaia asks for your password, then setup continues
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

  const confirmError =
    confirm && confirm !== password
      ? "The two passwords are not the same."
      : undefined;
  const valid =
    name.trim().length > 0 &&
    password.length >= MIN_PASSWORD_LENGTH &&
    password === confirm;

  async function create() {
    setBusy(true);
    setError(null);
    try {
      await api.createOwnerAccount({ username: name.trim(), password });
      if (goal === "private" && !status.sign_in_active) {
        // A private hub asks for the password only once its sign-in server
        // runs: turn it on for this dashboard (one restart, next screen).
        await api.changeMode({
          oauth_enabled: true,
          oauth_issuer: window.location.origin,
          dashboard_require_sign_in: true,
        });
      }
      await onDone();
    } catch (err) {
      setError(describeApiError(err));
    } finally {
      setBusy(false);
    }
  }

  async function skip() {
    setBusy(true);
    try {
      await api.updateSetup({ skipped: [...status.skipped, "account"] });
      await onDone();
    } finally {
      setBusy(false);
    }
  }

  return (
    <form
      className="ob__step-body"
      onSubmit={(event) => {
        event.preventDefault();
        if (valid && !busy) void create();
      }}
    >
      <h1 className="ob__title">Create your account</h1>
      <p className="t-lead">
        {goal === "cloud"
          ? "You sign in with this account to the dashboard and whenever ChatGPT or Claude " +
            "connects. AI apps never see the password."
          : "Optional. With an account, this dashboard asks for your password; without one, " +
            "anyone on your private network can open it."}
      </p>
      <div className="card">
        <div className="card__body stack stack--3">
          <Field label="Username">
            <Input
              value={name}
              onChange={(e) => setName(e.target.value)}
              autoComplete="username"
              required
            />
          </Field>
          <Field
            label="Password"
            hint={`At least ${MIN_PASSWORD_LENGTH} characters.`}
          >
            <Input
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              autoComplete="new-password"
              required
            />
          </Field>
          <Field label="Repeat the password" error={confirmError}>
            <Input
              type="password"
              value={confirm}
              onChange={(e) => setConfirm(e.target.value)}
              autoComplete="new-password"
              required
            />
          </Field>
        </div>
      </div>
      {goal === "private" ? (
        <p className="t-sm t-muted">Turning sign-in on restarts palaia once.</p>
      ) : null}
      {error ? <p className="field__error">{error}</p> : null}
      <div className="ob__foot">
        {goal === "private" ? (
          <button
            type="button"
            className="btn"
            onClick={() => void skip()}
            disabled={busy}
          >
            Skip
          </button>
        ) : null}
        <button
          type="submit"
          className="btn btn--primary btn--lg"
          disabled={!valid || busy}
        >
          {busy ? "Creating…" : "Create account"}
          <ArrowRightIcon className="icon--sm" />
        </button>
      </div>
    </form>
  );
}

// --------------------------------------------------------------------- done

function DoneStep({
  status,
  onFinish,
}: {
  status: SetupStatus;
  onFinish: () => Promise<void>;
}) {
  const goal = goalOf(status);
  const rows: { label: string; value: string; ok: boolean }[] = [
    {
      label: "Memory",
      value: status.vaults.length ? status.vaults.join(", ") : "None yet",
      ok: status.vaults.length > 0,
    },
    {
      label: "Account",
      value: status.owner_configured ? "Set up" : "Not set up",
      ok: status.owner_configured,
    },
  ];
  if (goal === "cloud") {
    rows.push({
      label: "Cloud access",
      value: status.cloud_ready ? (status.issuer ?? "On") : "Off",
      ok: status.cloud_ready,
    });
  }
  rows.push({
    label: "AI app",
    value: status.client_connected
      ? "Connected"
      : "Waiting for the first request",
    ok: status.client_connected,
  });
  return (
    <section className="ob__step-body">
      <h1 className="ob__title">You're set up</h1>
      <ul className="ob__summary">
        {rows.map((row) => (
          <li key={row.label}>
            <span
              className={row.ok ? "ob__dot ob__dot--ok" : "ob__dot"}
              aria-hidden="true"
            />
            <span className="ob__summary-label">{row.label}</span>
            <span className="ob__summary-value">{row.value}</span>
          </li>
        ))}
      </ul>
      <div className="ob__foot">
        <button
          type="button"
          className="btn btn--primary btn--lg"
          onClick={() => void onFinish()}
        >
          Open palaia
          <ArrowRightIcon className="icon--sm" />
        </button>
      </div>
      <p className="t-sm t-muted">
        Next: <Link to="/clients">connect another AI app</Link> — one memory,
        shared by all of them.
      </p>
    </section>
  );
}
