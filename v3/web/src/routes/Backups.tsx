/**
 * Settings › Backups (SPEC-604, issues 438, 570 and 571).
 *
 * Status first, then the action, then the details (Home Assistant's backup
 * page): the backup card with **Download backup**, the security note that is
 * always visible and "What's included?"; then automatic backups into
 * folders; then copying a memory's notes to Git.
 *
 * Every backup holds every key palaia has, so the hub serves these routes
 * only to a signed-in owner (issue 317). On a hub whose dashboard asks
 * nobody to sign in — the private default — the page says why, offers the
 * switch that fixes it, and keeps the server command as the second way.
 *
 * Deliberately dashboard-only — no MCP App surface (MASTERPLAN §4 rule 8).
 */
import { type ReactNode, useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";

import {
  Button,
  Callout,
  Card,
  CardHeader,
  Disclosure,
  ErrorState,
  LabeledInput,
  LoadingState,
  PageHeader,
  RestartCallout,
  StatusPill,
  useToast,
} from "../components";
import type {
  BackupLastRun,
  BackupSchedule,
  BackupTargetInfo,
  BackupTargetsResponse,
  ModeStatus,
  SetupStatus,
  UpdateCheckResponse,
  VaultPushRecord,
  VaultRemoteInfo,
  VaultRemotesResponse,
} from "../lib/api/client";
import { ApiError, api } from "../lib/api/client";
import { docsUrl } from "../lib/docs";
import { saveBlob } from "../lib/download";
import { describeApiError } from "../lib/errors";
import { exactTime, formatRelative } from "../lib/format";
import { POLL_INITIAL_MS } from "../lib/polling";
import { DownloadIcon } from "../shell/icons";
import "./settings.css";

/** Plain-language names for a folder's kind — never the config's own word. */
const KIND_LABEL: Record<string, string> = {
  local_directory: "Folder",
};

/** What a backup holds — palaia_hub.backup: the whole hub home except each
 * memory's search index. */
const WHATS_INCLUDED =
  "All memories with their history, palaia's settings, your owner account, every AI app's " +
  "access key, keys saved for add-ons and connected tools, and your automations and webhooks. " +
  "The search index is left out; palaia rebuilds it from your notes after a restore.";

/** One archive from inside palaia's container, streamed to the machine you
 * type this on. `docker cp` cannot read the container's /tmp (a tmpfs), so
 * the file comes out through standard output instead. */
const DOCKER_BACKUP_COMMAND =
  "docker exec palaia-hub sh -c 'palaia-hub backup --out /tmp/palaia-backup.tar.gz >&2 " +
  "&& cat /tmp/palaia-backup.tar.gz && rm /tmp/palaia-backup.tar.gz' > palaia-backup.tar.gz";
const PLAIN_BACKUP_COMMAND = "palaia-hub backup";

const STORE_NAME: Record<string, string> = {
  umbrel: "umbrelOS",
  casaos: "CasaOS",
  runtipi: "Runtipi",
  truenas: "TrueNAS",
  home_assistant: "Home Assistant",
};

function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} bytes`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} KB`;
  if (bytes < 1024 * 1024 * 1024) return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  return `${(bytes / (1024 * 1024 * 1024)).toFixed(2)} GB`;
}

function formatInterval(hours: number): string {
  if (hours % 24 === 0) {
    const days = hours / 24;
    return days === 1 ? "Every day" : `Every ${days} days`;
  }
  return hours === 1 ? "Every hour" : `Every ${hours} h`;
}

function retentionLine(target: BackupTargetInfo): string | null {
  if (target.keep_last === undefined) return null;
  if (target.keep_last === null) return "keeps every backup";
  return `keeps the newest ${target.keep_last}`;
}

/** The newest run across every folder, for the status at the top. */
function newestRun(data: BackupTargetsResponse | null): BackupLastRun | null {
  if (!data) return null;
  let newest: BackupLastRun | null = null;
  for (const target of data.targets) {
    if (target.last_run && (!newest || target.last_run.finished_at > newest.finished_at)) {
      newest = target.last_run;
    }
  }
  return newest;
}

function copy(text: string, toast: ReturnType<typeof useToast>) {
  navigator.clipboard.writeText(text).then(
    () => toast.show("Command copied."),
    () => toast.show("Couldn't copy. Select the text and copy it yourself."),
  );
}

function CommandLine({ command }: { command: string }) {
  const toast = useToast();
  return (
    <div className="snippet">
      <code>{command}</code>
      <Button size="sm" onClick={() => copy(command, toast)}>
        Copy
      </Button>
    </div>
  );
}

/** The server-side way to take a backup, for the deployment palaia reports. */
function ServerBackupHelp({ deployment }: { deployment: string | null }) {
  const store = deployment ? STORE_NAME[deployment] : undefined;
  if (store) {
    return (
      <>
        <p>
          {store} runs palaia in its own container. Open a terminal for the palaia app there and
          run this; it writes the file into the folder you are in:
        </p>
        <CommandLine command={PLAIN_BACKUP_COMMAND} />
      </>
    );
  }
  return (
    <>
      <p>Installed with the palaia installer or Docker Compose, run this on the server:</p>
      <CommandLine command={DOCKER_BACKUP_COMMAND} />
      {deployment === "compose" ? null : (
        <>
          <p>Installed without Docker, run this instead:</p>
          <CommandLine command={PLAIN_BACKUP_COMMAND} />
        </>
      )}
      <p>Either way you get one file in the folder you ran it in. Store it like a password.</p>
    </>
  );
}

/** The blocked state: why, the control that fixes it, and the server
 * command as the second way. */
function NeedsSignIn({
  mode,
  setup,
  owner,
  deployment,
  onTurnedOn,
}: {
  mode: ModeStatus | null;
  setup: SetupStatus | null;
  owner: boolean | null;
  deployment: string | null;
  onTurnedOn: (status: ModeStatus) => void;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Saved but not yet running: the restart is the one step left.
  const pendingRestart =
    !!mode &&
    mode.restart_required &&
    mode.oauth_enabled &&
    (mode.configured_mode !== "locked" || mode.dashboard_require_sign_in === true);

  async function turnOn() {
    if (!mode) return;
    setBusy(true);
    setError(null);
    try {
      const body: Parameters<typeof api.changeMode>[0] = { dashboard_require_sign_in: true };
      if (!mode.oauth_enabled) {
        body.oauth_enabled = true;
        body.oauth_issuer = mode.oauth_issuer ?? window.location.origin;
      }
      onTurnedOn(await api.changeMode(body));
    } catch (err) {
      setError(describeApiError(err));
    } finally {
      setBusy(false);
    }
  }

  let fix: ReactNode;
  if (pendingRestart) {
    fix = (
      <RestartCallout supported={setup?.restart_supported ?? false}>
        <p>Dashboard sign-in is turned on. After the restart, sign in and download your backup here.</p>
      </RestartCallout>
    );
  } else {
    fix = (
      <Callout
        tone="warn"
        title="Backups need dashboard sign-in"
        actions={
          owner === false ? (
            <Link className="btn btn--primary" to="/onboarding">
              Create the owner account
            </Link>
          ) : (
            <Button variant="primary" loading={busy} disabled={!mode} onClick={() => void turnOn()}>
              {busy ? "Turning on…" : "Turn on dashboard sign-in"}
            </Button>
          )
        }
      >
        <p>
          Backups contain your access keys, so palaia only offers them after you sign in.
          {owner === false ? " Sign-in needs an owner account first." : " palaia restarts once to apply it."}
        </p>
        {error ? (
          <p className="field__error" role="alert">
            {error}
          </p>
        ) : null}
      </Callout>
    );
  }

  return (
    <div className="stack stack--3" data-testid="backup-needs-sign-in">
      {fix}
      <Disclosure summary="Back up from the server instead">
        <ServerBackupHelp deployment={deployment} />
      </Disclosure>
    </div>
  );
}

function BackupCard({
  data,
  blocked,
  mode,
  setup,
  owner,
  deployment,
  onTurnedOn,
}: {
  data: BackupTargetsResponse | null;
  blocked: boolean;
  mode: ModeStatus | null;
  setup: SetupStatus | null;
  owner: boolean | null;
  deployment: string | null;
  onTurnedOn: (status: ModeStatus) => void;
}) {
  const [downloading, setDownloading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const last = newestRun(data);

  // Issue 382: fetched through the client, so an expired session goes to
  // sign-in and any other refusal shows in palaia's own words.
  async function download() {
    setDownloading(true);
    setError(null);
    try {
      const file = await api.downloadBackup();
      saveBlob(file.blob, file.filename ?? "palaia-backup.tar.gz");
    } catch (err) {
      setError(describeApiError(err));
    } finally {
      setDownloading(false);
    }
  }

  return (
    <Card data-testid="backup-card">
      <CardHeader
        title="Backup"
        description="Download a copy of your memories and settings."
        actions={
          last ? (
            last.ok ? (
              <StatusPill tone="ok" title={exactTime(last.finished_at * 1000)}>
                Backed up {formatRelative(last.finished_at)}
              </StatusPill>
            ) : (
              <StatusPill tone="error" title={exactTime(last.finished_at * 1000)}>
                Last backup failed
              </StatusPill>
            )
          ) : undefined
        }
      />
      <div className="settings-body">
        {blocked ? (
          <NeedsSignIn
            mode={mode}
            setup={setup}
            owner={owner}
            deployment={deployment}
            onTurnedOn={onTurnedOn}
          />
        ) : (
          <div className="row row--wrap">
            <Button variant="primary" loading={downloading} onClick={() => void download()}>
              {downloading ? (
                "Preparing the file…"
              ) : (
                <>
                  <DownloadIcon className="icon" />
                  Download backup
                </>
              )}
            </Button>
            {error ? <p className="field__error">{error}</p> : null}
          </div>
        )}
        <p className="t-sm" data-testid="backup-security-note">
          <strong>Includes private data and access keys.</strong> Anyone with the file can use them,
          so store it like a password.
        </p>
        <Disclosure summary="What's included?">
          <p>{WHATS_INCLUDED}</p>
          <p>
            <a href={docsUrl("/backup-restore/")} target="_blank" rel="noreferrer">
              How to restore a backup
            </a>
          </p>
        </Disclosure>
      </div>
    </Card>
  );
}

function LastRunLine({ lastRun }: { lastRun: BackupLastRun | null }) {
  if (!lastRun) {
    return <span className="t-sm t-muted">No backup written here yet.</span>;
  }
  const who = lastRun.trigger === "schedule" ? "on schedule" : "on request";
  if (lastRun.ok) {
    return (
      <span className="row row--wrap">
        <StatusPill tone="ok">Backed up</StatusPill>
        <span className="t-sm t-muted" title={exactTime(lastRun.finished_at * 1000)}>
          {formatRelative(lastRun.finished_at)} ({who})
          {lastRun.bytes_written !== null ? ` · ${formatSize(lastRun.bytes_written)}` : ""}
        </span>
      </span>
    );
  }
  return (
    <span className="stack stack--1">
      <span className="row row--wrap">
        <StatusPill tone="error">Failed</StatusPill>
        <span className="t-sm t-muted" title={exactTime(lastRun.finished_at * 1000)}>
          {formatRelative(lastRun.finished_at)} ({who})
        </span>
      </span>
      {lastRun.reason ? <span className="field__error">{lastRun.reason}</span> : null}
    </span>
  );
}

function TargetRow({
  target,
  pending,
  error,
  onRun,
}: {
  target: BackupTargetInfo;
  pending: boolean;
  error: string | null;
  onRun: () => void;
}) {
  const busy = pending || target.running;
  const retention = retentionLine(target);
  return (
    <li className="listrow settings-row--top" data-testid={`backup-target-${target.name}`}>
      <span className="listrow__main stack stack--2">
        <span className="listrow__title">{target.name}</span>
        <span className="listrow__desc">
          {KIND_LABEL[target.kind] ?? target.kind} <code>{target.destination}</code>
          {retention ? ` · ${retention}` : null}
        </span>
        <LastRunLine lastRun={target.last_run} />
        {error ? <span className="field__error">{error}</span> : null}
      </span>
      <span className="listrow__trail">
        <Button
          size="sm"
          onClick={onRun}
          disabled={busy}
          loading={busy}
          aria-label={`Back up now into ${target.name}`}
        >
          {busy ? "Backing up…" : "Back up now"}
        </Button>
      </span>
    </li>
  );
}

function ScheduleLine({ schedule }: { schedule: BackupSchedule }) {
  if (schedule.running || schedule.next_run_at === null) {
    return <p className="t-sm t-muted">Backing up now.</p>;
  }
  return (
    <p className="t-sm t-muted">
      Next: {formatRelative(schedule.next_run_at)}
      {schedule.last_pass_at !== null ? ` · last started ${formatRelative(schedule.last_pass_at)}` : ""}.
    </p>
  );
}

function AutomaticBackupsCard({
  data,
  pending,
  runErrors,
  onRun,
}: {
  data: BackupTargetsResponse;
  pending: Record<string, boolean>;
  runErrors: Record<string, string | null>;
  onRun: (name: string) => void;
}) {
  const { schedule, targets } = data;
  return (
    <Card data-testid="backup-schedule">
      <CardHeader
        title="Automatic backups"
        description="palaia can save a backup into a folder by itself, for example an external drive."
        actions={
          schedule ? (
            <StatusPill tone="ok">{formatInterval(schedule.interval_hours)}</StatusPill>
          ) : (
            <StatusPill tone="neutral">Off</StatusPill>
          )
        }
      />
      {targets.length > 0 ? (
        <ul className="settings-rows">
          {targets.map((target) => (
            <TargetRow
              key={target.name}
              target={target}
              pending={!!pending[target.name]}
              error={runErrors[target.name] ?? null}
              onRun={() => onRun(target.name)}
            />
          ))}
        </ul>
      ) : null}
      <div className="settings-body">
        {targets.length === 0 ? (
          <p className="t-sm t-muted">No backup folders yet.</p>
        ) : schedule ? (
          <ScheduleLine schedule={schedule} />
        ) : (
          <p className="t-sm t-muted">palaia backs up into these folders only when you ask.</p>
        )}
        <Disclosure summary={targets.length === 0 ? "How to add a folder" : "Change folders or schedule"}>
          <p>
            Folders and the schedule are set in <code>config.yaml</code> on the server palaia runs
            on. For example, a folder that keeps a week of daily backups:
          </p>
          <pre className="snippet snippet--block">
            <code>
              {"backup:\n  interval_hours: 24\n  targets:\n    - type: local_directory\n      name: nas\n      path: /mnt/nas/palaia-backups\n      keep_last: 7"}
            </code>
          </pre>
          <p>
            Then restart palaia.{" "}
            <a href={docsUrl("/backup-restore/")} target="_blank" rel="noreferrer">
              More about backup folders
            </a>
          </p>
        </Disclosure>
      </div>
    </Card>
  );
}

function LastPushLine({ lastPush }: { lastPush: VaultPushRecord | null }) {
  if (!lastPush) {
    return <span className="t-sm t-muted">Not copied yet.</span>;
  }
  const who = lastPush.trigger === "schedule" ? "on schedule" : "on request";
  if (lastPush.ok) {
    return (
      <span className="row row--wrap">
        <StatusPill tone="ok">Copied</StatusPill>
        <span className="t-sm t-muted" title={exactTime(lastPush.finished_at * 1000)}>
          {formatRelative(lastPush.finished_at)} ({who})
        </span>
      </span>
    );
  }
  return (
    <span className="stack stack--1">
      <span className="row row--wrap">
        <StatusPill tone="error">Failed</StatusPill>
        <span className="t-sm t-muted">
          {formatRelative(lastPush.finished_at)} ({who})
        </span>
      </span>
      {lastPush.reason ? <span className="field__error">{lastPush.reason}</span> : null}
    </span>
  );
}

function VaultRemoteForm({
  entry,
  onSaved,
  onCancel,
}: {
  entry: VaultRemoteInfo;
  onSaved: () => void;
  onCancel: () => void;
}) {
  const current = entry.remote;
  const [url, setUrl] = useState(current?.url ?? "");
  const [branch, setBranch] = useState(current?.branch ?? "main");
  const [username, setUsername] = useState(
    current && current.username !== "x-access-token" ? current.username : "",
  );
  const [token, setToken] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function save() {
    setSaving(true);
    setError(null);
    try {
      await api.saveVaultRemote(entry.vault, {
        url: url.trim(),
        branch: branch.trim() || undefined,
        username: username.trim() || undefined,
        token: token.trim() || undefined,
      });
      onSaved();
    } catch (err) {
      setError(describeApiError(err));
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="settings-form" data-testid={`vault-remote-form-${entry.vault}`}>
      <LabeledInput
        label="Repository address"
        placeholder="https://github.com/you/notes.git"
        hint="The https address of an empty repository you own."
        value={url}
        onChange={(event) => setUrl(event.target.value)}
      />
      <LabeledInput
        label="Branch"
        hint="palaia never overwrites changes it didn't make. Use a branch only this memory writes to."
        value={branch}
        onChange={(event) => setBranch(event.target.value)}
      />
      <LabeledInput
        label="User name"
        optional
        placeholder="x-access-token"
        hint="Leave empty for GitHub. Other hosts may want your account name."
        value={username}
        onChange={(event) => setUsername(event.target.value)}
      />
      <LabeledInput
        label="Access token"
        optional={current?.has_token}
        type="password"
        autoComplete="off"
        placeholder={current?.has_token ? "Stored — type a new one to replace it" : ""}
        hint={`A token from your Git host that may write to this repository (on GitHub: a fine-grained token with "Contents: read and write"). palaia stores it encrypted and never shows it again.${
          current?.has_token ? " Leave empty to keep the stored one." : ""
        }`}
        value={token}
        onChange={(event) => setToken(event.target.value)}
      />
      {error ? <p className="field__error">{error}</p> : null}
      <div className="settings-form__actions">
        <Button variant="primary" onClick={() => void save()} disabled={saving || !url.trim()} loading={saving}>
          {saving ? "Saving…" : "Save"}
        </Button>
        <Button onClick={onCancel} disabled={saving}>
          Cancel
        </Button>
      </div>
    </div>
  );
}

/**
 * Issue 438: copy a memory's notes into a Git repository the owner names —
 * for example a private GitHub repository. Only the notes leave palaia (no
 * keys), which is why this may go to a third-party host when a backup may
 * not. Hidden on a hub without a secret store (404): nowhere to keep the
 * token.
 */
function VaultRemotesCard({ scheduled }: { scheduled: boolean }) {
  const toast = useToast();
  const [data, setData] = useState<VaultRemotesResponse | null>(null);
  const [hidden, setHidden] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [editing, setEditing] = useState<string | null>(null);
  const [pending, setPending] = useState<Record<string, boolean>>({});
  const [errors, setErrors] = useState<Record<string, string | null>>({});

  const load = useCallback(async () => {
    try {
      setData(await api.listVaultRemotes());
      setLoadError(null);
    } catch (err) {
      if (err instanceof ApiError && err.status === 404) {
        setHidden(true);
        return;
      }
      setLoadError(describeApiError(err));
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const somethingPushing = !!data && data.vaults.some((entry) => entry.pushing);
  useEffect(() => {
    if (!somethingPushing) return;
    const timer = window.setTimeout(() => void load(), POLL_INITIAL_MS);
    return () => window.clearTimeout(timer);
  }, [somethingPushing, data, load]);

  async function push(vault: string) {
    setPending((prev) => ({ ...prev, [vault]: true }));
    setErrors((prev) => ({ ...prev, [vault]: null }));
    try {
      await api.pushVault(vault);
      toast.show(`Copied ${vault} to Git.`);
    } catch (err) {
      setErrors((prev) => ({ ...prev, [vault]: describeApiError(err) }));
    } finally {
      setPending((prev) => ({ ...prev, [vault]: false }));
      await load();
    }
  }

  async function remove(vault: string) {
    setPending((prev) => ({ ...prev, [vault]: true }));
    setErrors((prev) => ({ ...prev, [vault]: null }));
    try {
      await api.removeVaultRemote(vault);
      toast.show(`${vault} is no longer copied to Git.`);
    } catch (err) {
      setErrors((prev) => ({ ...prev, [vault]: describeApiError(err) }));
    } finally {
      setPending((prev) => ({ ...prev, [vault]: false }));
      await load();
    }
  }

  if (hidden) return null;

  return (
    <Card data-testid="vault-remotes">
      <CardHeader
        title="Copy notes to Git"
        description={`Push a memory's notes and history to a private Git repository. No keys are included.${
          scheduled ? " Every scheduled backup copies them too." : " They are copied when you ask."
        }`}
      />
      {loadError ? (
        <div className="settings-body">
          <ErrorState title="Couldn't load your memories" details={loadError} onRetry={() => void load()} />
        </div>
      ) : null}
      {!data && !loadError ? (
        <div className="settings-body">
          <LoadingState label="Loading your memories…" lines={2} />
        </div>
      ) : null}
      {data && data.vaults.length === 0 ? (
        <p className="empty--inline">No memories yet.</p>
      ) : null}
      {data && data.vaults.length > 0 ? (
        <ul className="settings-rows">
          {data.vaults.map((entry) => {
            const busy = !!pending[entry.vault] || entry.pushing;
            return (
              <li key={entry.vault} data-testid={`vault-remote-${entry.vault}`}>
                <div className="listrow settings-row--top">
                  <span className="listrow__main stack stack--2">
                    <span className="listrow__title">{entry.vault}</span>
                    {entry.remote ? (
                      <span className="listrow__desc">
                        <code>{entry.remote.url}</code> · branch <code>{entry.remote.branch}</code>
                      </span>
                    ) : (
                      <span className="listrow__desc">Not copied anywhere.</span>
                    )}
                    {entry.remote && editing !== entry.vault ? (
                      <LastPushLine lastPush={entry.last_push} />
                    ) : null}
                    {errors[entry.vault] ? (
                      <span className="field__error">{errors[entry.vault]}</span>
                    ) : null}
                  </span>
                  {editing === entry.vault ? null : (
                    <span className="listrow__trail row row--wrap">
                      {entry.remote ? (
                        <>
                          <Button
                            size="sm"
                            onClick={() => void push(entry.vault)}
                            disabled={busy || !entry.registered}
                            loading={busy}
                            aria-label={`Copy ${entry.vault} now`}
                          >
                            {busy ? "Copying…" : "Copy now"}
                          </Button>
                          <Button size="sm" onClick={() => setEditing(entry.vault)} disabled={busy}>
                            Change
                          </Button>
                          <Button
                            variant="destructive"
                            size="sm"
                            onClick={() => void remove(entry.vault)}
                            disabled={busy}
                            aria-label={`Stop copying ${entry.vault}`}
                          >
                            Stop copying
                          </Button>
                        </>
                      ) : entry.registered ? (
                        <Button size="sm" onClick={() => setEditing(entry.vault)}>
                          Set up
                        </Button>
                      ) : null}
                    </span>
                  )}
                </div>
                {editing === entry.vault ? (
                  <VaultRemoteForm
                    entry={entry}
                    onCancel={() => setEditing(null)}
                    onSaved={() => {
                      setEditing(null);
                      toast.show(`Saved where ${entry.vault} is copied.`);
                      void load();
                    }}
                  />
                ) : null}
              </li>
            );
          })}
        </ul>
      ) : null}
    </Card>
  );
}

const HEADER = (
  <PageHeader
    title="Backups"
    description="Keep a copy of your memories and settings somewhere safe."
    back={{ to: "/settings", label: "Settings" }}
  />
);

export function Backups() {
  const toast = useToast();
  const [data, setData] = useState<BackupTargetsResponse | null>(null);
  const [blocked, setBlocked] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [pending, setPending] = useState<Record<string, boolean>>({});
  const [runErrors, setRunErrors] = useState<Record<string, string | null>>({});
  const [mode, setMode] = useState<ModeStatus | null>(null);
  const [setup, setSetup] = useState<SetupStatus | null>(null);
  const [owner, setOwner] = useState<boolean | null>(null);
  const [update, setUpdate] = useState<UpdateCheckResponse | null>(null);

  const load = useCallback(async () => {
    try {
      setData(await api.listBackupTargets());
      setBlocked(false);
      setLoadError(null);
    } catch (err) {
      if (err instanceof ApiError && err.status === 403) {
        setBlocked(true);
        setLoadError(null);
        return;
      }
      setLoadError(describeApiError(err));
    }
  }, []);

  useEffect(() => {
    let cancelled = false;
    api
      .listBackupTargets()
      .then((next) => {
        if (!cancelled) setData(next);
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        // 403: this dashboard asks nobody to sign in (issue 317) — a state
        // with a fix, not an error.
        if (err instanceof ApiError && err.status === 403) setBlocked(true);
        else setLoadError(describeApiError(err));
      });
    return () => {
      cancelled = true;
    };
  }, []);

  // What the blocked state needs: whether sign-in is already saved, whether
  // palaia can restart itself, whether an owner exists, and which kind of
  // install this is (for the server command). Each is optional.
  useEffect(() => {
    if (!blocked) return;
    let cancelled = false;
    api
      .mode()
      .then((value) => !cancelled && setMode(value))
      .catch(() => {});
    api
      .setupStatus()
      .then((value) => !cancelled && setSetup(value))
      .catch(() => {});
    api
      .ownerAccount()
      .then((value) => !cancelled && setOwner(value.configured))
      .catch(() => {});
    api
      .updateCheck()
      .then((value) => !cancelled && setUpdate(value))
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, [blocked]);

  // While a backup is being written — by the schedule, or by a click in
  // another tab — look again every few seconds. Nothing running, nothing polled.
  const somethingRunning =
    !!data && (data.targets.some((target) => target.running) || !!data.schedule?.running);
  useEffect(() => {
    if (!somethingRunning) return;
    const timer = window.setTimeout(() => void load(), POLL_INITIAL_MS);
    return () => window.clearTimeout(timer);
  }, [somethingRunning, data, load]);

  async function run(name: string) {
    setPending((prev) => ({ ...prev, [name]: true }));
    setRunErrors((prev) => ({ ...prev, [name]: null }));
    try {
      const result = await api.runBackupTarget(name);
      toast.show(`Backed up into ${name}: ${result.artifact}`);
    } catch (err) {
      setRunErrors((prev) => ({ ...prev, [name]: describeApiError(err) }));
    } finally {
      setPending((prev) => ({ ...prev, [name]: false }));
      await load();
    }
  }

  if (loadError && !data) {
    return (
      <div className="stack narrow">
        {HEADER}
        <ErrorState
          title="Couldn't load your backups"
          details={loadError}
          onRetry={() => {
            setLoadError(null);
            void load();
          }}
        >
          palaia answered with an error.
        </ErrorState>
      </div>
    );
  }

  if (!data && !blocked) {
    return (
      <div className="stack narrow">
        {HEADER}
        <LoadingState label="Loading your backups…" />
      </div>
    );
  }

  return (
    <div className="stack narrow">
      {HEADER}
      <BackupCard
        data={data}
        blocked={blocked}
        mode={mode}
        setup={setup}
        owner={owner}
        deployment={update?.deployment ?? null}
        onTurnedOn={(status) => {
          setMode(status);
          api
            .setupStatus()
            .then(setSetup)
            .catch(() => {});
        }}
      />
      {data ? (
        <AutomaticBackupsCard
          data={data}
          pending={pending}
          runErrors={runErrors}
          onRun={(name) => void run(name)}
        />
      ) : null}
      {data ? <VaultRemotesCard scheduled={data.schedule !== null} /> : null}
      {blocked ? (
        <p className="t-sm t-muted">
          Automatic backups and copies to Git are set up here too, once dashboard sign-in is on.
        </p>
      ) : null}
    </div>
  );
}
