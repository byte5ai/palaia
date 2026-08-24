/**
 * SPEC-307 deliverable #4: the trigger -> condition -> action automations
 * editor, plus deliverable #5's canned recipes. Copy is written to
 * system.md §3 rule 0 (plain language, no protocol/implementation word in
 * a label/heading/button/badge/option name) — see `Automations.test.tsx`'s
 * jargon lint, scoped to this editor's own controls.
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
} from "../components";
import type {
  AutomationAction,
  AutomationInfo,
  ConditionClause,
  DeliveryLogEntry,
} from "../lib/api/client";
import { api, ApiError } from "../lib/api/client";
import { AutomationsIcon } from "../shell/icons";

/** Plain-language labels for the event names a person is likely to pick as
 * a trigger — the technical name stays the wire value, never the label. */
const TRIGGER_OPTIONS: { value: string; label: string }[] = [
  { value: "memory.entry.created", label: "A memory is created" },
  { value: "memory.entry.updated", label: "A memory is changed" },
  { value: "inbox.captured", label: "Something is captured" },
  {
    value: "curator.capture.needs_review",
    label: "The curator needs a review",
  },
  { value: "curator.run.finished", label: "The curator finishes a pass" },
  { value: "doctor.finding", label: "A problem is found" },
  { value: "client.connected", label: "A client connects for the first time" },
  { value: "*", label: "Anything happens" },
];

const ACTION_KIND_OPTIONS: {
  value: AutomationAction["kind"];
  label: string;
}[] = [
  { value: "memory_write", label: "Save a memory" },
  { value: "stash_set", label: "Save a value" },
  { value: "notification", label: "Send me a notification" },
];

const CONDITION_FIELD_OPTIONS: { value: string; label: string }[] = [
  { value: "event", label: "what happened" },
  { value: "origin", label: "where it came from" },
  { value: "vault", label: "the vault" },
];

const CONDITION_OP_OPTIONS: { value: ConditionClause["op"]; label: string }[] =
  [
    { value: "equals", label: "is exactly" },
    { value: "contains", label: "contains" },
    { value: "prefix", label: "starts with" },
  ];

interface Recipe {
  id: string;
  title: string;
  description: string;
  trigger_event: string;
  condition: ConditionClause[];
  action: AutomationAction;
}

/** Deliverable #5: 3-4 canned automations on the empty screen. One click
 * prefills the form below — nothing installs on its own. */
const RECIPES: Recipe[] = [
  {
    id: "notify-review",
    title: "Notify me when the curator needs a review",
    description:
      "A dashboard notification appears whenever a capture is too ambiguous to file on its own.",
    trigger_event: "curator.capture.needs_review",
    condition: [],
    action: {
      kind: "notification",
      title_template: "Review needed: {{data.permalink}}",
    },
  },
  {
    id: "notify-doctor",
    title: "Notify me when a problem is found",
    description:
      "A dashboard notification appears whenever the doctor reports a finding.",
    trigger_event: "doctor.finding",
    condition: [],
    action: {
      kind: "notification",
      title_template: "{{data.severity}}: {{data.detail}}",
    },
  },
  {
    id: "remember-capture",
    title: "Keep a running note of every capture",
    description:
      "Every capture also lands a short memory of what came in and where.",
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
    title: "Remember which client connected last",
    description:
      "Saves the most recently connected client's name to a value you can look up.",
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
    return {
      kind,
      vault: "",
      what_it_concerns_template: "",
      why_keep_template: "",
      content_template: "",
    };
  }
  if (kind === "stash_set") {
    return {
      kind,
      namespace: "automations",
      key_template: "",
      value_template: "",
    };
  }
  return { kind, title_template: "", body_template: "" };
}

function ActionFields({
  action,
  onChange,
}: {
  action: AutomationAction;
  onChange: (action: AutomationAction) => void;
}) {
  if (action.kind === "memory_write") {
    return (
      <div className="stack stack--3">
        <LabeledInput
          label="Vault"
          placeholder="work"
          value={action.vault}
          onChange={(e) => onChange({ ...action, vault: e.target.value })}
        />
        <LabeledInput
          label="What it concerns"
          hint="Can use {{event}}, {{vault}}, {{data.<key>}}."
          value={action.what_it_concerns_template}
          onChange={(e) =>
            onChange({ ...action, what_it_concerns_template: e.target.value })
          }
        />
        <LabeledInput
          label="Why keep it"
          value={action.why_keep_template}
          onChange={(e) =>
            onChange({ ...action, why_keep_template: e.target.value })
          }
        />
        <LabeledInput
          label="What to remember"
          value={action.content_template}
          onChange={(e) =>
            onChange({ ...action, content_template: e.target.value })
          }
        />
      </div>
    );
  }
  if (action.kind === "stash_set") {
    return (
      <div className="stack stack--3">
        <LabeledInput
          label="Namespace"
          value={action.namespace}
          onChange={(e) => onChange({ ...action, namespace: e.target.value })}
        />
        <LabeledInput
          label="Key"
          hint="Can use {{event}}, {{vault}}, {{data.<key>}}."
          value={action.key_template}
          onChange={(e) =>
            onChange({ ...action, key_template: e.target.value })
          }
        />
        <LabeledInput
          label="Value"
          value={action.value_template}
          onChange={(e) =>
            onChange({ ...action, value_template: e.target.value })
          }
        />
      </div>
    );
  }
  return (
    <div className="stack stack--3">
      <LabeledInput
        label="Title"
        hint="Can use {{event}}, {{vault}}, {{data.<key>}}."
        value={action.title_template}
        onChange={(e) =>
          onChange({ ...action, title_template: e.target.value })
        }
      />
      <LabeledInput
        label="Details"
        value={action.body_template ?? ""}
        onChange={(e) => onChange({ ...action, body_template: e.target.value })}
      />
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
      <span className="field__label">Only when (optional)</span>
      {condition.map((clause, index) => {
        const isDataField = clause.field.startsWith("data.");
        return (
          <div
            key={index}
            className="row row--wrap"
            style={{ gap: 8, alignItems: "center" }}
          >
            <select
              className="input"
              value={isDataField ? "data" : clause.field}
              onChange={(e) =>
                update(index, {
                  field: e.target.value === "data" ? "data." : e.target.value,
                })
              }
            >
              {CONDITION_FIELD_OPTIONS.map((opt) => (
                <option key={opt.value} value={opt.value}>
                  {opt.label}
                </option>
              ))}
              <option value="data">a data field</option>
            </select>
            {isDataField ? (
              <input
                className="input"
                style={{ width: 140 }}
                placeholder="data.severity"
                value={clause.field}
                onChange={(e) => update(index, { field: e.target.value })}
              />
            ) : null}
            <select
              className="input"
              value={clause.op}
              onChange={(e) =>
                update(index, { op: e.target.value as ConditionClause["op"] })
              }
            >
              {CONDITION_OP_OPTIONS.map((opt) => (
                <option key={opt.value} value={opt.value}>
                  {opt.label}
                </option>
              ))}
            </select>
            <input
              className="input"
              style={{ width: 140 }}
              value={clause.value}
              onChange={(e) => update(index, { value: e.target.value })}
            />
            <Button variant="ghost" size="sm" onClick={() => remove(index)}>
              Remove
            </Button>
          </div>
        );
      })}
      <div>
        <Button variant="ghost" size="sm" onClick={add}>
          Add a condition
        </Button>
      </div>
    </div>
  );
}

function AutomationForm({
  prefill,
  onCreated,
}: {
  prefill: Recipe | null;
  onCreated: () => void;
}) {
  const [name, setName] = useState(prefill?.title ?? "");
  const [triggerEvent, setTriggerEvent] = useState(
    prefill?.trigger_event ?? TRIGGER_OPTIONS[0].value,
  );
  const [condition, setCondition] = useState<ConditionClause[]>(
    prefill?.condition ?? [],
  );
  const [action, setAction] = useState<AutomationAction>(
    prefill?.action ?? defaultActionFor("notification"),
  );
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  async function submit() {
    setError(null);
    if (!name.trim()) {
      setError("Give this automation a name.");
      return;
    }
    setSaving(true);
    try {
      await api.createAutomation({
        name: name.trim(),
        trigger_event: triggerEvent,
        action,
        condition,
      });
      setName("");
      setCondition([]);
      setAction(defaultActionFor("notification"));
      onCreated();
    } catch (err) {
      setError(
        err instanceof ApiError &&
          typeof err.body === "object" &&
          err.body !== null
          ? String(
              (err.body as { detail?: string }).detail ??
                "Could not create the automation.",
            )
          : "Could not create the automation.",
      );
    } finally {
      setSaving(false);
    }
  }

  return (
    <Card>
      <CardHead title="new automation" />
      <CardBody className="stack stack--4">
        <LabeledInput
          label="Name"
          value={name}
          onChange={(e) => setName(e.target.value)}
        />
        <div className="stack stack--2">
          <span className="field__label">When</span>
          <select
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
        </div>
        <ConditionEditor condition={condition} onChange={setCondition} />
        <div className="stack stack--2">
          <span className="field__label">Then</span>
          <select
            className="input"
            value={action.kind}
            onChange={(e) =>
              setAction(
                defaultActionFor(e.target.value as AutomationAction["kind"]),
              )
            }
          >
            {ACTION_KIND_OPTIONS.map((opt) => (
              <option key={opt.value} value={opt.value}>
                {opt.label}
              </option>
            ))}
          </select>
          <ActionFields action={action} onChange={setAction} />
        </div>
        {error ? <p className="field__error">{error}</p> : null}
        <div className="row">
          <Button variant="primary" onClick={submit} disabled={saving}>
            {saving ? "Creating…" : "Create automation"}
          </Button>
        </div>
      </CardBody>
    </Card>
  );
}

function DeliveryLog({ automationId }: { automationId: string }) {
  const [entries, setEntries] = useState<DeliveryLogEntry[] | null>(null);

  function refresh() {
    api
      .automationDeliveries(automationId)
      .then(setEntries)
      .catch(() => setEntries([]));
  }

  return (
    <div className="stack stack--2">
      <Button variant="ghost" size="sm" onClick={refresh}>
        {entries === null
          ? "Show delivery history"
          : "Refresh delivery history"}
      </Button>
      {entries !== null ? (
        entries.length === 0 ? (
          <p className="t-xs t-subtle">No deliveries yet.</p>
        ) : (
          <div className="stack stack--1">
            {entries.map((entry) => (
              <div
                key={entry.id}
                className="row"
                style={{ justifyContent: "space-between" }}
              >
                <span className="t-xs t-mono">
                  {entry.event_name} {entry.test ? "(test)" : ""}
                </span>
                <Badge
                  variant={
                    entry.status === "delivered"
                      ? "ok"
                      : entry.status === "dead"
                        ? "risk"
                        : "neutral"
                  }
                >
                  {entry.status}
                </Badge>
              </div>
            ))}
          </div>
        )
      ) : null}
    </div>
  );
}

function AutomationRow({
  automation,
  onChanged,
}: {
  automation: AutomationInfo;
  onChanged: () => void;
}) {
  const [testResult, setTestResult] = useState<DeliveryLogEntry | null>(null);
  const [showLog, setShowLog] = useState(false);

  async function toggle(enabled: boolean) {
    await api.setAutomationEnabled(automation.id, enabled);
    onChanged();
  }

  async function remove() {
    await api.deleteAutomation(automation.id);
    onChanged();
  }

  async function testFire() {
    const result = await api.testFireAutomation(automation.id, {});
    setTestResult(result);
  }

  const triggerLabel =
    TRIGGER_OPTIONS.find((opt) => opt.value === automation.trigger_event)
      ?.label ?? automation.trigger_event;
  const actionLabel =
    ACTION_KIND_OPTIONS.find((opt) => opt.value === automation.action.kind)
      ?.label ?? automation.action.kind;

  return (
    <div className="card" style={{ padding: 0 }}>
      <div className="card__body stack stack--3">
        <div
          className="row"
          style={{ justifyContent: "space-between", alignItems: "flex-start" }}
        >
          <div className="stack stack--1">
            <span className="t-sm">{automation.name}</span>
            <span className="t-xs t-subtle">
              When {triggerLabel.toLowerCase()} → {actionLabel.toLowerCase()}
            </span>
          </div>
          <Badge variant={automation.enabled ? "ok" : "neutral"}>
            {automation.enabled ? "on" : "off"}
          </Badge>
        </div>
        <div
          className="row row--wrap"
          style={{ justifyContent: "space-between" }}
        >
          <div className="row" style={{ gap: 8 }}>
            <Button
              variant={automation.enabled ? "secondary" : "primary"}
              size="sm"
              onClick={() => toggle(!automation.enabled)}
            >
              {automation.enabled ? "Turn off" : "Turn on"}
            </Button>
            <Button variant="ghost" size="sm" onClick={testFire}>
              Test this automation
            </Button>
          </div>
          <Button variant="risk" size="sm" onClick={remove}>
            Delete
          </Button>
        </div>
        {testResult ? (
          <p className="t-xs t-subtle">
            Test run: <strong>{testResult.status}</strong>
            {testResult.last_error ? ` — ${testResult.last_error}` : ""}
          </p>
        ) : null}
        <Button variant="ghost" size="sm" onClick={() => setShowLog((v) => !v)}>
          {showLog ? "Hide history" : "Show history"}
        </Button>
        {showLog ? <DeliveryLog automationId={automation.id} /> : null}
      </div>
    </div>
  );
}

export function AutomationEditor() {
  const [automations, setAutomations] = useState<AutomationInfo[] | null>(null);
  const [available, setAvailable] = useState(true);
  const [prefill, setPrefill] = useState<Recipe | null>(null);

  function refresh() {
    api
      .listAutomations()
      .then((list) => {
        setAutomations(list);
        setAvailable(true);
      })
      .catch((err) => {
        if (err instanceof ApiError && err.status === 404) setAvailable(false);
      });
  }

  useEffect(refresh, []);

  if (!available) {
    return (
      <Card>
        <CardBody>
          <p className="t-sm t-muted">
            This hub has no automations store mounted, so no automation can be
            configured from here yet.
          </p>
        </CardBody>
      </Card>
    );
  }

  return (
    <section className="stack stack--4">
      {automations && automations.length === 0 ? (
        <Card>
          <CardHead title="try one of these" />
          <CardBody className="stack stack--2">
            {RECIPES.map((recipe) => (
              <button
                key={recipe.id}
                type="button"
                className="listrow"
                style={{ width: "100%", textAlign: "left" }}
                onClick={() => setPrefill(recipe)}
              >
                <div className="stack stack--1">
                  <span className="t-sm">{recipe.title}</span>
                  <span className="t-xs t-subtle">{recipe.description}</span>
                </div>
              </button>
            ))}
          </CardBody>
        </Card>
      ) : null}

      <AutomationForm
        key={prefill?.id ?? "blank"}
        prefill={prefill}
        onCreated={() => {
          setPrefill(null);
          refresh();
        }}
      />

      <div className="card">
        <div className="card__head">
          <span className="card__title">automations</span>
          <span className="t-meta">
            {automations ? `${automations.length} configured` : "…"}
          </span>
        </div>
        <div className="card__body stack stack--3">
          {automations && automations.length === 0 ? (
            <EmptyState
              mark={<AutomationsIcon className="icon--lg" />}
              title="No automations yet."
            >
              Pick a recipe above, or build your own: when something happens, do
              one thing.
            </EmptyState>
          ) : (
            (automations ?? []).map((automation) => (
              <AutomationRow
                key={automation.id}
                automation={automation}
                onChanged={refresh}
              />
            ))
          )}
        </div>
      </div>
    </section>
  );
}
