import { type ReactNode, useEffect, useRef, useState } from "react";

import { api } from "../lib/api/client";
import { describeApiError } from "../lib/errors";
import { RestartIcon } from "../shell/icons";
import { Button, type ButtonVariant } from "./Button";
import { Callout } from "./Callout";
import { ConfirmDialog } from "./Dialog";

/** The command for a hub that cannot restart itself (no supervisor that
 * would bring it back), as the hub's own refusal names it. */
export const RESTART_COMMAND = "docker restart palaia-hub";

const POLL_MS = 1500;
const GIVE_UP_MS = 90_000;

type Phase = "idle" | "confirm" | "restarting" | "failed";

/**
 * Restart palaia from the browser (`POST /api/hub/restart`), then wait for
 * it to answer again and reload the page. Only offered where the hub says
 * something brings it back (`restart_supported` in `/api/setup`).
 * `confirm={false}` skips the dialog where the page around the button
 * already says what the restart does (a setup step titled "Restart …").
 */
export function RestartButton({
  variant = "secondary",
  label = "Restart palaia",
  confirm = true,
}: {
  variant?: ButtonVariant;
  label?: string;
  confirm?: boolean;
}) {
  const [phase, setPhase] = useState<Phase>("idle");
  const [error, setError] = useState<string | null>(null);
  const timer = useRef(0);

  useEffect(() => () => window.clearTimeout(timer.current), []);

  async function restart() {
    setError(null);
    try {
      await api.restartHub();
    } catch (err) {
      setError(describeApiError(err));
      setPhase("failed");
      return;
    }
    setPhase("restarting");
    const started = Date.now();
    let wentAway = false;
    const poll = () => {
      api
        .health()
        .then(() => {
          // Back once it answers after having been away, or after a few
          // seconds in case the restart was too quick to notice.
          if (wentAway || Date.now() - started > 4000) {
            window.location.reload();
            return;
          }
          timer.current = window.setTimeout(poll, POLL_MS);
        })
        .catch(() => {
          wentAway = true;
          if (Date.now() - started > GIVE_UP_MS) {
            setError("palaia didn't come back. Check the server it runs on.");
            setPhase("failed");
            return;
          }
          timer.current = window.setTimeout(poll, POLL_MS);
        });
    };
    timer.current = window.setTimeout(poll, POLL_MS);
  }

  return (
    <>
      <Button
        variant={variant}
        onClick={() => (confirm ? setPhase("confirm") : void restart())}
        loading={phase === "restarting"}
      >
        {phase === "restarting" ? (
          "Restarting…"
        ) : (
          <>
            <RestartIcon className="icon" />
            {label}
          </>
        )}
      </Button>
      {error ? (
        <p className="field__error" role="alert">
          {error}
        </p>
      ) : null}
      <ConfirmDialog
        open={phase === "confirm"}
        onCancel={() => setPhase("idle")}
        onConfirm={() => void restart()}
        title="Restart palaia?"
        confirmLabel="Restart"
      >
        <p>
          This page and connected AI apps lose the connection for a few seconds. The page
          reloads when palaia is back.
        </p>
      </ConfirmDialog>
    </>
  );
}

/**
 * "Restart palaia to apply": shown when a saved change only takes effect
 * after a restart. With a supervisor the button does it; without one, the
 * command to run on the server.
 */
export function RestartCallout({
  supported,
  children,
}: {
  supported: boolean;
  children?: ReactNode;
}) {
  return (
    <Callout
      tone="warn"
      title="Restart palaia to apply your changes"
      actions={supported ? <RestartButton variant="primary" label="Restart now" /> : undefined}
    >
      {children}
      {supported ? null : (
        <p>
          On the server palaia runs on: <code>{RESTART_COMMAND}</code>
        </p>
      )}
    </Callout>
  );
}
