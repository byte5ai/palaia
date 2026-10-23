import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ToastProvider } from "../components/Toast";
import type {
  BackupTargetInfo,
  BackupTargetsResponse,
  ModeStatus,
  VaultRemoteInfo,
} from "../lib/api/client";
import { api, ApiError } from "../lib/api/client";
import { saveBlob } from "../lib/download";
import { formatRelative } from "../lib/format";
import { Backups } from "./Backups";

vi.mock("../lib/download", () => ({ saveBlob: vi.fn() }));

function mount() {
  return render(
    <MemoryRouter>
      <ToastProvider>
        <Backups />
      </ToastProvider>
    </MemoryRouter>,
  );
}

const NOW = Date.now() / 1000;

const NAS: BackupTargetInfo = {
  name: "nas",
  kind: "local_directory",
  destination: "/mnt/nas/palaia-backups",
  carries_full_archive: true,
  secret_safe: true,
  keep_last: 7,
  running: false,
  last_run: {
    finished_at: NOW - 3 * 3600,
    ok: true,
    trigger: "schedule",
    artifact: "palaia-backup-20260926T020000Z.tar.gz",
    bytes_written: 5 * 1024 * 1024,
    pruned: 1,
    duration_seconds: 4.2,
    reason: null,
  },
};

const USB: BackupTargetInfo = {
  name: "usb",
  kind: "local_directory",
  destination: "/media/usb/backups",
  carries_full_archive: true,
  secret_safe: true,
  keep_last: null,
  running: false,
  last_run: {
    finished_at: NOW - 3600,
    ok: false,
    trigger: "manual",
    artifact: null,
    bytes_written: null,
    pruned: 0,
    duration_seconds: null,
    reason: "backup target 'usb' could not write into /media/usb/backups: not mounted",
  },
};

const LOCKED_MODE: ModeStatus = {
  active_mode: "locked",
  configured_mode: "locked",
  restart_required: false,
  host: "127.0.0.1",
  auth_enabled: true,
  oauth_enabled: false,
  oauth_issuer: null,
  dashboard_require_sign_in: null,
  public_url: null,
  tunnel: null,
};

const SCHEDULED: BackupTargetsResponse = {
  targets: [NAS, USB],
  schedule: {
    interval_hours: 24,
    next_run_at: NOW + 5 * 3600,
    last_pass_at: NOW - 19 * 3600,
    running: false,
  },
};

/** Words a person who never read the source should not have to know.
 * (A failed run's reason is the hub's own sentence, shown verbatim.) */
const BANNED = [
  /\bmcp\b/i,
  /\boauth\b/i,
  /\bapi\b/i,
  /\bjson\b/i,
  /\bvault\b/i,
  /\blocal_directory\b/i,
  /\bcron\b/i,
];

beforeEach(() => {
  // Every memory in palaia's data folder unless a test says otherwise.
  vi.spyOn(api, "listVaults").mockResolvedValue([]);
  // A hub without a secret store: the git card hides itself (404).
  vi.spyOn(api, "listVaultRemotes").mockRejectedValue(
    new ApiError("/api/backup/vault-remotes", 404, { detail: "Not Found" }),
  );
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("Backups (issue 438)", () => {
  it("lists every folder with how its last backup went, and the schedule", async () => {
    vi.spyOn(api, "listBackupTargets").mockResolvedValue(SCHEDULED);

    mount();

    const nas = await screen.findByTestId("backup-target-nas");
    expect(nas).toHaveTextContent("/mnt/nas/palaia-backups");
    expect(nas).toHaveTextContent(/keeps the newest 7/i);
    expect(nas).toHaveTextContent(/backed up/i);
    expect(nas).toHaveTextContent(/3 h ago \(on schedule\)/);
    expect(nas).toHaveTextContent("5.0 MB");

    const usb = screen.getByTestId("backup-target-usb");
    expect(usb).toHaveTextContent(/keeps every backup/i);
    expect(usb).toHaveTextContent(/failed/i);
    expect(usb).toHaveTextContent(/not mounted/);

    const schedule = screen.getByTestId("backup-schedule");
    expect(schedule).toHaveTextContent(/every day/i);
    expect(schedule).toHaveTextContent(/next: in 5 h/i);

    // The newest run sets the status at the top: the usb folder failed last.
    expect(within(screen.getByTestId("backup-card")).getByText("Last backup failed")).toBeInTheDocument();
  });

  it("runs one folder now, says so, and shows the fresh outcome", async () => {
    const list = vi
      .spyOn(api, "listBackupTargets")
      .mockResolvedValueOnce({ targets: [{ ...NAS, last_run: null }], schedule: null })
      .mockResolvedValue({ targets: [NAS], schedule: null });
    const run = vi.spyOn(api, "runBackupTarget").mockResolvedValue({
      target: "nas",
      kind: "local_directory",
      destination: NAS.destination,
      artifact: "palaia-backup-20260926T120000Z.tar.gz",
      bytes_written: 1024,
      pruned: [],
      duration_seconds: 1.5,
    });

    mount();
    const row = await screen.findByTestId("backup-target-nas");
    expect(row).toHaveTextContent(/no backup written here yet/i);
    fireEvent.click(within(row).getByRole("button", { name: /back up now into nas/i }));

    await waitFor(() => expect(run).toHaveBeenCalledWith("nas"));
    expect(
      await screen.findByText(/backed up into nas: palaia-backup-20260926T120000Z/i),
    ).toBeInTheDocument();
    await waitFor(() => expect(list).toHaveBeenCalledTimes(2));
    await waitFor(() =>
      expect(screen.getByTestId("backup-target-nas")).toHaveTextContent(/on schedule/),
    );
  });

  it("a folder already being written says so in the hub's words", async () => {
    vi.spyOn(api, "listBackupTargets").mockResolvedValue({
      targets: [NAS],
      schedule: null,
    });
    vi.spyOn(api, "runBackupTarget").mockRejectedValue(
      new ApiError("/api/backup/targets/nas/run", 409, {
        detail: "a backup to 'nas' is already being written by this hub.",
      }),
    );

    mount();
    fireEvent.click(await screen.findByRole("button", { name: /back up now into nas/i }));

    expect(await screen.findByText(/already being written/i)).toBeInTheDocument();
  });

  it("a folder being written right now cannot be started twice", async () => {
    vi.spyOn(api, "listBackupTargets").mockResolvedValue({
      targets: [{ ...NAS, running: true }],
      schedule: null,
    });

    mount();

    const button = await screen.findByRole("button", { name: /back up now into nas/i });
    expect(button).toBeDisabled();
    expect(button).toHaveTextContent(/backing up/i);
  });

  it("without a schedule it says how to turn one on", async () => {
    vi.spyOn(api, "listBackupTargets").mockResolvedValue({
      targets: [NAS],
      schedule: null,
    });

    mount();

    const schedule = await screen.findByTestId("backup-schedule");
    expect(schedule).toHaveTextContent(/only when you ask/i);
    expect(within(schedule).getByText("Off")).toBeInTheDocument();
    expect(schedule).toHaveTextContent("interval_hours: 24");
  });

  it("with no folders it explains how to add one instead of an empty list", async () => {
    vi.spyOn(api, "listBackupTargets").mockResolvedValue({ targets: [], schedule: null });

    mount();

    expect(await screen.findByText(/no backup folders yet/i)).toBeInTheDocument();
    expect(screen.getByText("How to add a folder")).toBeInTheDocument();
    expect(screen.getByTestId("backup-schedule")).toHaveTextContent("path: /mnt/nas/palaia-backups");
  });

  it("downloads the backup, with the security note always in view", async () => {
    vi.spyOn(api, "listBackupTargets").mockResolvedValue({ targets: [], schedule: null });
    const download = vi
      .spyOn(api, "downloadBackup")
      .mockResolvedValue({ blob: new Blob(["x"]), filename: "palaia-backup-1.tar.gz" });

    mount();

    const card = await screen.findByTestId("backup-card");
    expect(within(card).getByRole("heading", { name: "Backup" })).toBeInTheDocument();
    expect(card).toHaveTextContent("Download a copy of your memories and settings.");
    expect(within(card).getByTestId("backup-security-note")).toHaveTextContent(
      "Includes private data and access keys. Anyone with the file can use them, so store it like a password.",
    );
    expect(within(card).getByText("What's included?")).toBeInTheDocument();
    expect(card).toHaveTextContent(/every AI app's access key/);

    fireEvent.click(within(card).getByRole("button", { name: /download backup/i }));
    await waitFor(() => expect(download).toHaveBeenCalled());
    await waitFor(() =>
      expect(saveBlob).toHaveBeenCalledWith(expect.any(Blob), "palaia-backup-1.tar.gz"),
    );
  });

  it("names each memory a backup leaves out, with its folder, instead of promising all", async () => {
    vi.spyOn(api, "listBackupTargets").mockResolvedValue({ targets: [], schedule: null });
    vi.spyOn(api, "listVaults").mockResolvedValue([
      { key: "work", purpose: null, path: "/data/vaults/work", writable: true, note_count: 3, in_backup: true },
      { key: "notes", purpose: null, path: "/srv/notes", writable: true, note_count: 9, in_backup: false },
    ]);

    mount();

    const missing = await screen.findByTestId("backup-not-included");
    expect(missing).toHaveTextContent("“notes” is not in the backup");
    expect(missing).toHaveTextContent("/srv/notes");
    expect(missing).not.toHaveTextContent("work");
    const card = screen.getByTestId("backup-card");
    expect(card).not.toHaveTextContent(/all memories/i);
    expect(card).toHaveTextContent(/a memory you created in another folder is not included/i);
  });

  it("without dashboard sign-in: says why, offers the switch that fixes it, and the server way second", async () => {
    vi.spyOn(api, "listBackupTargets").mockRejectedValue(
      new ApiError("/api/backup/targets", 403, { detail: "only for a signed-in owner" }),
    );
    vi.spyOn(api, "mode").mockResolvedValue(LOCKED_MODE);
    vi.spyOn(api, "setupStatus").mockRejectedValue(new Error("not needed"));
    vi.spyOn(api, "ownerAccount").mockResolvedValue({ configured: true });
    vi.spyOn(api, "updateCheck").mockRejectedValue(new Error("offline"));
    const change = vi.spyOn(api, "changeMode").mockResolvedValue({
      ...LOCKED_MODE,
      oauth_enabled: true,
      oauth_issuer: window.location.origin,
      dashboard_require_sign_in: true,
      restart_required: true,
    });

    mount();

    const blocked = await screen.findByTestId("backup-needs-sign-in");
    expect(within(blocked).getByText("Backups need dashboard sign-in")).toBeInTheDocument();
    expect(blocked).toHaveTextContent(/contain your access keys/i);
    // The security note is still there; the page is never an error.
    expect(screen.getByTestId("backup-security-note")).toBeInTheDocument();
    expect(screen.queryByRole("alert")).toBeNull();
    // The server way, second: the Docker command streams the file out.
    expect(within(blocked).getByText("Back up from the server instead")).toBeInTheDocument();
    expect(blocked).toHaveTextContent("docker exec palaia-hub sh -c");
    expect(blocked).toHaveTextContent("palaia-hub backup");

    fireEvent.click(await within(blocked).findByRole("button", { name: "Turn on dashboard sign-in" }));
    await waitFor(() =>
      expect(change).toHaveBeenCalledWith({
        dashboard_require_sign_in: true,
        oauth_enabled: true,
        oauth_issuer: window.location.origin,
      }),
    );
    expect(await screen.findByText("Restart palaia to apply your changes")).toBeInTheDocument();
  });

  it("without an owner account, points at creating one first", async () => {
    vi.spyOn(api, "listBackupTargets").mockRejectedValue(
      new ApiError("/api/backup/targets", 403, { detail: "only for a signed-in owner" }),
    );
    vi.spyOn(api, "mode").mockResolvedValue(LOCKED_MODE);
    vi.spyOn(api, "setupStatus").mockRejectedValue(new Error("not needed"));
    vi.spyOn(api, "ownerAccount").mockResolvedValue({ configured: false });
    vi.spyOn(api, "updateCheck").mockRejectedValue(new Error("offline"));

    mount();

    expect(await screen.findByRole("link", { name: "Create the owner account" })).toHaveAttribute(
      "href",
      "/onboarding",
    );
  });

  it("names the store's own way out on an app-store install", async () => {
    vi.spyOn(api, "listBackupTargets").mockRejectedValue(
      new ApiError("/api/backup/targets", 403, { detail: "only for a signed-in owner" }),
    );
    vi.spyOn(api, "mode").mockResolvedValue(LOCKED_MODE);
    vi.spyOn(api, "setupStatus").mockRejectedValue(new Error("not needed"));
    vi.spyOn(api, "ownerAccount").mockResolvedValue({ configured: true });
    vi.spyOn(api, "updateCheck").mockResolvedValue({ deployment: "umbrel" } as never);

    mount();

    const blocked = await screen.findByTestId("backup-needs-sign-in");
    await waitFor(() => expect(blocked).toHaveTextContent("umbrelOS runs palaia in its own container"));
    expect(blocked).not.toHaveTextContent("docker exec");
  });

  it("an error loading backups is an error, with Try again — never an empty page", async () => {
    vi.spyOn(api, "listBackupTargets").mockRejectedValue(
      new ApiError("/api/backup/targets", 500, { detail: "the ledger could not be read" }),
    );

    mount();

    expect(await screen.findByText("Couldn't load your backups")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Try again" })).toBeInTheDocument();
  });

  it("uses no in-house word", async () => {
    vi.spyOn(api, "listBackupTargets").mockResolvedValue(SCHEDULED);

    const { container } = mount();
    await screen.findByTestId("backup-target-nas");

    // A configuration example is text people type, where the config's own
    // words belong (system.md §3); everything else is read.
    const readable = container.cloneNode(true) as HTMLElement;
    readable.querySelectorAll("pre").forEach((example) => example.remove());
    const text = readable.textContent ?? "";
    for (const pattern of BANNED) {
      expect(text).not.toMatch(pattern);
    }
  });
});

const PUSHED: VaultRemoteInfo = {
  vault: "work",
  registered: true,
  remote: {
    url: "https://github.com/me/notes.git",
    branch: "main",
    username: "x-access-token",
    has_token: true,
  },
  pushing: false,
  last_push: {
    ok: true,
    trigger: "schedule",
    finished_at: NOW - 3600,
    commit: "0123456789abcdef",
    reason: null,
  },
};

const NOT_PUSHED: VaultRemoteInfo = {
  vault: "family",
  registered: true,
  remote: null,
  pushing: false,
  last_push: null,
};

describe("Backups: memories in git (issue 438)", () => {
  it("hides the card on a hub that cannot keep a token", async () => {
    vi.spyOn(api, "listBackupTargets").mockResolvedValue(SCHEDULED);

    mount();

    await screen.findByTestId("backup-target-nas");
    await waitFor(() => expect(api.listVaultRemotes).toHaveBeenCalled());
    expect(screen.queryByTestId("vault-remotes")).toBeNull();
  });

  it("lists each memory with its repository and how the last push went", async () => {
    vi.spyOn(api, "listBackupTargets").mockResolvedValue(SCHEDULED);
    vi.spyOn(api, "listVaultRemotes").mockResolvedValue({
      vaults: [PUSHED, NOT_PUSHED],
    });

    mount();

    const card = await screen.findByTestId("vault-remotes");
    expect(card).toHaveTextContent(/every scheduled backup copies them too/i);
    const work = await screen.findByTestId("vault-remote-work");
    expect(work).toHaveTextContent("https://github.com/me/notes.git");
    expect(work).toHaveTextContent(/copied/i);
    const family = screen.getByTestId("vault-remote-family");
    expect(family).toHaveTextContent(/not copied anywhere/i);
    expect(within(family).getByRole("button", { name: "Set up" })).toBeInTheDocument();
  });

  it("sets up a push with a write-only token", async () => {
    vi.spyOn(api, "listBackupTargets").mockResolvedValue({ targets: [], schedule: null });
    const list = vi
      .spyOn(api, "listVaultRemotes")
      .mockResolvedValue({ vaults: [NOT_PUSHED] });
    const save = vi.spyOn(api, "saveVaultRemote").mockResolvedValue({
      ...NOT_PUSHED,
      remote: {
        url: "https://github.com/me/family.git",
        branch: "main",
        username: "x-access-token",
        has_token: true,
      },
    });

    mount();

    const card = await screen.findByTestId("vault-remotes");
    expect(card).toHaveTextContent(/copied when you ask/i);
    fireEvent.click(await screen.findByRole("button", { name: "Set up" }));
    const form = screen.getByTestId("vault-remote-form-family");
    fireEvent.change(within(form).getByLabelText(/repository address/i), {
      target: { value: "https://github.com/me/family.git" },
    });
    const token = within(form).getByLabelText(/access token/i);
    expect(token).toHaveAttribute("type", "password");
    fireEvent.change(token, { target: { value: "github_pat_secret" } });
    fireEvent.click(within(form).getByRole("button", { name: "Save" }));

    await waitFor(() =>
      expect(save).toHaveBeenCalledWith("family", {
        url: "https://github.com/me/family.git",
        branch: "main",
        username: undefined,
        token: "github_pat_secret",
      }),
    );
    await waitFor(() => expect(list).toHaveBeenCalledTimes(2));
  });

  it("keeps the stored token when the field is left empty", async () => {
    vi.spyOn(api, "listBackupTargets").mockResolvedValue({ targets: [], schedule: null });
    vi.spyOn(api, "listVaultRemotes").mockResolvedValue({ vaults: [PUSHED] });
    const save = vi.spyOn(api, "saveVaultRemote").mockResolvedValue(PUSHED);

    mount();

    fireEvent.click(await screen.findByRole("button", { name: "Change" }));
    const form = screen.getByTestId("vault-remote-form-work");
    expect(within(form).getByLabelText(/access token/i)).toHaveAttribute(
      "placeholder",
      expect.stringMatching(/stored/i),
    );
    fireEvent.click(within(form).getByRole("button", { name: "Save" }));

    await waitFor(() =>
      expect(save).toHaveBeenCalledWith("work", {
        url: "https://github.com/me/notes.git",
        branch: "main",
        username: undefined,
        token: undefined,
      }),
    );
  });

  it("pushes on request and shows the hub's reason when it fails", async () => {
    vi.spyOn(api, "listBackupTargets").mockResolvedValue({ targets: [], schedule: null });
    vi.spyOn(api, "listVaultRemotes").mockResolvedValue({ vaults: [PUSHED] });
    const push = vi.spyOn(api, "pushVault").mockRejectedValue(
      new ApiError("/api/backup/vault-remotes/work/push", 500, {
        detail:
          "the repository's branch has commits this vault does not have, so palaia " +
          "did not overwrite it.",
      }),
    );

    mount();

    fireEvent.click(await screen.findByRole("button", { name: /copy work now/i }));

    await waitFor(() => expect(push).toHaveBeenCalledWith("work"));
    expect(
      await screen.findByText(/did not overwrite it/i),
    ).toBeInTheDocument();
  });

  it("stops pushing a memory", async () => {
    vi.spyOn(api, "listBackupTargets").mockResolvedValue({ targets: [], schedule: null });
    vi.spyOn(api, "listVaultRemotes").mockResolvedValue({ vaults: [PUSHED] });
    const remove = vi
      .spyOn(api, "removeVaultRemote")
      .mockResolvedValue({ removed: "work" });

    mount();

    fireEvent.click(await screen.findByRole("button", { name: /stop copying work/i }));
    await waitFor(() => expect(remove).toHaveBeenCalledWith("work"));
  });

  it("uses no in-house word", async () => {
    vi.spyOn(api, "listBackupTargets").mockResolvedValue(SCHEDULED);
    vi.spyOn(api, "listVaultRemotes").mockResolvedValue({
      vaults: [PUSHED, NOT_PUSHED],
    });

    mount();

    const card = await screen.findByTestId("vault-remotes");
    await within(card).findByTestId("vault-remote-work");
    const text = card.textContent ?? "";
    for (const pattern of BANNED) {
      expect(text).not.toMatch(pattern);
    }
  });
});

describe("formatRelative", () => {
  it("reads naturally in both directions", () => {
    const now = 1_000_000_000_000;
    expect(formatRelative(now / 1000 - 2 * 3600, now)).toBe("2 h ago");
    expect(formatRelative(now / 1000 + 90 * 60, now)).toBe("in 2 h");
    expect(formatRelative(now / 1000 + 30, now)).toBe("in less than a minute");
    expect(formatRelative(now / 1000 - 3 * 86400, now)).toBe("3 d ago");
  });
});
