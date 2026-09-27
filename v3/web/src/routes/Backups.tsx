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
  useToast,
  Waiting,
} from "../components";
import type {
  BackupLastRun,
  BackupSchedule,
  BackupTargetInfo,
  BackupTargetsResponse,
} from "../lib/api/client";
import { api } from "../lib/api/client";
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
    </div>
  );
}
