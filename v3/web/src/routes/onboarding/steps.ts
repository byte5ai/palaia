/**
 * The wizard's steps and their state, derived from the hub's own setup
 * status (issues 559, 561): a step is done when the hub has it, skipped
 * when the owner said so, never because the wizard moved past it.
 */
import type { SetupStatus } from "../../lib/api/client";

export type StepId = "goal" | "memory" | "account" | "cloud" | "connect";
export type StepState = "done" | "skipped" | "attention" | "todo";

export interface StepView {
  id: StepId;
  name: string;
  state: StepState;
}

export type Goal = "cloud" | "private";

/** The goal shown before the owner chose one: cloud, the usual setup. */
export function goalOf(status: SetupStatus): Goal {
  return status.goal ?? "cloud";
}

/** A private hub's account exists and its sign-in is saved, but the running
 * palaia does not ask for it yet: the account step's restart is still to
 * do, so the step stays open until the hub confirms sign-in is active. */
export function signInPending(status: SetupStatus): boolean {
  return (
    goalOf(status) === "private" &&
    status.owner_configured &&
    status.configured_sign_in &&
    !status.sign_in_active
  );
}

/** Whether `id` names a step of this setup (the `?step=` link). */
export function isStepOf(views: StepView[], id: string | null): id is StepId {
  return views.some((view) => view.id === id);
}

export function stepViews(status: SetupStatus): StepView[] {
  const goal = goalOf(status);
  const skipped = new Set(status.skipped);
  const views: StepView[] = [
    {
      id: "goal",
      name: "How you'll use palaia",
      state: status.goal ? "done" : "todo",
    },
    {
      id: "memory",
      name: "Your first memory",
      state: status.vaults.length ? "done" : "todo",
    },
    {
      id: "account",
      name: "Your account",
      state: status.owner_configured
        ? signInPending(status)
          ? "attention"
          : "done"
        : goal === "private" && skipped.has("account")
          ? "skipped"
          : "todo",
    },
  ];
  if (goal === "cloud") {
    const turnedOn =
      status.configured_mode === "cloud" && status.configured_sign_in;
    views.push({
      id: "cloud",
      name: "Cloud access",
      // Done only once the hub reached its own public address and every
      // check passed — configuration alone does not prove the tunnel.
      state: status.cloud_ready && status.cloud_verified
        ? "done"
        : skipped.has("cloud")
          ? "skipped"
          : turnedOn
            ? "attention"
            : "todo",
    });
  }
  views.push({
    id: "connect",
    name: "Connect an AI app",
    state: status.client_connected
      ? "done"
      : skipped.has("client")
        ? "skipped"
        : "todo",
  });
  return views;
}

/** The first step still to do — or `null` when every step is done or skipped. */
export function firstOpenStep(views: StepView[]): StepId | null {
  return (
    views.find((view) => view.state === "todo" || view.state === "attention")
      ?.id ?? null
  );
}
