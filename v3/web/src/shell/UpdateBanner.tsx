import { useEffect, useState } from "react";

import { Badge } from "../components/Badge";
import { Button } from "../components/Button";
import { Card, CardBody, CardHead } from "../components/Card";
import { useToast } from "../components/Toast";
import type { UpdateCheckResponse } from "../lib/api/client";
import { api } from "../lib/api/client";
import { CopyIcon } from "./icons";

const DISMISSED_KEY = "palaia.update.dismissed_version";

function readDismissedVersion(): string | null {
  try {
    return window.localStorage.getItem(DISMISSED_KEY);
  } catch {
    // Private browsing / blocked site data: the banner just reappears
    // every visit instead of remembering a dismissal — no worse than not
    // having one.
    return null;
  }
}

function writeDismissedVersion(version: string): void {
  try {
    window.localStorage.setItem(DISMISSED_KEY, version);
  } catch {
    // Same as above — dismissing this once, this visit, is still fine.
  }
}

/**
 * SPEC-501 deliverable #4: the "Update available" banner. Renders nothing
 * until `GET /api/update/check` actually reports `update_available` — "up
 * to date" and "could not check" are both quiet states (this SPEC's own
 * non-goal: no nagging, no error page for an offline hub). Never performs
 * an update itself; every path here ends with the operator (or their
 * store) doing the recreate — see `palaia_hub.update.update_guidance`.
 */
export function UpdateBanner() {
  const toast = useToast();
  const [check, setCheck] = useState<UpdateCheckResponse | null>(null);
  const [dismissedVersion, setDismissedVersion] = useState<string | null>(() =>
    readDismissedVersion(),
  );

  useEffect(() => {
    let cancelled = false;
    api
      .updateCheck()
      .then((result) => {
        if (!cancelled) setCheck(result);
      })
      .catch(() => {
        // Same rule as the hub's own /api/update/check: a failure here is
        // silence, never an error banner.
      });
    return () => {
      cancelled = true;
    };
  }, []);

  if (!check || check.state !== "update_available") return null;
  if (check.latest_version && check.latest_version === dismissedVersion) return null;

  const { guidance } = check;

  return (
    <Card className="update-banner" role="status">
      <CardHead title="Update available" meta={check.channel}>
        <Badge variant="info">
          {check.current_version}
          {check.latest_version ? ` → ${check.latest_version}` : ""}
        </Badge>
      </CardHead>
      <CardBody className="stack stack--2">
        <p className="t-sm t-muted">{guidance.message}</p>
        {guidance.commands.length > 0 ? (
          <div className="row row--wrap" style={{ gap: 6 }}>
            {guidance.commands.map((command) => (
              <Button
                key={command}
                size="sm"
                variant="quiet"
                onClick={() => {
                  navigator.clipboard.writeText(command).then(
                    () => toast.show("Command copied."),
                    () => toast.show("Could not copy — select and copy manually."),
                  );
                }}
              >
                <CopyIcon className="icon--sm" />
                {command}
              </Button>
            ))}
          </div>
        ) : null}
        <div>
          <Button
            variant="quiet"
            size="sm"
            onClick={() => {
              if (check.latest_version) {
                writeDismissedVersion(check.latest_version);
                setDismissedVersion(check.latest_version);
              }
            }}
          >
            Dismiss
          </Button>
        </div>
      </CardBody>
    </Card>
  );
}
