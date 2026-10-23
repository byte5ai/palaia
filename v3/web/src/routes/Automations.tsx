/**
 * Automations (SPEC-307, redesigned for issues 570 and 571): the list first, with
 * "New automation" as the page's one primary action and the ready-made
 * recipes as the empty state; events sent to the person's own server
 * (SPEC-201 #3's webhooks) on a tab of their own. The two are separate
 * configuration surfaces — see `palaia_hub.automations` for why.
 */
import { useCallback, useEffect, useId, useRef, useState } from "react";

import {
  Button,
  Callout,
  ConfirmDialog,
  Dialog,
  EmptyState,
  ErrorState,
  LabeledInput,
  LoadingState,
  PageHeader,
  Switch,
  TabPanel,
  Tabs,
  useToast,
} from "../components";
import type { AutomationInfo, CreatedHook, HookInfo } from "../lib/api/client";
import { api, ApiError } from "../lib/api/client";
import { docsUrl } from "../lib/docs";
import { describeApiError } from "../lib/errors";
import { exactTime, shortDate } from "../lib/format";
import { useTabParam } from "../lib/useTabParam";
import { CopyIcon, LinkIcon } from "../shell/icons";
import { AutomationDialog, AutomationList, type Recipe } from "./AutomationEditor";
import "./automations.css";

const VIEWS = ["automations", "webhooks"] as const;
type View = (typeof VIEWS)[number];

/** A list that is loading, ready, turned off on this server (404) or
 * failed — with the failure's own words. */
type Load<T> = { data: T | null; state: "loading" | "ready" | "off" | "error"; error: string | null };

function useList<T>(load: () => Promise<T>): [Load<T>, () => void] {
  const [value, setValue] = useState<Load<T>>({ data: null, state: "loading", error: null });
  const refresh = useCallback(() => {
    load()
      .then((data) => setValue({ data, state: "ready", error: null }))
      .catch((err: unknown) => {
        if (err instanceof ApiError && err.status === 404) {
          setValue({ data: null, state: "off", error: null });
          return;
        }
        // Issue 378: any other failure is said, never shown as empty.
        setValue((prev) => ({ data: prev.data, state: "error", error: describeApiError(err) }));
      });
    // `load` is a stable module-level call in both uses below.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  useEffect(refresh, [refresh]);
  return [value, refresh];
}

function HookRow({
  hook,
  onToggle,
  onDelete,
}: {
  hook: HookInfo;
  onToggle: (enabled: boolean) => void;
  onDelete: () => void;
}) {
  const labelId = useId();
  const allEvents = hook.events.length === 0 || hook.events.includes("*");
  return (
    <div className="automations-row">
      <div className="automations-row__head">
        <div className="automations-row__main">
          <span className="listrow__title t-mono automations-hook__url" id={labelId}>
            {hook.url}
          </span>
          <span className="listrow__desc">
            {allEvents ? "All events" : hook.events.join(", ")}
          </span>
          <span className="listrow__meta" title={exactTime(hook.created_at)}>
            Added {shortDate(hook.created_at)}
          </span>
        </div>
        <div className="automations-row__actions">
          <span className="t-sm t-muted" aria-hidden="true">
            {hook.enabled ? "On" : "Off"}
          </span>
          <Switch checked={hook.enabled} onChange={onToggle} labelledBy={labelId} />
        </div>
      </div>
      <div className="automations-row__tools">
        <Button variant="destructive" size="sm" onClick={onDelete}>
          Delete
        </Button>
      </div>
    </div>
  );
}

function NewHookDialog({
  open,
  onClose,
  onCreated,
}: {
  open: boolean;
  onClose: () => void;
  onCreated: (created: CreatedHook) => void;
}) {
  const [url, setUrl] = useState("");
  const [events, setEvents] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function create() {
    setError(null);
    if (!url.trim()) {
      setError("Enter the address palaia should send events to.");
      return;
    }
    setSaving(true);
    try {
      const eventList = events
        .split(",")
        .map((e) => e.trim())
        .filter(Boolean);
      // Empty means every event — the hub's own default when the list is left out.
      const created = await api.createHook({
        url: url.trim(),
        ...(eventList.length > 0 ? { events: eventList } : {}),
      });
      setUrl("");
      setEvents("");
      onCreated(created);
    } catch (err) {
      // Issue 377: the hub's own words, never "[object Object]".
      setError(describeApiError(err));
    } finally {
      setSaving(false);
    }
  }

  return (
    <Dialog
      open={open}
      onClose={onClose}
      size="form"
      title="Send events to your server"
      description="palaia sends each event to this address, signed so your server can check it came from palaia."
      footer={
        <>
          <Button onClick={onClose} disabled={saving}>
            Cancel
          </Button>
          <Button variant="primary" onClick={() => void create()} loading={saving}>
            {saving ? "Adding…" : "Add address"}
          </Button>
        </>
      }
    >
      <LabeledInput
        label="Address"
        placeholder="https://example.com/palaia-events"
        title="A webhook: palaia sends a signed request to this address for every matching event."
        value={url}
        onChange={(event) => setUrl(event.target.value)}
      />
      <LabeledInput
        label="Events"
        optional
        placeholder="memory.entry.created, doctor.finding"
        hint={
          <>
            Leave empty for all events. Separate names with commas.{" "}
            <a href={docsUrl("/automations/")} target="_blank" rel="noreferrer">
              Which events exist
            </a>
          </>
        }
        value={events}
        onChange={(event) => setEvents(event.target.value)}
      />
      {error ? (
        <p className="field__error" role="alert">
          {error}
        </p>
      ) : null}
    </Dialog>
  );
}

function WebhooksView({
  hooks,
  onRefresh,
  justCreated,
  onDismissCreated,
}: {
  hooks: Load<HookInfo[]>;
  onRefresh: () => void;
  justCreated: CreatedHook | null;
  onDismissCreated: () => void;
}) {
  const toast = useToast();
  const [deleting, setDeleting] = useState<HookInfo | null>(null);
  const [busy, setBusy] = useState(false);

  function copy(text: string) {
    navigator.clipboard.writeText(text).then(
      () => toast.show("Signing key copied."),
      () => toast.show("Couldn't copy. Select the key and copy it yourself."),
    );
  }

  // Issue 376: a failed toggle/delete says what the hub answered.
  async function toggle(hook: HookInfo, enabled: boolean) {
    try {
      await api.setHookEnabled(hook.id, enabled);
    } catch (err) {
      toast.show(describeApiError(err));
      return;
    }
    onRefresh();
  }

  async function remove(hook: HookInfo) {
    setBusy(true);
    try {
      await api.deleteHook(hook.id);
    } catch (err) {
      toast.show(describeApiError(err));
      setBusy(false);
      return;
    }
    setBusy(false);
    setDeleting(null);
    if (justCreated?.info.id === hook.id) onDismissCreated();
    onRefresh();
  }

  if (hooks.state === "off") {
    return (
      <Callout tone="neutral" title="Sending events to a server is turned off on this palaia" />
    );
  }
  if (hooks.data === null) {
    return hooks.state === "error" ? (
      <ErrorState title="Couldn't load your addresses" details={hooks.error} onRetry={onRefresh}>
        palaia didn't answer with the addresses it sends events to.
      </ErrorState>
    ) : (
      <LoadingState label="Loading your addresses…" />
    );
  }

  return (
    <div className="stack stack--4">
      <p className="t-muted">Send events to your own server. Each one is signed by palaia.</p>
      {justCreated ? (
        <Callout
          tone="ok"
          title="Address added. Copy its signing key now"
          actions={
            <Button size="sm" variant="plain" onClick={onDismissCreated}>
              Done
            </Button>
          }
        >
          <p>palaia signs every delivery with this key and can't show it again.</p>
          <div className="snippet snippet--wrap automations-secret">
            <code>{justCreated.secret}</code>
            <Button size="sm" onClick={() => copy(justCreated.secret)}>
              <CopyIcon className="icon" />
              Copy
            </Button>
          </div>
        </Callout>
      ) : null}
      {hooks.data.length === 0 ? (
        <EmptyState mark={<LinkIcon className="icon icon--xl" />} title="No addresses yet">
          Add one to have palaia send events to your own server.
        </EmptyState>
      ) : (
        <div className="card">
          {hooks.data.map((hook) => (
            <HookRow
              key={hook.id}
              hook={hook}
              onToggle={(enabled) => void toggle(hook, enabled)}
              onDelete={() => setDeleting(hook)}
            />
          ))}
        </div>
      )}
      <ConfirmDialog
        open={deleting !== null}
        onCancel={() => setDeleting(null)}
        onConfirm={() => deleting && void remove(deleting)}
        title="Stop sending events to this address?"
        confirmLabel="Delete address"
        destructive
        busy={busy}
      >
        <p className="t-mono automations-hook__url">{deleting?.url}</p>
      </ConfirmDialog>
    </div>
  );
}

function AutomationsView({
  automations,
  onRefresh,
  onUseRecipe,
}: {
  automations: Load<AutomationInfo[]>;
  onRefresh: () => void;
  onUseRecipe: (recipe: Recipe) => void;
}) {
  if (automations.state === "off") {
    return <Callout tone="neutral" title="Automations are turned off on this palaia" />;
  }
  if (automations.data === null) {
    return automations.state === "error" ? (
      <ErrorState
        title="Couldn't load your automations"
        details={automations.error}
        onRetry={onRefresh}
      >
        palaia didn't answer with the list of automations.
      </ErrorState>
    ) : (
      <LoadingState label="Loading your automations…" />
    );
  }
  return (
    <AutomationList automations={automations.data} onChanged={onRefresh} onUseRecipe={onUseRecipe} />
  );
}

export function Automations() {
  const toast = useToast();
  const [view, setView] = useTabParam(VIEWS);
  const [automations, refreshAutomations] = useList(() => api.listAutomations());
  const [hooks, refreshHooks] = useList(() => api.listHooks());
  const [dialog, setDialog] = useState<{ recipe: Recipe | null; n: number } | null>(null);
  const [hookDialog, setHookDialog] = useState(false);
  const [justCreated, setJustCreated] = useState<CreatedHook | null>(null);
  // Each opening of the dialog starts clean (it is keyed by this counter).
  const openings = useRef(0);

  function openNew(recipe: Recipe | null) {
    openings.current += 1;
    setDialog({ recipe, n: openings.current });
  }

  const primary =
    view === "automations" ? (
      automations.state !== "off" ? (
        <Button variant="primary" onClick={() => openNew(null)}>
          New automation
        </Button>
      ) : null
    ) : hooks.state !== "off" ? (
      <Button variant="primary" onClick={() => setHookDialog(true)}>
        Add address
      </Button>
    ) : null;

  return (
    <div className="stack">
      <PageHeader
        title="Automations"
        description="Let palaia act when something happens in your memories."
        actions={primary}
      />
      <Tabs<View>
        label="Automations"
        idPrefix="automations"
        value={view}
        onChange={setView}
        items={[
          { id: "automations", label: "Automations" },
          { id: "webhooks", label: "Webhooks" },
        ]}
      />
      <TabPanel idPrefix="automations" id={view}>
        {view === "automations" ? (
          <AutomationsView
            automations={automations}
            onRefresh={refreshAutomations}
            onUseRecipe={(recipe) => openNew(recipe)}
          />
        ) : (
          <WebhooksView
            hooks={hooks}
            onRefresh={refreshHooks}
            justCreated={justCreated}
            onDismissCreated={() => setJustCreated(null)}
          />
        )}
      </TabPanel>

      {dialog ? (
        <AutomationDialog
          key={dialog.n}
          open
          prefill={dialog.recipe}
          onClose={() => setDialog(null)}
          onCreated={(created) => {
            setDialog(null);
            toast.show(`${created.name} is on.`);
            refreshAutomations();
          }}
        />
      ) : null}
      <NewHookDialog
        open={hookDialog}
        onClose={() => setHookDialog(false)}
        onCreated={(created) => {
          setHookDialog(false);
          setJustCreated(created);
          refreshHooks();
        }}
      />
    </div>
  );
}
