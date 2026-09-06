/**
 * The onboarding wizard (SPEC-110 deliverable #1): owner account → access
 * mode → first vault → connect a client. Visual ground truth:
 * v3/docs/design/mockups/onboarding.html — its `.wiz` rail-and-panel
 * layout, `.steps` list and `.radiocards`/`.clientgrid` are ported in
 * components.css and reused as-is.
 *
 * Honest about which steps are real:
 * - Step 3 (first vault) is fully wired to `POST /api/vaults` — creating
 *   it here creates a real vault on disk, with a real git history, and
 *   (SPEC-210) mounts it live on the running hub's MCP gateway under the
 *   `default` profile — no hub restart needed before step 4's client can
 *   reach it.
 * - Step 4 (first client) reuses the same `ConnectPanel` the dedicated
 *   Clients page uses — issuing a token here is real, and (as of
 *   SPEC-210) so is the endpoint it names: the `default` profile the
 *   wizard's vault creation just mounted.
 * - Step 1 (owner account) is real since issue 342: it creates the hub's
 *   one owner account through `POST /api/auth/owner` (accepted only while
 *   none exists) and signs this browser in with it. A hub whose sign-in
 *   server is off (`oauth.enabled: false`, the default) is offered the
 *   switch here too — `POST /api/mode` turns it on, one restart applies
 *   it, and the step then shows the account form. A hub signing in
 *   through an identity provider has nothing to set up here.
 * - Step 2 (access mode) is still a preview: changing the hub's real mode
 *   is the Access page's job (SPEC-205); this step previews how step 4
 *   gates clients, showing the real current mode read-only from
 *   `GET /api/info`.
 */
import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";

import { ConnectPanel } from "../../components/ConnectPanel";
import { Field, Input } from "../../components/Field";
import { api } from "../../lib/api/client";
import type { SignInInfo } from "../../lib/api/client";
import type { HubMode } from "../../lib/clients";
import { guidedClients } from "../../lib/clients";
import { docsUrl } from "../../lib/docs";
import { describeApiError } from "../../lib/errors";
import {
  ArrowRightIcon,
  CheckIcon,
  ClientsIcon,
  LinkIcon,
  MarketplaceIcon,
  WarningIcon,
} from "../../shell/icons";

const STEP_NAMES = [
  { name: "Owner account", hint: "who administers this hub" },
  { name: "Access mode", hint: "who can reach it" },
  { name: "First vault", hint: "where memory lives" },
  { name: "First client", hint: "the two-minute part" },
];

const MODE_CARDS: { mode: HubMode; label: string; badge: string; when: string }[] = [
  {
    mode: "locked",
    label: "Locked",
    badge: "sign-in optional",
    when: "You only use agents in your terminal and apps on your own machines.",
  },
  {
    mode: "cloud",
    label: "Cloud",
    badge: "sign-in required",
    when:
      "You want claude.ai, ChatGPT or your phone to reach your memory, over a private tunnel — " +
      "this dashboard stays reachable only from your own network.",
  },
  {
    mode: "open",
    label: "Open",
    badge: "sign-in, plus a security checklist",
    when: "You consciously want the dashboard itself reachable from the internet.",
  },
];

/** What step 1 has to offer, once the hub has answered (issue 342). */
type OwnerStep =
  | { kind: "checking" }
  /** No sign-in server: the step offers to turn it on. */
  | { kind: "server-off" }
  /** Sign-in server turned on this session; the hub needs a restart first. */
  | { kind: "restart-pending" }
  | { kind: "idp"; provider: string }
  /** Password sign-in, no owner yet: the account form. */
  | { kind: "form" }
  | { kind: "configured" };

const MIN_PASSWORD_LENGTH = 12;

function StepRail({ step }: { step: number }) {
  return (
    <div className="steps">
      {STEP_NAMES.map((item, index) => {
        const num = index + 1;
        const state = num === step ? "step--on" : num < step ? "step--done" : "";
        return (
          <div className={["step", state].filter(Boolean).join(" ")} key={item.name}>
            <span className="step__num">{num < step ? <CheckIcon className="icon--sm" /> : num}</span>
            <span className="grow">
              <span className="step__name">{item.name}</span>
              <br />
              <span className="step__hint">{item.hint}</span>
            </span>
          </div>
        );
      })}
    </div>
  );
}

export function Onboarding() {
  const navigate = useNavigate();
  const [step, setStep] = useState(1);
  const [realMode, setRealMode] = useState<HubMode>("locked");

  const [ownerStep, setOwnerStep] = useState<OwnerStep>({ kind: "checking" });
  const [ownerName, setOwnerName] = useState("");
  const [ownerPassword, setOwnerPassword] = useState("");
  const [ownerConfirm, setOwnerConfirm] = useState("");
  const [ownerBusy, setOwnerBusy] = useState(false);
  const [ownerError, setOwnerError] = useState<string | null>(null);

  const [previewMode, setPreviewMode] = useState<HubMode>("locked");

  const [vaultKey, setVaultKey] = useState("work");
  const [vaultPurpose, setVaultPurpose] = useState("");
  const [vaultPath, setVaultPath] = useState("");
  const [template, setTemplate] = useState(false);
  const [creating, setCreating] = useState(false);
  const [createError, setCreateError] = useState<string | null>(null);

  const [clientId, setClientId] = useState(guidedClients()[0]!.id);

  useEffect(() => {
    let cancelled = false;
    const info = api.info().catch(() => null);
    const owner = api.ownerAccount().catch(() => null);
    Promise.all([info, owner]).then(([hubInfo, ownerState]) => {
      if (cancelled) return;
      if (hubInfo) {
        setRealMode(hubInfo.mode as HubMode);
        setPreviewMode(hubInfo.mode as HubMode);
      }
      const signIn = (hubInfo?.sign_in ?? null) as SignInInfo | null;
      if (signIn?.method === "idp") {
        setOwnerStep({ kind: "idp", provider: signIn.provider_name ?? "your sign-in provider" });
      } else if (ownerState === null) {
        // 404 (no sign-in server) or no hub reachable at all.
        setOwnerStep({ kind: "server-off" });
      } else {
        setOwnerStep({ kind: ownerState.configured ? "configured" : "form" });
      }
    });
    return () => {
      cancelled = true;
    };
  }, []);

  async function createOwner() {
    setOwnerBusy(true);
    setOwnerError(null);
    try {
      await api.createOwnerAccount({ username: ownerName.trim(), password: ownerPassword });
      setOwnerStep({ kind: "configured" });
      setStep(2);
    } catch (err) {
      setOwnerError(describeApiError(err));
    } finally {
      setOwnerBusy(false);
    }
  }

  async function turnOnSignIn() {
    setOwnerBusy(true);
    setOwnerError(null);
    try {
      const status = await api.changeMode({
        oauth_enabled: true,
        oauth_issuer: window.location.origin,
      });
      setOwnerStep({ kind: status.restart_required ? "restart-pending" : "form" });
    } catch (err) {
      setOwnerError(describeApiError(err));
    } finally {
      setOwnerBusy(false);
    }
  }

  const ownerFormValid =
    ownerName.trim().length > 0 &&
    ownerPassword.length >= MIN_PASSWORD_LENGTH &&
    ownerPassword === ownerConfirm;

  async function createVault() {
    setCreating(true);
    setCreateError(null);
    try {
      await api.createVault({
        key: vaultKey,
        purpose: vaultPurpose || undefined,
        path: vaultPath || undefined,
        template,
      });
      setStep(4);
    } catch (err) {
      setCreateError(describeApiError(err));
    } finally {
      setCreating(false);
    }
  }

  const selectedClient = guidedClients().find((c) => c.id === clientId) ?? guidedClients()[0]!;

  return (
    <div className="wiz">
      <aside className="wiz__rail">
        <a className="brand" href="/">
          <span className="brand__mark">p</span>
          <span className="brand__name">palaia</span>
          <span className="brand__ver">v3</span>
        </a>
        <StepRail step={step} />
        <div className="stack stack--2" style={{ marginTop: "auto" }}>
          <p className="t-xs t-muted">
            Takes about two minutes. Every answer is changeable later in Settings — nothing here
            is a one-way door.
          </p>
          <p className="t-xs t-subtle">No account on our servers, no telemetry. This hub is yours.</p>
        </div>
      </aside>

      <div className="wiz__panel">
        <div className="wiz__inner">
          {step === 1 ? (
            <>
              <div className="wiz__eyebrow">
                <span className="t-over">Step 1 of 4</span>
                <span className="badge">nothing installed on your clients yet</span>
              </div>
              <h2 className="wiz__title">Let's set up your hub.</h2>
              {ownerStep.kind === "form" ? (
                <>
                  <p className="t-lead">
                    The account you sign in to this dashboard with. palaia has exactly one owner —
                    AI tools connect with their own tokens, never with this password.
                  </p>
                  <form
                    className="card"
                    onSubmit={(e) => {
                      e.preventDefault();
                      if (ownerFormValid && !ownerBusy) void createOwner();
                    }}
                  >
                    <div className="card__body stack stack--3">
                      <Field label="Username">
                        <Input
                          value={ownerName}
                          onChange={(e) => setOwnerName(e.target.value)}
                          placeholder="owner"
                          autoComplete="username"
                        />
                      </Field>
                      <Field
                        label="Password"
                        hint={`At least ${MIN_PASSWORD_LENGTH} characters — a passphrase, or one from your password manager. Changeable later where the hub runs (palaia-hub oauth set-password).`}
                      >
                        <Input
                          type="password"
                          value={ownerPassword}
                          onChange={(e) => setOwnerPassword(e.target.value)}
                          autoComplete="new-password"
                        />
                      </Field>
                      <Field
                        label="Repeat the password"
                        error={
                          ownerConfirm && ownerConfirm !== ownerPassword
                            ? "The two passwords differ."
                            : undefined
                        }
                      >
                        <Input
                          type="password"
                          value={ownerConfirm}
                          onChange={(e) => setOwnerConfirm(e.target.value)}
                          autoComplete="new-password"
                        />
                      </Field>
                      {ownerError ? <p className="field__error">{ownerError}</p> : null}
                    </div>
                  </form>
                </>
              ) : null}
              {ownerStep.kind === "configured" ? (
                <p className="t-lead">
                  This hub already has its owner account. When the dashboard asks you to sign in,
                  that is the account to use — to change its password, run{" "}
                  <code>palaia-hub oauth set-password</code> where the hub runs.
                </p>
              ) : null}
              {ownerStep.kind === "idp" ? (
                <p className="t-lead">
                  This hub signs you in through {ownerStep.provider}, so there is no password to
                  set here — who may sign in is that provider's allow-list in the hub's
                  configuration.
                </p>
              ) : null}
              {ownerStep.kind === "server-off" ? (
                <>
                  <p className="t-lead">
                    This hub is running without its sign-in server, so the dashboard is protected
                    by your network alone. That is fine for a hub only your own devices reach —
                    turn sign-in on now if other people share the network, or before you make the
                    hub reachable from the internet.
                  </p>
                  {ownerError ? <p className="field__error">{ownerError}</p> : null}
                  <div className="row" style={{ gap: 8 }}>
                    <button
                      type="button"
                      className="btn"
                      onClick={() => void turnOnSignIn()}
                      disabled={ownerBusy}
                    >
                      {ownerBusy ? "Turning on…" : "Turn on sign-in"}
                    </button>
                  </div>
                </>
              ) : null}
              {ownerStep.kind === "restart-pending" ? (
                <div className="banner">
                  <WarningIcon className="icon icon--sm" />
                  <div>
                    <p className="banner__title">Sign-in is switched on — one restart applies it</p>
                    <p className="t-sm t-muted">
                      Restart the hub (the container, or the service), then open this setup again:
                      this step will ask for your account. Everything else below works without the
                      restart.
                    </p>
                  </div>
                </div>
              ) : null}
              {ownerStep.kind === "checking" ? (
                <p className="t-lead t-muted">Checking how this hub signs you in…</p>
              ) : null}
              <div className="wiz__foot">
                <span className="t-meta">Step 1 of 4</span>
                <span className="grow" style={{ textAlign: "right" }}>
                  {ownerStep.kind === "form" ? (
                    <button
                      type="button"
                      className="btn btn--primary btn--lg"
                      onClick={() => void createOwner()}
                      disabled={!ownerFormValid || ownerBusy}
                    >
                      {ownerBusy ? "Creating…" : "Create account"}
                      <ArrowRightIcon className="icon--sm" />
                    </button>
                  ) : (
                    <button
                      type="button"
                      className="btn btn--primary btn--lg"
                      onClick={() => setStep(2)}
                      disabled={ownerStep.kind === "checking"}
                    >
                      Continue
                      <ArrowRightIcon className="icon--sm" />
                    </button>
                  )}
                </span>
              </div>
            </>
          ) : null}

          {step === 2 ? (
            <>
              <div className="wiz__eyebrow">
                <span className="t-over">Step 2 of 4</span>
                <span className="badge">this hub is currently running in {realMode} mode</span>
              </div>
              <h2 className="wiz__title">Who should be able to reach palaia?</h2>
              <p className="t-lead">
                This previews which clients Step 4 can guide you through. Changing the hub's real
                mode is a config-file/Settings action, not this wizard, yet — pick the one you
                mean to use so the reasons in Step 4 line up.
              </p>
              <div className="radiocards">
                {MODE_CARDS.map((card) => (
                  <button
                    type="button"
                    key={card.mode}
                    className={["radiocard", previewMode === card.mode ? "radiocard--on" : ""]
                      .filter(Boolean)
                      .join(" ")}
                    onClick={() => setPreviewMode(card.mode)}
                    style={{ textAlign: "left", width: "100%" }}
                  >
                    <span className="radiocard__pick" />
                    <span className="grow">
                      <span className="row" style={{ gap: 8 }}>
                        <span className="radiocard__name">{card.label}</span>
                        <span className="badge">{card.badge}</span>
                      </span>
                      <span className="radiocard__when">{card.when}</span>
                    </span>
                  </button>
                ))}
              </div>
              <div className="banner">
                <WarningIcon className="icon icon--sm" />
                <div>
                  <p className="banner__title">The part other tools leave out</p>
                  <p className="t-sm t-muted">
                    claude.ai, ChatGPT and the phone apps connect from <em>their vendor's cloud</em>,
                    not from your device: in Locked mode they cannot reach palaia, whatever your
                    network looks like.
                  </p>
                </div>
              </div>
              <div className="wiz__foot">
                <button type="button" className="btn" onClick={() => setStep(1)}>
                  Back
                </button>
                <span className="t-meta">Step 2 of 4</span>
                <span className="grow" style={{ textAlign: "right" }}>
                  <button type="button" className="btn btn--primary btn--lg" onClick={() => setStep(3)}>
                    Continue with {MODE_CARDS.find((c) => c.mode === previewMode)!.label}
                    <ArrowRightIcon className="icon--sm" />
                  </button>
                </span>
              </div>
            </>
          ) : null}

          {step === 3 ? (
            <>
              <div className="wiz__eyebrow">
                <span className="t-over">Step 3 of 4</span>
                <span className="badge">plain Markdown, versioned with git</span>
              </div>
              <h2 className="wiz__title">Your first vault.</h2>
              <p className="t-lead">
                A folder of Markdown files your agents share. Add more later; they stay physically
                separate.
              </p>
              <div className="card">
                <div className="card__body stack stack--3">
                  <Field label="Name" hint="Becomes part of your agents' tool names, e.g. work_memory_search.">
                    <Input
                      value={vaultKey}
                      onChange={(e) => setVaultKey(e.target.value.toLowerCase().replace(/[^a-z0-9-]/g, "-"))}
                    />
                  </Field>
                  <Field
                    label="What is this vault for?"
                    hint="The agents read this line. It is how they pick the right memory instead of guessing."
                  >
                    <Input
                      value={vaultPurpose}
                      onChange={(e) => setVaultPurpose(e.target.value)}
                      placeholder="Clients, projects and technical decisions at byte5"
                    />
                  </Field>
                  <Field label="Where it lives" hint="Leave blank to use the default location under the hub's data directory.">
                    <Input
                      value={vaultPath}
                      onChange={(e) => setVaultPath(e.target.value)}
                      placeholder="(default)"
                    />
                  </Field>
                  <div className="switchgrid">
                    <div className="switchrow">
                      <span className="switch switch--on" aria-hidden="true" />
                      <span className="grow">
                        <span className="field__label">Version with git</span>
                        <br />
                        <span className="field__hint">
                          Every write becomes a commit naming the agent and the reason. Always on —
                          this is the engine's own undo mechanism.
                        </span>
                      </span>
                    </div>
                    <button
                      type="button"
                      className="switchrow"
                      style={{ textAlign: "left", cursor: "pointer" }}
                      onClick={() => setTemplate((v) => !v)}
                    >
                      <span className={["switch", template ? "switch--on" : ""].filter(Boolean).join(" ")} />
                      <span className="grow">
                        <span className="field__label">Start from a template</span>
                        <br />
                        <span className="field__hint">Two example notes to learn from. Deletable, no lock-in.</span>
                      </span>
                    </button>
                  </div>
                </div>
              </div>
              <div className="preview stack stack--2">
                <div className="row row--wrap" style={{ gap: 6 }}>
                  <span className="t-over">What your agents will see</span>
                  <span className="chip chip--mono">{vaultKey}_memory_search</span>
                  <span className="chip chip--mono">{vaultKey}_memory_write</span>
                </div>
                <p className="t-xs t-muted">
                  Names carry the vault: an agent with two memories tells them apart from the tool
                  list alone.
                </p>
              </div>
              {createError ? <p className="field__error">{createError}</p> : null}
              <div className="wiz__foot">
                <button type="button" className="btn" onClick={() => setStep(2)}>
                  Back
                </button>
                <span className="t-meta">Step 3 of 4</span>
                <span className="grow" style={{ textAlign: "right" }}>
                  <button
                    type="button"
                    className="btn btn--signal btn--lg"
                    onClick={createVault}
                    disabled={creating || !vaultKey}
                  >
                    {creating ? "Creating…" : "Create vault"}
                    <ArrowRightIcon className="icon--sm" />
                  </button>
                </span>
              </div>
            </>
          ) : null}

          {step === 4 ? (
            <>
              <div className="wiz__eyebrow">
                <span className="t-over">Step 4 of 4</span>
                <span className="badge">most people finish this one in a minute</span>
              </div>
              <h2 className="wiz__title">Connect your first client.</h2>
              <p className="t-lead">
                Pick where you work most. You paste one thing — palaia handles the endpoint and
                the token.
              </p>
              <div className="clientgrid">
                {guidedClients().map((client) => (
                  <button
                    type="button"
                    key={client.id}
                    className={["clientcard", client.id === clientId ? "clientcard--on" : ""]
                      .filter(Boolean)
                      .join(" ")}
                    onClick={() => setClientId(client.id)}
                  >
                    <span className="row" style={{ gap: 8 }}>
                      <client.icon className="icon--sm" />
                      <span className="clientcard__name">{client.name}</span>
                    </span>
                    <span className="t-xs t-muted">{client.estimate}</span>
                  </button>
                ))}
              </div>
              <ConnectPanel
                key={selectedClient.id}
                client={selectedClient}
                defaultProfile="default"
              />
              <div className="card" style={{ marginTop: "var(--space-4)" }}>
                <div className="card__body stack stack--3">
                  <p className="t-over">What's next</p>
                  <div className="row row--wrap" style={{ gap: 8 }}>
                    <Link className="btn" to="/clients">
                      <ClientsIcon className="icon--sm" />
                      Connect a second AI
                    </Link>
                    <Link className="btn" to="/marketplace">
                      <MarketplaceIcon className="icon--sm" />
                      Install a tool
                    </Link>
                    <a
                      className="btn"
                      href={docsUrl("/first-shared-memory/")}
                      target="_blank"
                      rel="noreferrer"
                    >
                      <LinkIcon className="icon--sm" />
                      Read the docs
                    </a>
                  </div>
                  <p className="t-xs t-muted">
                    A second AI is the whole point — one memory both of them read from and write
                    to. All three are here whenever you're ready; nothing above is required to
                    finish.
                  </p>
                </div>
              </div>
              <div className="wiz__foot">
                <button type="button" className="btn" onClick={() => setStep(3)}>
                  Back
                </button>
                <span className="t-meta">Step 4 of 4</span>
                <span className="grow row" style={{ justifyContent: "flex-end" }}>
                  <button type="button" className="btn btn--ghost" onClick={() => navigate("/")}>
                    Skip for now
                  </button>
                  <button type="button" className="btn btn--primary btn--lg" onClick={() => navigate("/")}>
                    Finish
                    <ArrowRightIcon className="icon--sm" />
                  </button>
                </span>
              </div>
            </>
          ) : null}
        </div>
      </div>
    </div>
  );
}
