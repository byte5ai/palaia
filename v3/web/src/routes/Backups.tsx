/**
 * The backup screen (issue 438, the dashboard half of issue 297): the folders
 * this hub writes its own backup into, how each one's last backup went,
 * whether it does so on a schedule — and "Back up now" per folder.
 *
 * Reads `GET /api/backup/targets` and runs `POST /api/backup/targets/{name}
 * /run`. The file never passes through this browser: the hub writes it
 * straight into the folder, which is why this screen can offer a button for
 * a file of any size (the download on Home cannot).
 *
 * Deliberately dashboard-only — no MCP App surface (MASTERPLAN §4 rule 8,
 * §5.7): every backup is the full archive, keys included, and administering
 * where that goes is exactly the security-sensitive administration the
 * rule keeps out of chat clients. On a hub whose dashboard has no sign-in
 * the hub refuses these routes (issue 317) and this screen shows its words,
 * which name the command-line way instead.
 */
import { useCallback, useEffect, useState } from "react";

import {
  Badge,
  Button,
  Card,
  CardBody,
  CardHead,
  EmptyState,
  LabeledInput,
  useToast,
  Waiting,
} from "../components";
import type {
  BackupLastRun,
  BackupSchedule,
  BackupTargetInfo,
  BackupTargetsResponse,
  VaultPushRecord,
  VaultRemoteInfo,
  VaultRemotesResponse,
} from "../lib/api/client";
import { ApiError, api } from "../lib/api/client";
import { docsUrl } from "../lib/docs";
import { describeApiError } from "../lib/errors";
import { formatRelative } from "../lib/format";
import { POLL_INITIAL_MS } from "../lib/polling";
import { BackupIcon, WarningIcon } from "../shell/icons";

/** Plain-language names for a folder's kind — never the config's own word. */
const KIND_LABEL: Record<string, string> = {
  local_directory: "Folder",
};

function formatWhen(epochSeconds: number): string {
  return new Date(epochSeconds * 1000).toLocaleString(undefined, {
    dateStyle: "medium",
    timeStyle: "short",
  });
}

function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} bytes`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} KB`;
  if (bytes < 1024 * 1024 * 1024) return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  return `${(bytes / (1024 * 1024 * 1024)).toFixed(2)} GB`;
}

function formatInterval(hours: number): string {
  if (hours % 24 === 0) {
    const days = hours / 24;
    return days === 1 ? "every day" : `every ${days} days`;
  }
  return hours === 1 ? "every hour" : `every ${hours} h`;
}

function retentionLine(target: BackupTargetInfo): string | null {
  if (target.keep_last === undefined) return null;
  if (target.keep_last === null) return "Keeps every backup";
  return `Keeps the newest ${target.keep_last}`;
}

function ScheduleCard({ schedule }: { schedule: BackupSchedule | null }) {
  return (
    <Card data-testid="backup-schedule">
      <CardHead title="schedule">
        {schedule ? (
          <Badge variant="ok">on</Badge>
        ) : (
          <Badge variant="neutral">off</Badge>
        )}
      </CardHead>
      <CardBody className="stack stack--2">
        {schedule ? (
          <>
            <p className="card__subject">
              palaia backs up into every folder below{" "}
              {formatInterval(schedule.interval_hours)}.
            </p>
            {schedule.running || schedule.next_run_at === null ? (
              <Waiting>Backing up now</Waiting>
            ) : (
              <p className="t-sm t-muted">
                Next: {formatRelative(schedule.next_run_at)} (
                {formatWhen(schedule.next_run_at)}).
              </p>
            )}
            {schedule.last_pass_at !== null ? (
              <p className="t-sm t-muted">
                Last started {formatRelative(schedule.last_pass_at)}.
              </p>
            ) : null}
          </>
        ) : (
          <>
            <p className="card__subject">Only when you ask.</p>
            <p className="t-sm t-muted">
              To have palaia back up by itself, add{" "}
              <code>interval_hours: 24</code> under <code>backup:</code> in{" "}
              <code>config.yaml</code> on the machine it runs on, then restart
              it.
            </p>
          </>
        )}
      </CardBody>
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
        <Badge variant="ok">backed up</Badge>
        <span className="t-sm t-muted">
          {formatRelative(lastRun.finished_at)} ({who})
          {lastRun.bytes_written !== null
            ? ` — ${formatSize(lastRun.bytes_written)}`
            : ""}
        </span>
      </span>
    );
  }
  return (
    <span className="stack stack--2">
      <span className="row row--wrap">
        <Badge variant="risk">failed</Badge>
        <span className="t-sm t-muted">
          {formatRelative(lastRun.finished_at)} ({who})
        </span>
      </span>
      {lastRun.reason ? (
        <span className="field__error">{lastRun.reason}</span>
      ) : null}
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
    <li className="stack stack--2" data-testid={`backup-target-${target.name}`}>
      <div className="row--between">
        <div className="stack stack--2">
          <span className="card__subject">{target.name}</span>
          <span className="t-sm t-muted">
            {KIND_LABEL[target.kind] ?? target.kind}{" "}
            <code>{target.destination}</code>
            {retention ? ` · ${retention}` : null}
          </span>
        </div>
        <Button
          variant="primary"
          size="sm"
          onClick={onRun}
          disabled={busy}
          aria-label={`Back up now into ${target.name}`}
        >
          {busy ? "Backing up…" : "Back up now"}
        </Button>
      </div>
      <LastRunLine lastRun={target.last_run} />
      {error ? <p className="field__error">{error}</p> : null}
    </li>
  );
}

function LastPushLine({ lastPush }: { lastPush: VaultPushRecord | null }) {
  if (!lastPush) {
    return <span className="t-sm t-muted">Not pushed yet.</span>;
  }
  const who = lastPush.trigger === "schedule" ? "on schedule" : "on request";
  if (lastPush.ok) {
    return (
      <span className="row row--wrap">
        <Badge variant="ok">pushed</Badge>
        <span className="t-sm t-muted">
          {formatRelative(lastPush.finished_at)} ({who})
          {lastPush.commit ? ` — ${lastPush.commit.slice(0, 7)}` : ""}
        </span>
      </span>
    );
  }
  return (
    <span className="stack stack--2">
      <span className="row row--wrap">
        <Badge variant="risk">failed</Badge>
        <span className="t-sm t-muted">
          {formatRelative(lastPush.finished_at)} ({who})
        </span>
      </span>
      {lastPush.reason ? (
        <span className="field__error">{lastPush.reason}</span>
      ) : null}
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
    <div className="stack stack--3" data-testid={`vault-remote-form-${entry.vault}`}>
      <LabeledInput
        label="Repository address"
        placeholder="https://github.com/you/notes.git"
        hint="The HTTPS address of an empty repository you own. palaia pushes over HTTPS only."
        value={url}
        onChange={(event) => setUrl(event.target.value)}
      />
      <LabeledInput
        label="Branch"
        hint="palaia never overwrites commits it did not make; use a branch that is empty or only ever written by this memory."
        value={branch}
        onChange={(event) => setBranch(event.target.value)}
      />
      <LabeledInput
        label="User name"
        placeholder="x-access-token"
        hint="Leave empty for GitHub. Other hosts may want your account name with the token."
        value={username}
        onChange={(event) => setUsername(event.target.value)}
      />
      <LabeledInput
        label="Access token"
        type="password"
        autoComplete="off"
        placeholder={
          current?.has_token ? "Stored — type a new one to replace it" : ""
        }
        hint={`A token that may write to this repository (on GitHub: a fine-grained token with "Contents: read and write"). Stored encrypted in the hub's secret store, never shown again.${
          current?.has_token ? " Leave empty to keep the stored one." : ""
        }`}
        value={token}
        onChange={(event) => setToken(event.target.value)}
      />
      {error ? <p className="field__error">{error}</p> : null}
      <div className="row row--wrap">
        <Button
          variant="primary"
          size="sm"
          onClick={() => void save()}
          disabled={saving || !url.trim()}
        >
          {saving ? "Saving…" : "Save"}
        </Button>
        <Button variant="ghost" size="sm" onClick={onCancel} disabled={saving}>
          Cancel
        </Button>
      </div>
    </div>
  );
}

/**
 * Issue 438: push a vault's notes into a git repository the owner names —
 * for example a private GitHub repository. Only the notes leave the hub
 * (no keys, no tokens), which is why this may go to a third-party host when
 * a backup folder may not. Hidden on a hub without a secret store (404):
 * there is nowhere to keep the token.
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
      const result = await api.pushVault(vault);
      toast.show(
        `Pushed ${vault}${result.commit ? ` (${result.commit.slice(0, 7)})` : ""}`,
      );
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
      toast.show(`${vault} is no longer pushed`);
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
      <CardHead title="memories in git" />
      <CardBody className="stack stack--3">
        <p className="t-sm t-muted">
          Push a memory&rsquo;s notes, with their history, into a git
          repository you own — for example a private GitHub repository. Only
          the notes go there: no keys, no tokens.
          {scheduled
            ? " Every scheduled backup pushes them too."
            : " They are pushed when you ask."}
        </p>
        {loadError ? <p className="field__error">{loadError}</p> : null}
        {!data && !loadError ? <Waiting>Loading your memories</Waiting> : null}
        {data && data.vaults.length === 0 ? (
          <p className="t-sm t-muted">No memories yet.</p>
        ) : null}
        {data && data.vaults.length > 0 ? (
          <ul
            className="stack stack--6"
            style={{ listStyle: "none", padding: 0, margin: 0 }}
          >
            {data.vaults.map((entry) => {
              const busy = !!pending[entry.vault] || entry.pushing;
              return (
                <li
                  key={entry.vault}
                  className="stack stack--2"
                  data-testid={`vault-remote-${entry.vault}`}
                >
                  <div className="row--between">
                    <div className="stack stack--2">
                      <span className="card__subject">{entry.vault}</span>
                      {entry.remote ? (
                        <span className="t-sm t-muted">
                          <code>{entry.remote.url}</code> · branch{" "}
                          <code>{entry.remote.branch}</code>
                        </span>
                      ) : (
                        <span className="t-sm t-muted">Not pushed anywhere.</span>
                      )}
                    </div>
                    {editing === entry.vault ? null : entry.remote ? (
                      <div className="row row--wrap">
                        <Button
                          variant="primary"
                          size="sm"
                          onClick={() => void push(entry.vault)}
                          disabled={busy || !entry.registered}
                          aria-label={`Push ${entry.vault} now`}
                        >
                          {busy ? "Pushing…" : "Push now"}
                        </Button>
                        <Button
                          size="sm"
                          onClick={() => setEditing(entry.vault)}
                          disabled={busy}
                        >
                          Change
                        </Button>
                        <Button
                          variant="ghost"
                          size="sm"
                          onClick={() => void remove(entry.vault)}
                          disabled={busy}
                          aria-label={`Stop pushing ${entry.vault}`}
                        >
                          Stop pushing
                        </Button>
                      </div>
                    ) : entry.registered ? (
                      <Button size="sm" onClick={() => setEditing(entry.vault)}>
                        Push to a git repository
                      </Button>
                    ) : null}
                  </div>
                  {editing === entry.vault ? (
                    <VaultRemoteForm
                      entry={entry}
                      onCancel={() => setEditing(null)}
                      onSaved={() => {
                        setEditing(null);
                        toast.show(`Saved where ${entry.vault} is pushed`);
                        void load();
                      }}
                    />
                  ) : entry.remote ? (
                    <LastPushLine lastPush={entry.last_push} />
                  ) : null}
                  {errors[entry.vault] ? (
                    <p className="field__error">{errors[entry.vault]}</p>
                  ) : null}
                </li>
              );
            })}
          </ul>
        ) : null}
      </CardBody>
    </Card>
  );
}

export function Backups() {
  const toast = useToast();
  const [data, setData] = useState<BackupTargetsResponse | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [pending, setPending] = useState<Record<string, boolean>>({});
  const [runErrors, setRunErrors] = useState<Record<string, string | null>>({});

  const load = useCallback(async () => {
    try {
      const next = await api.listBackupTargets();
      setData(next);
      setLoadError(null);
    } catch (err) {
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
        if (!cancelled) setLoadError(describeApiError(err));
      });
    return () => {
      cancelled = true;
    };
  }, []);

  // While a backup is being written — by the schedule, or by a click in
  // another tab — look again every few seconds, so the row settles on its
  // outcome without a reload. Nothing running, nothing polled.
  const somethingRunning =
    !!data &&
    (data.targets.some((target) => target.running) ||
      !!data.schedule?.running);
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
      <Card data-testid="backups-error">
        <CardHead title="backups" />
        <CardBody className="stack stack--3">
          <p className="t-sm">{loadError}</p>
          <div className="row">
            <Button size="sm" onClick={() => void load()}>
              Try again
            </Button>
          </div>
        </CardBody>
      </Card>
    );
  }

  if (!data) {
    return <Waiting>Loading your backup folders</Waiting>;
  }

  return (
    <div className="stack" style={{ gap: 16 }}>
      <Card>
        <CardHead title="backup folders" />
        <CardBody className="stack stack--3">
          {data.targets.length === 0 ? (
            <EmptyState
              mark={<BackupIcon />}
              title="No backup folders yet"
              actions={
                <a
                  className="btn btn--sm"
                  href={docsUrl("/backup-restore/")}
                  target="_blank"
                  rel="noreferrer"
                >
                  How to add one
                </a>
              }
            >
              Name a folder once — an external drive, or a share on your
              network storage — and palaia writes its backup there itself.
              Folders are added in config.yaml on the machine palaia runs on.
            </EmptyState>
          ) : (
            <ul className="stack stack--6" style={{ listStyle: "none", padding: 0, margin: 0 }}>
              {data.targets.map((target) => (
                <TargetRow
                  key={target.name}
                  target={target}
                  pending={!!pending[target.name]}
                  error={runErrors[target.name] ?? null}
                  onRun={() => void run(target.name)}
                />
              ))}
            </ul>
          )}
          <div className="banner banner--warn">
            <WarningIcon className="icon icon--sm" />
            <div>
              <p className="banner__title">Every backup can act as your hub.</p>
              <p className="t-sm t-muted">
                Anyone who has one can read everything in it. Only use a folder
                you&rsquo;d be comfortable storing a password in.
              </p>
            </div>
          </div>
        </CardBody>
      </Card>

      {data.targets.length > 0 ? <ScheduleCard schedule={data.schedule} /> : null}

      <VaultRemotesCard scheduled={data.schedule !== null} />
    </div>
  );
}
