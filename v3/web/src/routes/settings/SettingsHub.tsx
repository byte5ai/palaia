/**
 * Settings: one card that says what this palaia is and how it runs, then
 * one row per area, each with its current state in its description (Home
 * Assistant's and umbrelOS's settings pattern).
 */
import { type ReactNode, useEffect, useState } from "react";
import { useOutletContext } from "react-router-dom";

import {
  Card,
  ListRow,
  RestartButton,
  RestartCallout,
  Segmented,
  StatusPill,
} from "../../components";
import type {
  BackupTargetsResponse,
  ModeStatus,
  SetupStatus,
  SignInInfo,
  TelegramStatus,
  UpdateCheckResponse,
} from "../../lib/api/client";
import { api, ApiError } from "../../lib/api/client";
import type { EventStreamState } from "../../lib/events";
import { hubHealth } from "../../lib/health";
import { isHubMode, MODE_LABEL } from "../../lib/mode";
import { useSession } from "../../lib/session";
import { type ThemeMode, useTheme } from "../../lib/theme";
import { __version__ } from "../../version";
import {
  AppearanceIcon,
  BackupIcon,
  InfoIcon,
  LockIcon,
  PalaiaMark,
  SlidersIcon,
  TelegramIcon,
} from "../../shell/icons";

/** `undefined` while loading, `null` when the hub could not answer. */
type Loaded<T> = T | null | undefined;

function useLoad<T>(load: () => Promise<T>): Loaded<T> {
  const [value, setValue] = useState<Loaded<T>>(undefined);
  useEffect(() => {
    let cancelled = false;
    load()
      .then((result) => {
        if (!cancelled) setValue(result);
      })
      .catch(() => {
        if (!cancelled) setValue(null);
      });
    return () => {
      cancelled = true;
    };
    // `load` is a stable module-level call in every use below.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  return value;
}

/** Backups answer 401/403 until the dashboard asks for sign-in. */
function useBackupState(): Loaded<BackupTargetsResponse | "needs-sign-in"> {
  const [value, setValue] = useState<Loaded<BackupTargetsResponse | "needs-sign-in">>(undefined);
  useEffect(() => {
    let cancelled = false;
    api
      .listBackupTargets()
      .then((result) => {
        if (!cancelled) setValue(result);
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        const gated = err instanceof ApiError && (err.status === 401 || err.status === 403);
        setValue(gated ? "needs-sign-in" : null);
      });
    return () => {
      cancelled = true;
    };
  }, []);
  return value;
}

function Fact({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="stack stack--1">
      <dt className="t-over">{label}</dt>
      <dd style={{ margin: 0 }}>{children}</dd>
    </div>
  );
}

function accessSummary(mode: ModeStatus | null | undefined, signIn: SignInInfo | undefined): string {
  if (mode === undefined) return "Loading…";
  if (mode === null) return "Who can reach palaia, and who has to sign in";
  const name = isHubMode(mode.active_mode) ? MODE_LABEL[mode.active_mode] : mode.active_mode;
  const dashboard = signIn?.required ? "Dashboard sign-in on" : "Dashboard sign-in off";
  return `${name} · ${dashboard}`;
}

function backupSummary(state: Loaded<BackupTargetsResponse | "needs-sign-in">): ReactNode {
  if (state === undefined) return "Loading…";
  if (state === "needs-sign-in") return "Turn on dashboard sign-in to download backups";
  if (state === null) return "Download a copy of your memories and settings";
  if (state.schedule) return `Automatic backups every ${state.schedule.interval_hours} h`;
  if (state.targets.length > 0) return `${state.targets.length} backup folder${state.targets.length === 1 ? "" : "s"}`;
  return "Download a copy of your memories and settings";
}

function telegramSummary(status: Loaded<TelegramStatus>): string {
  if (status === undefined) return "Loading…";
  if (status === null || status.bots.length === 0) return "Not set up";
  return `${status.bots.length} bot${status.bots.length === 1 ? "" : "s"}`;
}

function updateSummary(check: Loaded<UpdateCheckResponse>): ReactNode {
  if (check?.state === "update_available") {
    return `Update available: ${check.latest_version ?? "new version"}`;
  }
  return `Version ${__version__}`;
}

const THEME_OPTIONS: { value: ThemeMode; label: string }[] = [
  { value: "system", label: "System" },
  { value: "light", label: "Light" },
  { value: "dark", label: "Dark" },
];

export function SettingsHub() {
  const stream = useOutletContext<EventStreamState | undefined>();
  const health = hubHealth(stream ?? { connection: "connecting", health: null });
  const { mode: theme, setMode: setTheme } = useTheme();
  const { session, signOut } = useSession();
  const info = useLoad(() => api.info());
  const setup = useLoad<SetupStatus>(() => api.setupStatus());
  const mode = useLoad(() => api.mode());
  const telegram = useLoad(() => api.telegramStatus());
  const update = useLoad(() => api.updateCheck());
  const backups = useBackupState();

  const signIn = info?.sign_in as SignInInfo | undefined;
  const runningMode = isHubMode(info?.mode) ? MODE_LABEL[info.mode] : "…";
  const version = typeof info?.version === "string" ? info.version : __version__;
  const channel = typeof info?.channel === "string" ? info.channel : null;
  const signedInAs = session?.signed_in ? session.username : null;

  return (
    <div className="stack narrow">
      <Card>
        <div className="card__body stack stack--4">
          <div className="row" style={{ alignItems: "flex-start" }}>
            <PalaiaMark className="brand__mark" style={{ width: 40, height: 40 }} />
            <div className="grow">
              <h2 className="card__title">palaia {version}</h2>
              <p className="t-sm t-muted">{channel ? `${channel} channel` : " "}</p>
            </div>
            <StatusPill tone={health.tone}>{health.label}</StatusPill>
          </div>
          <dl className="tiles" style={{ gridTemplateColumns: "repeat(auto-fit, minmax(150px, 1fr))", gap: "var(--space-4)", margin: 0 }}>
            <Fact label="Access">{runningMode}</Fact>
            <Fact label="Address">
              <span className="t-mono">{window.location.host}</span>
            </Fact>
            <Fact label="Dashboard sign-in">
              {signIn === undefined ? "…" : signIn.required ? "On" : "Off"}
            </Fact>
            {signedInAs ? <Fact label="Signed in as">{signedInAs}</Fact> : null}
          </dl>
          <div className="row row--wrap">
            {setup?.restart_supported ? <RestartButton /> : null}
            {signedInAs ? (
              <button type="button" className="btn" onClick={() => void signOut()}>
                Sign out
              </button>
            ) : null}
          </div>
        </div>
      </Card>

      {setup?.restart_required ? <RestartCallout supported={setup.restart_supported} /> : null}

      <Card>
        <ListRow
          to="/settings/access"
          icon={<LockIcon className="icon" />}
          title="Access & sign-in"
          description={accessSummary(mode, signIn)}
        />
        <ListRow
          to="/settings/backups"
          icon={<BackupIcon className="icon" />}
          title="Backups"
          description={backupSummary(backups)}
        />
        <ListRow
          to="/settings/telegram"
          icon={<TelegramIcon className="icon" />}
          title="Telegram"
          description={telegramSummary(telegram)}
        />
      </Card>

      <Card>
        <ListRow
          setting
          icon={<AppearanceIcon className="icon" />}
          title="Appearance"
          description="Light or dark, or follow this device."
          labelId="appearance-label"
          trailing={
            <Segmented
              ariaLabel="Appearance"
              options={THEME_OPTIONS}
              value={theme}
              onChange={setTheme}
            />
          }
        />
        <ListRow
          to="/settings/advanced"
          icon={<SlidersIcon className="icon" />}
          title="Advanced"
          description="Tool sets and tool names. Most setups never need these."
        />
        <ListRow
          to="/settings/about"
          icon={<InfoIcon className="icon" />}
          title="About & updates"
          description={updateSummary(update)}
          trailing={
            update?.state === "update_available" ? (
              <StatusPill tone="info">Update available</StatusPill>
            ) : undefined
          }
        />
      </Card>
    </div>
  );
}
