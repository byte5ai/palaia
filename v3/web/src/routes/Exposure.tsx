/**
 * The access-mode & reach-it-from-outside wizard (SPEC-205).
 *
 * Locked -> Cloud -> Open is presented as a guided, safe journey rather
 * than a raw settings form: each mode is explained in plain language
 * before the switch (MASTERPLAN §5.5's table, and its "vendor-cloud
 * reality check" — claude.ai/ChatGPT connect from their own cloud, so
 * Locked mode genuinely cannot reach them, whatever the local network
 * looks like); Cloud mode's tunnel guidance is copy-paste ready for
 * Tailscale or cloudflared, with a real "is it actually reachable"
 * self-test that never claims success it did not itself observe; Open
 * mode surfaces its hardening checklist, honest about which items the hub
 * verified itself and which only the operator can confirm.
 *
 * Deliberately dashboard-only — no MCP App surface (system's own
 * principles.md: "Access mode / exposure, token revocation — changes the
 * attack surface — dashboard only").
 */
import { useEffect, useState } from "react";

import { Badge } from "../components/Badge";
import { Button } from "../components/Button";
import { Card, CardBody, CardFoot, CardHead } from "../components/Card";
import { SwitchRow } from "../components/Field";
import { Waiting } from "../components/Skeleton";
import { useToast } from "../components/Toast";
import type {
  ChecklistItem,
  ExposureStatus,
  ModeStatus,
  SelfTestResult,
  TunnelGuidance,
} from "../lib/api/client";
import { api, ApiError } from "../lib/api/client";
import { CheckIcon, CopyIcon, InfoIcon, WarningIcon } from "../shell/icons";

type Mode = "locked" | "cloud" | "open";

const MODE_COPY: Record<Mode, { title: string; body: string }> = {
  locked: {
    title: "Only your own network can reach it",
    body:
      "Your laptop, your phone on your home Wi-Fi, or anything on your VPN can connect. " +
      "claude.ai and ChatGPT connect from their own cloud, not from your device — in this " +
      "mode they simply cannot reach palaia, whatever your network looks like.",
  },
  cloud: {
    title: "Claude, ChatGPT and your phone can reach your memory",
    body:
      "Your memory becomes reachable from anywhere, once you point a tunnel at it below. " +
      "This dashboard stays on your own network only — someone would need to be on your " +
      "VPN to see or change anything here.",
  },
  open: {
    title: "Everything is reachable from the internet — including this dashboard",
    body:
      "Only choose this if you mean it: vault contents, tokens and hooks management all " +
      "become reachable from anywhere, not just your memory. Everything here is then " +
      "behind your sign-in, which this mode requires. Go through the checklist below first.",
  },
};

function errorDetail(err: unknown): string {
  if (err instanceof ApiError) {
    const body = err.body as { detail?: string } | undefined;
    if (body?.detail) return body.detail;
    return `The hub answered ${err.status}.`;
  }
  return "Could not reach the hub.";
}

function copy(text: string, toast: ReturnType<typeof useToast>, what: string) {
  navigator.clipboard.writeText(text).then(
    () => toast.show(`${what} copied.`),
    () => toast.show("Could not copy — select and copy manually."),
  );
}

export function Exposure() {
  const toast = useToast();
  const [status, setStatus] = useState<ModeStatus | null>(null);
  const [draftMode, setDraftMode] = useState<Mode>("locked");
  const [requireSignIn, setRequireSignIn] = useState(true);
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    api
      .mode()
      .then((body) => {
        if (cancelled) return;
        setStatus(body);
        setDraftMode(body.configured_mode as Mode);
        setRequireSignIn(body.auth_enabled || body.oauth_enabled);
      })
      .catch(() => {
        // No hub reachable — this page just stays on its loading state
        // rather than guessing at a mode it does not actually know.
      });
    return () => {
      cancelled = true;
    };
  }, []);

  async function save() {
    setSaving(true);
    setSaveError(null);
    try {
      const body = await api.changeMode({
        mode: draftMode,
        auth_enabled: draftMode === "locked" ? requireSignIn : true,
      });
      setStatus(body);
      toast.show(
        body.restart_required
          ? "Saved. Restart the hub for this to take effect."
          : "Saved.",
      );
    } catch (err) {
      setSaveError(errorDetail(err));
    } finally {
      setSaving(false);
    }
  }

  if (!status) {
    return (
      <Card>
        <CardBody>
          <Waiting>Loading your current access mode…</Waiting>
        </CardBody>
      </Card>
    );
  }

  const dirty = draftMode !== status.configured_mode;
  const showTunnel = draftMode === "cloud" || draftMode === "open";
  const showChecklist = draftMode === "open";

  return (
    <div className="stack stack--4">
      <Card>
        <CardHead
          title="access mode"
          meta={
            status.restart_required ? (
              <Badge variant="warn">saved — restart to apply</Badge>
            ) : (
              <Badge variant="ok">
                {status.active_mode === "locked"
                  ? "your network only"
                  : status.active_mode === "cloud"
                    ? "memory reachable everywhere"
                    : "everything reachable everywhere"}
              </Badge>
            )
          }
        />
        <CardBody className="stack stack--3">
          <div className="segmented" role="radiogroup" aria-label="Access mode">
            {(["locked", "cloud", "open"] as Mode[]).map((mode) => (
              <button
                key={mode}
                type="button"
                role="radio"
                aria-checked={draftMode === mode}
                className={["segmented__item", draftMode === mode ? "segmented__item--on" : ""]
                  .filter(Boolean)
                  .join(" ")}
                onClick={() => setDraftMode(mode)}
              >
                {mode === "locked" ? "Locked" : mode === "cloud" ? "Cloud" : "Open"}
              </button>
            ))}
          </div>
          <p className="card__subject">{MODE_COPY[draftMode].title}</p>
          <p className="t-sm t-muted">{MODE_COPY[draftMode].body}</p>
          {draftMode !== "locked" ? (
            <div className="banner">
              <InfoIcon className="icon icon--sm" />
              <p className="t-sm t-muted">
                Cloud and Open both require sign-in — anyone without a token or an account is
                turned away.
              </p>
            </div>
          ) : (
            <SwitchRow
              label="Require sign-in"
              consequence="Off by default here, since only your own trusted devices can reach palaia in this mode."
              checked={requireSignIn}
              onChange={setRequireSignIn}
            />
          )}
          {saveError ? (
            <div className="banner banner--warn">
              <WarningIcon className="icon icon--sm" />
              <p className="t-sm t-muted">{saveError}</p>
            </div>
          ) : null}
        </CardBody>
        <CardFoot>
          <Button variant="primary" onClick={save} disabled={saving || !dirty}>
            {saving ? "Saving…" : dirty ? "Save this access mode" : "No changes to save"}
          </Button>
        </CardFoot>
      </Card>

      {showTunnel ? <TunnelCard mode={draftMode === "open" ? "open" : "cloud"} /> : null}
      {showChecklist ? <ChecklistCard /> : null}
    </div>
  );
}

function TunnelCard({ mode }: { mode: "cloud" | "open" }) {
  const toast = useToast();
  const [kind, setKind] = useState<"tailscale" | "cloudflared" | "own">("tailscale");
  const [hostname, setHostname] = useState("");
  const [guidance, setGuidance] = useState<TunnelGuidance | null>(null);
  const [detected, setDetected] = useState<{ tailscale: boolean; cloudflared: boolean } | null>(
    null,
  );
  const [publicUrl, setPublicUrl] = useState("");
  const [testResult, setTestResult] = useState<SelfTestResult | null>(null);
  const [testing, setTesting] = useState(false);

  useEffect(() => {
    let cancelled = false;
    api
      .exposure()
      .then((body: ExposureStatus) => {
        if (cancelled) return;
        setDetected(body.detected);
        if (body.status.public_url) setPublicUrl(body.status.public_url);
      })
      .catch(() => {
        // Detection/known-public-URL is a convenience, not a requirement —
        // the tabs below still work with nothing pre-filled.
      });
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    // Nothing to fetch for "I have my own reverse proxy" — the render
    // below never reads `guidance` in that branch, so leaving stale state
    // sit unread here is harmless, and it is refreshed the moment `kind`
    // switches back to a real provider.
    if (kind === "own") return;
    let cancelled = false;
    api
      .tunnelGuidance({ kind, hostname: hostname || undefined })
      .then((body) => {
        if (!cancelled) setGuidance(body);
      })
      .catch(() => {
        // No hub reachable — the tab just stays without a generated
        // config rather than showing a stale or fabricated one.
      });
    return () => {
      cancelled = true;
    };
  }, [kind, hostname, mode]);

  async function runSelfTest() {
    if (!publicUrl.trim()) return;
    setTesting(true);
    setTestResult(null);
    try {
      setTestResult(await api.selfTest(publicUrl.trim()));
    } catch {
      // The self-test endpoint itself was unreachable (not the public URL
      // it was asked to check) — leave the result blank rather than
      // reporting a fabricated "unreachable" for the wrong target.
    } finally {
      setTesting(false);
    }
  }

  return (
    <Card>
      <CardHead title="reach it from outside your network" />
      <CardBody className="stack stack--3">
        <div className="segmented" role="radiogroup" aria-label="How you reach this hub">
          {(
            [
              { value: "tailscale" as const, label: "Tailscale" },
              { value: "cloudflared" as const, label: "cloudflared" },
              { value: "own" as const, label: "I have my own reverse proxy" },
            ]
          ).map((option) => (
            <button
              key={option.value}
              type="button"
              role="radio"
              aria-checked={kind === option.value}
              className={["segmented__item", kind === option.value ? "segmented__item--on" : ""]
                .filter(Boolean)
                .join(" ")}
              onClick={() => setKind(option.value)}
            >
              {option.label}
            </button>
          ))}
        </div>

        {kind === "own" ? (
          <p className="t-sm t-muted">
            Point your reverse proxy at this machine and terminate a secure (https) address
            there. Once it answers, put its address in the box below and test it.
          </p>
        ) : (
          <>
            <p className="t-xs t-muted">
              {detected
                ? detected[kind]
                  ? `${kind === "tailscale" ? "Tailscale" : "cloudflared"} was found on this machine.`
                  : `${kind === "tailscale" ? "Tailscale" : "cloudflared"} was not found on this machine — install it first, then come back to run these.`
                : null}
            </p>
            <input
              className="input"
              placeholder={kind === "tailscale" ? "your-machine.tailnet-name.ts.net" : "hub.example.com"}
              value={hostname}
              onChange={(event) => setHostname(event.target.value)}
              aria-label="Hostname"
            />
            {guidance ? (
              <div className="stack stack--2">
                <div className="snippet snippet--block">
                  <code>{guidance.config}</code>
                </div>
                <div className="row row--wrap" style={{ gap: 6 }}>
                  <Button size="sm" onClick={() => copy(guidance.config, toast, "Config")}>
                    <CopyIcon className="icon--sm" />
                    Copy config
                  </Button>
                  {guidance.commands.map((command) => (
                    <Button
                      key={command}
                      size="sm"
                      variant="quiet"
                      onClick={() => copy(command, toast, "Command")}
                    >
                      <CopyIcon className="icon--sm" />
                      {command}
                    </Button>
                  ))}
                </div>
                <p className="t-xs t-muted">{guidance.note}</p>
              </div>
            ) : null}
          </>
        )}

        <div className="stack stack--2" style={{ marginTop: 8 }}>
          <span className="field__label">Check it actually works</span>
          <div className="row row--wrap">
            <input
              className="input"
              style={{ maxWidth: 320 }}
              placeholder="https://hub.example.com"
              value={publicUrl}
              onChange={(event) => setPublicUrl(event.target.value)}
              aria-label="Public address to test"
            />
            <Button onClick={runSelfTest} disabled={testing || !publicUrl.trim()}>
              {testing ? "Testing…" : "Test now"}
            </Button>
          </div>
          {testResult ? (
            testResult.reachable ? (
              <div className="banner banner--ok">
                <CheckIcon className="icon icon--sm" />
                <p className="t-sm t-muted">
                  Reachable — palaia fetched itself through this address in{" "}
                  {Math.round(testResult.latency_ms ?? 0)} ms.
                </p>
              </div>
            ) : (
              <div className="banner banner--warn">
                <WarningIcon className="icon icon--sm" />
                <p className="t-sm t-muted">Not reachable — {testResult.error}</p>
              </div>
            )
          ) : null}
        </div>
      </CardBody>
    </Card>
  );
}

function ChecklistCard() {
  const [items, setItems] = useState<ChecklistItem[] | null>(null);

  useEffect(() => {
    let cancelled = false;
    api
      .exposure()
      .then((body: ExposureStatus) => {
        if (!cancelled) setItems(body.checklist);
      })
      .catch(() => {
        // No hub reachable — the list just stays on its loading state.
      });
    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <Card>
      <CardHead title="before you open the dashboard itself" />
      <CardBody className="stack stack--2">
        {items === null ? (
          <Waiting>Checking…</Waiting>
        ) : (
          items.map((item) => (
            <div className="row" key={item.id} style={{ gap: 10, alignItems: "flex-start" }}>
              {item.auto ? (
                <Badge variant={item.passed ? "ok" : "risk"}>
                  {item.passed ? "checked" : "not yet"}
                </Badge>
              ) : (
                <Badge variant="neutral">check yourself</Badge>
              )}
              <div>
                <p className="t-sm">{item.title}</p>
                <p className="t-xs t-muted">{item.detail}</p>
              </div>
            </div>
          ))
        )}
      </CardBody>
    </Card>
  );
}
