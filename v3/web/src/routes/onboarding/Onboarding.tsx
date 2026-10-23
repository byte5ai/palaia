/**
 * The first-run setup (SPEC-110 deliverable #1, reworked for issues 559, 561,
 * 562, 563 and 565 after the 2026-10-23 installation test; design 570).
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
import { useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";

import { Button, LinkButton } from "../../components/Button";
import { Callout } from "../../components/Callout";
import { Disclosure } from "../../components/Disclosure";
import { Field, Input } from "../../components/Field";
import { RestartButton } from "../../components/RestartHub";
import { StatusPill } from "../../components/StatusPill";
import { Stepper, StepperPanel, type StepperStep } from "../../components/Stepper";
import type { SetupStatus } from "../../lib/api/client";
import { api } from "../../lib/api/client";
import { describeApiError } from "../../lib/errors";
import { useSetupStatus } from "../../lib/setup";
import { ArrowRightIcon } from "../../shell/icons";
import { CloudStep } from "./CloudStep";
import { ConnectStep } from "./ConnectStep";
import { RestartByHand } from "./RestartByHand";
import "./onboarding.css";
import { firstOpenStep, goalOf, type Goal, type StepId, stepViews } from "./steps";

const MIN_PASSWORD_LENGTH = 12;
const VAULT_KEY_RE = /^[a-z0-9][a-z0-9-]*$/;

export interface StepProps {
  status: SetupStatus;
  onDone: () => Promise<void>;
}

export function Onboarding() {
  const navigate = useNavigate();
  const { status, error, refresh } = useSetupStatus(3000);
  // The step on screen. It starts at the first open one and moves only when
  // the person moves (Continue, the step list): a status poll that finds a
  // step done must not pull the page away from the result they are reading.
  const [pinned, setPinned] = useState<StepId | "done" | null>(null);

  const views = useMemo(() => (status ? stepViews(status) : []), [status]);
  const open = status ? firstOpenStep(views) : null;
  if (status && pinned === null) setPinned(open ?? "done");
  const current: StepId | "done" = pinned ?? open ?? "done";

  async function finish() {
    await api.updateSetup({ completed: true });
    navigate("/", { replace: true });
  }

  async function next() {
    const latest = await refresh();
    if (latest) setPinned(firstOpenStep(stepViews(latest)) ?? "done");
  }

  const index = current === "done" ? views.length : views.findIndex((v) => v.id === current);
  const steps: StepperStep[] = [
    ...views.map((view, i) => ({
      id: view.id,
      label: view.name,
      state:
        i === index
          ? ("current" as const)
          : view.state === "done"
            ? ("done" as const)
            : view.state === "skipped"
              ? ("skipped" as const)
              : view.state === "attention"
                ? ("attention" as const)
                : ("todo" as const),
    })),
    { id: "done", label: "Done", state: current === "done" ? "current" : "todo" },
  ];

  return (
    <Stepper
      steps={steps}
      currentIndex={index}
      onSelect={(i) => setPinned(i < views.length ? views[i]!.id : "done")}
      barEnd={
        status ? (
          <Button variant="plain" size="sm" onClick={() => void finish()}>
            Leave setup
          </Button>
        ) : null
      }
    >
      {!status ? (
        <StepperPanel title={error ? "Can't reach palaia" : "Loading setup…"}>
          {error ? (
            <Callout tone="error" title="palaia doesn't answer right now">
              <p>{describeApiError(error)} This page tries again by itself.</p>
            </Callout>
          ) : null}
        </StepperPanel>
      ) : (
        <div className="ob__main">
          {status.problems.length > 0 ? (
            <div className="ob__problems">
              {status.problems.map((problem) => (
                <Callout key={problem} tone="warn" title="palaia needs a look" role="status">
                  <p>{problem}</p>
                </Callout>
              ))}
            </div>
          ) : null}
          {current === "goal" ? <GoalStep status={status} onDone={next} /> : null}
          {current === "memory" ? <MemoryStep status={status} onDone={next} /> : null}
          {current === "account" ? <AccountStep status={status} onDone={next} /> : null}
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
          {current === "done" ? <DoneStep status={status} onFinish={finish} /> : null}
        </div>
      )}
    </Stepper>
  );
}

function ContinueButton({ onClick, label = "Continue" }: { onClick: () => void; label?: string }) {
  return (
    <Button variant="primary" size="lg" onClick={onClick}>
      {label}
      <ArrowRightIcon className="icon--sm" />
    </Button>
  );
}

// --------------------------------------------------------------------- goal

const GOALS: { goal: Goal; title: string; recommended?: boolean; text: string }[] = [
  {
    goal: "cloud",
    title: "With ChatGPT and Claude",
    recommended: true,
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

function GoalStep({ status, onDone }: StepProps) {
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
    <StepperPanel
      title="How do you want to use palaia?"
      description="You can change this later in Settings → Access."
      primary={
        <Button variant="primary" size="lg" loading={busy} onClick={() => void save()}>
          Continue
          <ArrowRightIcon className="icon--sm" />
        </Button>
      }
    >
      <div className="radiocards" role="radiogroup" aria-label="How you'll use palaia">
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
              <span className="row row--wrap">
                <span className="radiocard__name">{card.title}</span>
                {card.recommended ? <StatusPill tone="info">Recommended</StatusPill> : null}
              </span>
              <span className="radiocard__when">{card.text}</span>
            </span>
          </button>
        ))}
      </div>
      {error ? <p className="field__error">{error}</p> : null}
    </StepperPanel>
  );
}

// ------------------------------------------------------------------- memory

function MemoryStep({ status, onDone }: StepProps) {
  const [key, setKey] = useState("work");
  const [purpose, setPurpose] = useState("");
  const [path, setPath] = useState("");
  const [template, setTemplate] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  if (status.vaults.length > 0) {
    return (
      <StepperPanel
        title="Your memory is ready"
        description={
          status.vaults.length === 1
            ? `“${status.vaults[0]}” is where your AI apps save and find notes.`
            : `${status.vaults.length} memories are ready for your AI apps.`
        }
        primary={<ContinueButton onClick={() => void onDone()} />}
      />
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
      onSubmit={(event) => {
        event.preventDefault();
        if (key && !keyError && !busy) void create();
      }}
    >
      <StepperPanel
        title="Create your first memory"
        description="A memory is a folder of notes your AI apps read and write. You can add more later."
        primary={
          <Button
            type="submit"
            variant="primary"
            size="lg"
            loading={busy}
            disabled={!key || Boolean(keyError)}
          >
            Create memory
            <ArrowRightIcon className="icon--sm" />
          </Button>
        }
      >
        <div className="stack stack--4">
          <Field label="Name" hint="Lowercase letters, numbers and dashes, e.g. work." error={keyError}>
            <Input
              value={key}
              onChange={(e) => setKey(e.target.value.toLowerCase().replace(/\s+/g, "-"))}
              required
              autoComplete="off"
            />
          </Field>
          <Field
            label="What it's for"
            optional
            hint="AI apps read this to choose the right memory. Leave it empty to add it later."
          >
            <Input
              value={purpose}
              onChange={(e) => setPurpose(e.target.value)}
              placeholder="Projects, decisions and notes"
            />
          </Field>
          <Disclosure summary="More options">
            <div className="stack stack--4">
              <Field label="Folder" optional hint="Leave empty to keep it in palaia's data folder.">
                <Input value={path} onChange={(e) => setPath(e.target.value)} />
              </Field>
              <label className="checkrow">
                <input
                  type="checkbox"
                  checked={template}
                  onChange={(e) => setTemplate(e.target.checked)}
                />
                <span>
                  Add two example notes <span className="t-muted">— delete them any time</span>
                </span>
              </label>
            </div>
          </Disclosure>
          <p className="t-sm t-muted">Every change is saved with its history, so you can undo it.</p>
          {error ? <p className="field__error">{error}</p> : null}
        </div>
      </StepperPanel>
    </form>
  );
}

// ------------------------------------------------------------------ account

function AccountStep({ status, onDone }: StepProps) {
  const goal = goalOf(status);
  const [name, setName] = useState("");
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const signInPending =
    goal === "private" &&
    status.owner_configured &&
    status.configured_sign_in &&
    !status.sign_in_active;

  if (status.owner_configured && !signInPending) {
    return (
      <StepperPanel
        title="Your account is set up"
        description={
          goal === "cloud"
            ? "You sign in with it to this dashboard and when an AI app connects to palaia."
            : "You sign in with it to this dashboard."
        }
        primary={<ContinueButton onClick={() => void onDone()} />}
      />
    );
  }

  if (signInPending) {
    return (
      <StepperPanel
        title="Restart palaia to turn on sign-in"
        description="After the restart, palaia asks for your password, then setup continues here."
        primary={
          status.restart_supported ? <RestartButton variant="primary" confirm={false} /> : null
        }
      >
        {status.restart_supported ? null : <RestartByHand />}
      </StepperPanel>
    );
  }

  const confirmError =
    confirm && confirm !== password ? "The two passwords are not the same." : undefined;
  const valid =
    name.trim().length > 0 && password.length >= MIN_PASSWORD_LENGTH && password === confirm;

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
      onSubmit={(event) => {
        event.preventDefault();
        if (valid && !busy) void create();
      }}
    >
      <StepperPanel
        title="Create your account"
        description={
          goal === "cloud"
            ? "You sign in with this account to the dashboard and whenever ChatGPT or Claude " +
              "connects. AI apps never see the password."
            : "Optional. With an account, this dashboard asks for your password; without one, " +
              "anyone on your private network can open it."
        }
        back={
          goal === "private" ? (
            <Button variant="secondary" onClick={() => void skip()} disabled={busy}>
              Skip
            </Button>
          ) : undefined
        }
        primary={
          <Button type="submit" variant="primary" size="lg" loading={busy} disabled={!valid}>
            Create account
            <ArrowRightIcon className="icon--sm" />
          </Button>
        }
      >
        <div className="stack stack--4">
          <Field label="Username">
            <Input
              value={name}
              onChange={(e) => setName(e.target.value)}
              autoComplete="username"
              required
            />
          </Field>
          <Field label="Password" hint={`At least ${MIN_PASSWORD_LENGTH} characters.`}>
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
          {goal === "private" ? (
            <p className="t-sm t-muted">Turning sign-in on restarts palaia once.</p>
          ) : null}
          {error ? <p className="field__error">{error}</p> : null}
        </div>
      </StepperPanel>
    </form>
  );
}

// --------------------------------------------------------------------- done

function DoneStep({ status, onFinish }: { status: SetupStatus; onFinish: () => Promise<void> }) {
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
      value: status.cloud_ready && status.cloud_verified ? (status.issuer ?? "On") : "Off",
      ok: status.cloud_ready && status.cloud_verified,
    });
  }
  rows.push({
    label: "AI app",
    value: status.client_connected ? "Connected" : "Waiting for the first request",
    ok: status.client_connected,
  });
  return (
    <StepperPanel
      title="You're set up"
      primary={<ContinueButton label="Open palaia" onClick={() => void onFinish()} />}
      back={
        <LinkButton to="/apps" variant="plain">
          Connect another AI app
        </LinkButton>
      }
    >
      <ul className="ob__summary">
        {rows.map((row) => (
          <li key={row.label}>
            <span className="ob__summary-label">{row.label}</span>
            <span className="ob__summary-value">{row.value}</span>
            <StatusPill tone={row.ok ? "ok" : "neutral"}>{row.ok ? "Done" : "Open"}</StatusPill>
          </li>
        ))}
      </ul>
    </StepperPanel>
  );
}
