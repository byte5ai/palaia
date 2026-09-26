import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ToastProvider } from "../components/Toast";
import type { BackupTargetInfo, BackupTargetsResponse } from "../lib/api/client";
import { api, ApiError } from "../lib/api/client";
import { formatRelative } from "../lib/format";
import { Backups } from "./Backups";

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
    expect(schedule).toHaveTextContent("interval_hours: 24");
  });

  it("with no folders it explains how to add one instead of an empty list", async () => {
    vi.spyOn(api, "listBackupTargets").mockResolvedValue({ targets: [], schedule: null });

    mount();

    expect(await screen.findByText(/no backup folders yet/i)).toBeInTheDocument();
    expect(screen.queryByTestId("backup-schedule")).toBeNull();
    expect(screen.getByRole("link", { name: /how to add one/i })).toBeInTheDocument();
  });

  it("on a hub that refuses (no sign-in), shows the hub's own way out", async () => {
    vi.spyOn(api, "listBackupTargets").mockRejectedValue(
      new ApiError("/api/backup/targets", 403, {
        detail:
          "Backup targets are only reachable by a signed-in owner. Fix: run " +
          "`palaia-hub backup --target <name>` on the machine the hub runs on.",
      }),
    );

    mount();

    const card = await screen.findByTestId("backups-error");
    expect(card).toHaveTextContent(/palaia-hub backup --target/);
  });

  it("uses no in-house word", async () => {
    vi.spyOn(api, "listBackupTargets").mockResolvedValue(SCHEDULED);

    const { container } = mount();
    await screen.findByTestId("backup-target-nas");

    const text = container.textContent ?? "";
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
