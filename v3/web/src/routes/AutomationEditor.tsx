/**
 * SPEC-307 deliverable #4: the "when → only when → then" automations, and
 * deliverable #5's ready-made recipes (shown on the empty list; one click
 * opens the New automation dialog prefilled — nothing runs until saved).
 *
 * Copy follows system.md §3 and principles §0.1: no protocol or
 * implementation word in a label, heading, button, pill or option (see the
 * lint in `Automations.test.tsx`). The event names stay the stored values,
 * never the labels.
 */
import { useEffect, useId, useState } from "react";

import {
  Button,
  ConfirmDialog,
  Dialog,
  Disclosure,
  EmptyState,
  Field,
  LabeledInput,
  ListRow,
  StatusPill,
  Switch,
  useToast,
} from "../components";
import type {
  AutomationAction,
  AutomationInfo,
  ConditionClause,
  DeliveryLogEntry,
} from "../lib/api/client";
import { api } from "../lib/api/client";
import { describeApiError } from "../lib/errors";
import { exactTime, timeAgo } from "../lib/format";
import { AutomationsIcon } from "../shell/icons";

/** Plain-language labels for the events a person is likely to pick. */
const TRIGGER_OPTIONS: { value: string; label: string }[] = [
  { value: "memory.entry.created", label: "A note is created" },
  { value: "memory.entry.updated", label: "A note is changed" },
  { value: "inbox.captured", label: "A note is captured" },
  { value: "curator.capture.needs_review", label: "palaia needs your review" },
  { value: "curator.run.finished", label: "palaia finishes sorting notes" },
  { value: "doctor.finding", label: "A problem is found" },
  { value: "client.connected", label: "An AI app connects for the first time" },
  { value: "*", label: "Anything happens" },
];

const ACTION_KIND_OPTIONS: { value: AutomationAction["kind"]; label: string }[] = [
  { value: "notification", label: "Send me a notification" },
  { value: "memory_write", label: "Save a note in a memory" },
  { value: "stash_set", label: "Save a value in the scratchpad" },
];

const CONDITION_FIELD_OPTIONS: { value: string; label: string }[] = [
  { value: "event", label: "what happened" },
  { value: "origin", label: "where it came from" },
  { value: "vault", label: "the memory" },
];

const CONDITION_OP_OPTIONS: { value: ConditionClause["op"]; label: string }[] = [
  { value: "equals", label: "is exactly" },
  { value: "contains", label: "contains" },
  { value: "prefix", label: "starts with" },
];

export interface Recipe {
  id: string;
  title: string;
  description: string;
  trigger_event: string;
  condition: ConditionClause[];
  action: AutomationAction;
}

/** Deliverable #5: ready-made automations for the empty list. */
const RECIPES: Recipe[] = [
  {
    id: "notify-review",
    title: "Notify me when palaia needs a review",
    description: "A notification whenever a captured note is too unclear to file on its own.",
    trigger_event: "curator.capture.needs_review",
    condition: [],
    action: { kind: "notification", title_template: "Review needed: {{data.permalink}}" },
  },
  {
    id: "notify-doctor",
    title: "Notify me when a problem is found",
    description: "A notification whenever palaia's health check finds something.",
    trigger_event: "doctor.finding",
    condition: [],
    action: { kind: "notification", title_template: "{{data.severity}}: {{data.detail}}" },
  },
  {
    id: "remember-capture",
    title: "Keep a running note of every capture",
    description: "Every captured note also saves a short note of what came in and where.",
    trigger_event: "inbox.captured",
    condition: [],
    action: {
      kind: "memory_write",
      vault: "",
      what_it_concerns_template: "capture {{data.capture_id}}",
      why_keep_template: "Captured via {{data.source}}.",
      content_template: "{{data.title}}",
    },
  },
  {
    id: "stash-last-client",
    title: "Remember which AI app connected last",
    description: "Saves the name of the most recently connected AI app as a value you can look up.",
    trigger_event: "client.connected",
    condition: [],
    action: {
      kind: "stash_set",
      namespace: "automations",
      key_template: "last-client",
      value_template: "{{data.client_name}}",
    },
  },
];

function defaultActionFor(kind: AutomationAction["kind"]): AutomationAction {
  if (kind === "memory_write") {
    return { kind, vault: "", what_it_concerns_template: "", why_keep_template: "", content_template: "" };
  }
  if (kind === "stash_set") {
    return { kind, namespace: "automations", key_template: "", value_template: "" };
  }
  return { kind, title_template: "", body_template: "" };
}

function triggerLabel(event: string): string {
  return TRIGGER_OPTIONS.find((opt) => opt.value === event)?.label ?? event;
}

function actionLabel(kind: AutomationAction["kind"]): string {
  return ACTION_KIND_OPTIONS.find((opt) => opt.value === kind)?.label ?? kind;
}

function Placeholders() {
  return (
    <Disclosure summary="Details you can insert">
      <ul className="automations-placeholders">
        <li>
          <code>{"{{event}}"}</code> — what happened
        </li>
        <li>
          <code>{"{{vault}}"}</code> — the memory it happened in
        </li>
        <li>
          <code>{"{{data.title}}"}</code> — one detail of it; each kind of event has its own
        </li>
      </ul>
    </Disclosure>
  );
}

function ActionFields({
  action,
  memories,
  onChange,
}: {
  action: AutomationAction;
  memories: string[] | null;
  onChange: (action: AutomationAction) => void;
}) {
  const memoryId = useId();
  if (action.kind === "memory_write") {
    return (
      <div className="stack stack--4">
        <Field label="Memory" controlId={memoryId}>
          {memories && memories.length > 0 ? (
            <select
              id={memoryId}
              className="input"
              value={action.vault}
              onChange={(e) => onChange({ ...action, vault: e.target.value })}
            >
              <option value="">Choose a memory…</option>
              {memories.map((key) => (
                <option key={key} value={key}>
                  {key}
                </option>
              ))}
            </select>
          ) : (
            <input
              id={memoryId}
              className="input"
              placeholder="work"
              value={action.vault}
              onChange={(e) => onChange({ ...action, vault: e.target.value })}
            />
          )}
        </Field>
        <LabeledInput
          label="What it concerns"
          value={action.what_it_concerns_template}
          onChange={(e) => onChange({ ...action, what_it_concerns_template: e.target.value })}
        />
        <LabeledInput
          label="Why keep it"
          value={action.why_keep_template}
          onChange={(e) => onChange({ ...action, why_keep_template: e.target.value })}
        />
        <LabeledInput
          label="What to save"
          value={action.content_template}
          onChange={(e) => onChange({ ...action, content_template: e.target.value })}
        />
        <Placeholders />
      </div>
    );
  }
  if (action.kind === "stash_set") {
    return (
      <div className="stack stack--4">
        <LabeledInput
          label="Value name"
          placeholder="last-client"
          value={action.key_template}
          onChange={(e) => onChange({ ...action, key_template: e.target.value })}
        />
        <LabeledInput
          label="Value"
          value={action.value_template}
          onChange={(e) => onChange({ ...action, value_template: e.target.value })}
        />
        <Disclosure summary="Advanced">
          <LabeledInput
            label="Scratchpad group"
            hint="Values are kept in groups. Most people keep the default."
            value={action.namespace}
            onChange={(e) => onChange({ ...action, namespace: e.target.value })}
          />
        </Disclosure>
        <Placeholders />
      </div>
    );
  }
  return (
    <div className="stack stack--4">
      <LabeledInput
        label="Title"
        value={action.title_template}
        onChange={(e) => onChange({ ...action, title_template: e.target.value })}
      />
      <LabeledInput
        label="Details"
        optional
        value={action.body_template ?? ""}
        onChange={(e) => onChange({ ...action, body_template: e.target.value })}
      />
      <Placeholders />
    </div>
  );
}

function ConditionEditor({
  condition,
  onChange,
}: {
  condition: ConditionClause[];
  onChange: (condition: ConditionClause[]) => void;
}) {
  function update(index: number, patch: Partial<ConditionClause>) {
    onChange(condition.map((c, i) => (i === index ? { ...c, ...patch } : c)));
  }
  function remove(index: number) {
    onChange(condition.filter((_, i) => i !== index));
  }
  function add() {
    onChange([...condition, { field: "event", op: "equals", value: "" }]);
  }
  return (
    <div className="stack stack--2">
      <span className="field__label">
        Only when<span className="field__optional">Optional</span>
      </span>
      {condition.length === 0 ? (
        <p className="t-sm t-muted">Every time it happens.</p>
      ) : null}
      {condition.map((clause, index) => {
        const isDataField = clause.field.startsWith("data.");
        return (
          <div key={index} className="automations-condition">
            <select
              className="input"
              aria-label="Which detail to check"
              value={isDataField ? "data" : clause.field}
              onChange={(e) =>
                update(index, { field: e.target.value === "data" ? "data." : e.target.value })
              }
            >
              {CONDITION_FIELD_OPTIONS.map((opt) => (
                <option key={opt.value} value={opt.value}>
                  {opt.label}
                </option>
              ))}
              <option value="data">a detail of the event</option>
            </select>
            {isDataField ? (
              <input
                className="input input--mono"
                aria-label="Name of the detail"
                placeholder="data.severity"
                value={clause.field}
                onChange={(e) => update(index, { field: e.target.value })}
              />
            ) : null}
            <select
              className="input"
              aria-label="How to compare"
              value={clause.op}
              onChange={(e) => update(index, { op: e.target.value as ConditionClause["op"] })}
            >
              {CONDITION_OP_OPTIONS.map((opt) => (
                <option key={opt.value} value={opt.value}>
                  {opt.label}
                </option>
              ))}
            </select>
            <input
              className="input"
              aria-label="Value to compare with"
              value={clause.value}
              onChange={(e) => update(index, { value: e.target.value })}
            />
            <Button variant="plain" size="sm" onClick={() => remove(index)}>
              Remove
            </Button>
          </div>
        );
      })}
      <div>
        <Button variant="plain" size="sm" onClick={add}>
          Add a condition
        </Button>
      </div>
    </div>
  );
}

/** The New automation dialog. `prefill` is a recipe, or `null` for a blank
 * one; keyed by the caller so each opening starts clean. */
export function AutomationDialog({
  open,
  prefill,
  onClose,
  onCreated,
}: {
  open: boolean;
  prefill: Recipe | null;
  onClose: () => void;
  onCreated: (automation: AutomationInfo) => void;
}) {
  const whenId = useId();
  const thenId = useId();
  const [name, setName] = useState(prefill?.title ?? "");
  const [triggerEvent, setTriggerEvent] = useState(prefill?.trigger_event ?? TRIGGER_OPTIONS[0].value);
  const [condition, setCondition] = useState<ConditionClause[]>(prefill?.condition ?? []);
  const [action, setAction] = useState<AutomationAction>(
    prefill?.action ?? defaultActionFor("notification"),
  );
  const [memories, setMemories] = useState<string[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (!open) return;
    let cancelled = false;
    api
      .listVaults()
      .then((list) => {
        if (!cancelled) setMemories(list.map((v) => v.key));
      })
      .catch(() => {
        if (!cancelled) setMemories(null);
      });
    return () => {
      cancelled = true;
    };
  }, [open]);

  async function submit() {
    setError(null);
    if (!name.trim()) {
      setError("Give this automation a name.");
      return;
    }
    setSaving(true);
    try {
      const created = await api.createAutomation({
        name: name.trim(),
        trigger_event: triggerEvent,
        action,
        condition,
      });
      onCreated(created);
    } catch (err) {
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
      title="New automation"
      description="When something happens, palaia does one thing."
      footer={
        <>
          <Button onClick={onClose} disabled={saving}>
            Cancel
          </Button>
          <Button variant="primary" onClick={() => void submit()} loading={saving}>
            {saving ? "Creating…" : "Create automation"}
          </Button>
        </>
      }
    >
      <LabeledInput label="Name" value={name} onChange={(e) => setName(e.target.value)} />
      <Field label="When" controlId={whenId}>
        <select
          id={whenId}
          className="input"
          value={triggerEvent}
          onChange={(e) => setTriggerEvent(e.target.value)}
        >
          {TRIGGER_OPTIONS.map((opt) => (
            <option key={opt.value} value={opt.value}>
              {opt.label}
            </option>
          ))}
        </select>
      </Field>
      <ConditionEditor condition={condition} onChange={setCondition} />
      <Field label="Then" controlId={thenId}>
        <select
          id={thenId}
          className="input"
          value={action.kind}
          onChange={(e) => setAction(defaultActionFor(e.target.value as AutomationAction["kind"]))}
        >
          {ACTION_KIND_OPTIONS.map((opt) => (
            <option key={opt.value} value={opt.value}>
              {opt.label}
            </option>
          ))}
        </select>
      </Field>
      <ActionFields action={action} memories={memories} onChange={setAction} />
      {error ? (
        <p className="field__error" role="alert">
          {error}
        </p>
      ) : null}
    </Dialog>
  );
}

const DELIVERY_TONE: Record<string, "ok" | "error" | "info" | "neutral"> = {
  delivered: "ok",
  dead: "error",
  pending: "info",
};

const DELIVERY_WORD: Record<string, string> = {
  delivered: "Done",
  dead: "Failed",
  pending: "Waiting",
};

function DeliveryLog({ automationId }: { automationId: string }) {
  const [entries, setEntries] = useState<DeliveryLogEntry[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    api
      .automationDeliveries(automationId)
      .then((list) => {
        if (!cancelled) setEntries(list);
      })
      .catch((err: unknown) => {
        if (!cancelled) setError(describeApiError(err));
      });
    return () => {
      cancelled = true;
    };
  }, [automationId]);

  if (error) return <p className="t-sm t-muted">Couldn't load the history. {error}</p>;
  if (entries === null) return <p className="t-sm t-muted">Loading the history…</p>;
  if (entries.length === 0) return <p className="t-sm t-muted">It hasn't run yet.</p>;
  return (
    <ul className="automations-log">
      {entries.map((entry) => (
        <li key={entry.id}>
          <span title={exactTime(entry.created_at)}>
            {timeAgo(entry.created_at)}
            {entry.test ? " · test" : ""}
          </span>
          <StatusPill tone={DELIVERY_TONE[entry.status] ?? "neutral"}>
            {DELIVERY_WORD[entry.status] ?? entry.status}
          </StatusPill>
        </li>
      ))}
    </ul>
  );
}

function AutomationRow({ automation, onChanged }: { automation: AutomationInfo; onChanged: () => void }) {
  const toast = useToast();
  const labelId = useId();
  const [testResult, setTestResult] = useState<DeliveryLogEntry | null>(null);
  const [testing, setTesting] = useState(false);
  const [showLog, setShowLog] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [deleting, setDeleting] = useState(false);

  // Issue 376: a refusal (a sign-in cookie rotated by another tab, …) is
  // shown, never swallowed.
  async function toggle(enabled: boolean) {
    try {
      await api.setAutomationEnabled(automation.id, enabled);
    } catch (err) {
      toast.show(describeApiError(err));
      return;
    }
    onChanged();
  }

  async function remove() {
    setDeleting(true);
    try {
      await api.deleteAutomation(automation.id);
    } catch (err) {
      toast.show(describeApiError(err));
      setDeleting(false);
      return;
    }
    setConfirmDelete(false);
    onChanged();
  }

  async function testFire() {
    setTesting(true);
    try {
      setTestResult(await api.testFireAutomation(automation.id, {}));
    } catch (err) {
      toast.show(describeApiError(err));
    } finally {
      setTesting(false);
    }
  }

  return (
    <div className="automations-row">
      <div className="automations-row__head">
        <div className="automations-row__main">
          <span className="listrow__title" id={labelId}>
            {automation.name}
          </span>
          <span className="listrow__desc">
            When {triggerLabel(automation.trigger_event).toLowerCase()}:{" "}
            {actionLabel(automation.action.kind).toLowerCase()}
            {automation.condition.length > 0 ? " (with a condition)" : ""}
          </span>
        </div>
        <div className="automations-row__actions">
          <span className="t-sm t-muted" aria-hidden="true">
            {automation.enabled ? "On" : "Off"}
          </span>
          <Switch checked={automation.enabled} onChange={(on) => void toggle(on)} labelledBy={labelId} />
        </div>
      </div>
      <div className="automations-row__tools">
        <Button size="sm" onClick={() => void testFire()} loading={testing}>
          Test it
        </Button>
        <Button
          size="sm"
          variant="plain"
          onClick={() => setShowLog((v) => !v)}
          aria-expanded={showLog}
        >
          {showLog ? "Hide history" : "History"}
        </Button>
        <Button size="sm" variant="destructive" onClick={() => setConfirmDelete(true)}>
          Delete
        </Button>
      </div>
      {testResult ? (
        <p className="t-sm" role="status">
          Test run:{" "}
          <StatusPill tone={DELIVERY_TONE[testResult.status] ?? "neutral"}>
            {DELIVERY_WORD[testResult.status] ?? testResult.status}
          </StatusPill>
          {testResult.last_error ? ` ${testResult.last_error}` : ""}
        </p>
      ) : null}
      {showLog ? <DeliveryLog automationId={automation.id} /> : null}
      <ConfirmDialog
        open={confirmDelete}
        onCancel={() => setConfirmDelete(false)}
        onConfirm={() => void remove()}
        title={`Delete ${automation.name}?`}
        confirmLabel="Delete automation"
        destructive
        busy={deleting}
      >
        <p>It stops right away. You can create it again later.</p>
      </ConfirmDialog>
    </div>
  );
}

/** The list of automations; on an empty list, the recipes to start from. */
export function AutomationList({
  automations,
  onChanged,
  onUseRecipe,
}: {
  automations: AutomationInfo[];
  onChanged: () => void;
  onUseRecipe: (recipe: Recipe) => void;
}) {
  if (automations.length === 0) {
    return (
      <div className="stack">
        <EmptyState mark={<AutomationsIcon className="icon icon--xl" />} title="No automations yet">
          Start from one of these, or create your own with New automation.
        </EmptyState>
        <div className="card">
          {RECIPES.map((recipe) => (
            <ListRow
              key={recipe.id}
              onClick={() => onUseRecipe(recipe)}
              title={recipe.title}
              description={recipe.description}
              chevron
            />
          ))}
        </div>
      </div>
    );
  }
  return (
    <div className="card">
      {automations.map((automation) => (
        <AutomationRow key={automation.id} automation={automation} onChanged={onChanged} />
      ))}
    </div>
  );
}
