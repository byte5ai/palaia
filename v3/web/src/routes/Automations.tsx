/**
 * SPEC-201 deliverable #3's webhook list (create/enable/disable/delete),
 * plus SPEC-307's real trigger → condition → action editor
 * (`AutomationEditor`) for the three action kinds beyond a webhook:
 * remembering something, saving a value, and sending a notification. A
 * webhook stays its own, separate configuration surface below — see
 * `palaia_hub.automations`'s package docstring for why the two are not
 * unified into one model.
 */
import { useEffect, useState } from "react";

import {
  Badge,
  Button,
  Card,
  CardBody,
  CardHead,
  EmptyState,
  LabeledInput,
  SwitchRow,
  useToast,
} from "../components";
import type { CreatedHook, HookInfo } from "../lib/api/client";
import { api, ApiError } from "../lib/api/client";
import { AutomationsIcon, CopyIcon } from "../shell/icons";
import { AutomationEditor } from "./AutomationEditor";

function HookRow({
  hook,
  onToggle,
  onDelete,
}: {
  hook: HookInfo;
  onToggle: (enabled: boolean) => void;
  onDelete: () => void;
}) {
  return (
    <div className="card" style={{ padding: 0 }}>
      <div className="card__body stack stack--3">
        <div
          className="row"
          style={{ justifyContent: "space-between", alignItems: "flex-start" }}
        >
          <div className="stack stack--2">
            <span className="t-sm" style={{ wordBreak: "break-all" }}>
              {hook.url}
            </span>
            <div className="row row--wrap" style={{ gap: 4 }}>
              {hook.events.map((event) => (
                <span className="chip chip--mono" key={event}>
                  {event}
                </span>
              ))}
            </div>
          </div>
          <Badge variant={hook.enabled ? "ok" : "neutral"}>
            {hook.enabled ? "enabled" : "disabled"}
          </Badge>
        </div>
        <div className="row" style={{ justifyContent: "space-between" }}>
          <SwitchRow
            label={hook.enabled ? "Enabled" : "Disabled"}
            checked={hook.enabled}
            onChange={onToggle}
          />
          <Button variant="risk" size="sm" onClick={onDelete}>
            Delete
          </Button>
        </div>
        <span className="t-xs t-subtle">
          Created {new Date(hook.created_at).toLocaleString()}
        </span>
      </div>
    </div>
  );
}

export function Automations() {
  const toast = useToast();
  const [hooks, setHooks] = useState<HookInfo[] | null>(null);
  const [hooksAvailable, setHooksAvailable] = useState(true);
  const [url, setUrl] = useState("");
  const [events, setEvents] = useState("*");
  const [creating, setCreating] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [justCreated, setJustCreated] = useState<CreatedHook | null>(null);

  function refresh() {
    api
      .listHooks()
      .then((list) => {
        setHooks(list);
        setHooksAvailable(true);
      })
      .catch((err) => {
        if (err instanceof ApiError && err.status === 404) {
          setHooksAvailable(false);
        }
      });
  }

  useEffect(refresh, []);

  function copy(text: string) {
    navigator.clipboard.writeText(text).then(
      () => toast.show("Secret copied."),
      () => toast.show("Could not copy — select and copy manually."),
    );
  }

  async function createHook() {
    setError(null);
    if (!url.trim()) {
      setError("A URL is required.");
      return;
    }
    setCreating(true);
    try {
      const eventList = events
        .split(",")
        .map((e) => e.trim())
        .filter(Boolean);
      const created = await api.createHook({
        url: url.trim(),
        events: eventList,
      });
      setJustCreated(created);
      setUrl("");
      setEvents("*");
      refresh();
    } catch (err) {
      setError(
        err instanceof ApiError
          ? String(err.body ?? err.message)
          : "Could not create hook.",
      );
    } finally {
      setCreating(false);
    }
  }

  async function toggle(hook: HookInfo, enabled: boolean) {
    await api.setHookEnabled(hook.id, enabled);
    refresh();
  }

  async function remove(hook: HookInfo) {
    await api.deleteHook(hook.id);
    if (justCreated?.info.id === hook.id) setJustCreated(null);
    refresh();
  }

  return (
    <section className="stack stack--4">
      <AutomationEditor />

      {!hooksAvailable ? (
        <Card>
          <CardBody>
            <p className="t-sm t-muted">
              This hub has no webhook store mounted, so no outside address can
              be connected from here yet.
            </p>
          </CardBody>
        </Card>
      ) : (
        <>
          <Card>
            <CardHead title="connect an outside address" />
            <CardBody className="stack stack--3">
              <p className="t-xs t-subtle">
                For sending an event to your own server address, rather than one
                of the actions above.
              </p>
              <LabeledInput
                label="Address"
                placeholder="https://example.com/palaia-hook"
                title="A webhook: palaia POSTs a signed JSON payload to this address."
                value={url}
                onChange={(event) => setUrl(event.target.value)}
              />
              <LabeledInput
                label="Events"
                hint="Comma-separated event names, or * for every event — see docs/events.md."
                value={events}
                onChange={(event) => setEvents(event.target.value)}
              />
              {error ? <p className="field__error">{error}</p> : null}
              <div className="row">
                <Button
                  variant="primary"
                  onClick={createHook}
                  disabled={creating}
                >
                  {creating ? "Connecting…" : "Connect"}
                </Button>
              </div>
            </CardBody>
          </Card>

          {justCreated ? (
            <Card variant="flat">
              <CardBody className="stack stack--2">
                <p className="t-sm">
                  Connected. Copy its secret now — it signs every delivery and
                  will not be shown again.
                </p>
                <div className="snippet snippet--wrap">
                  <code>{justCreated.secret}</code>
                  <Button size="sm" onClick={() => copy(justCreated.secret)}>
                    <CopyIcon className="icon--sm" />
                    Copy
                  </Button>
                </div>
              </CardBody>
            </Card>
          ) : null}

          <div className="card">
            <div className="card__head">
              <span className="card__title">connected addresses</span>
              <span className="t-meta">
                {hooks ? `${hooks.length} configured` : "…"}
              </span>
            </div>
            <div className="card__body stack stack--3">
              {hooks && hooks.length === 0 ? (
                <EmptyState
                  mark={<AutomationsIcon className="icon--lg" />}
                  title="Nothing connected yet."
                >
                  Connect one above to have palaia send a signed payload for
                  every event that matches its filter.
                </EmptyState>
              ) : (
                (hooks ?? []).map((hook) => (
                  <HookRow
                    key={hook.id}
                    hook={hook}
                    onToggle={(enabled) => toggle(hook, enabled)}
                    onDelete={() => remove(hook)}
                  />
                ))
              )}
            </div>
          </div>
        </>
      )}
    </section>
  );
}
