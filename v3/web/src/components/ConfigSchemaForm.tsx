/**
 * SPEC-304 deliverable #2: one shared form renderer for every add-on's
 * `config_schema` — string / number / boolean / enum / secret, the fixed
 * subset the hub's install endpoint understands. Labels come straight
 * from the schema's own `title`s (jargon-free by the add-on index's own
 * convention, not by anything this component enforces). Fields the schema
 * does not require say "Optional"; required ones carry no marker
 * (system.md §2, Field). A `secret` field never carries its previous value
 * back in — the hub never echoes one back either.
 */
import { useId } from "react";
import type { MarketConfigSchema } from "../lib/api/client";
import { Field, LabeledInput, SwitchRow } from "./Field";

export type ConfigFormValue = string | number | boolean;
export type ConfigFormValues = Record<string, ConfigFormValue>;

/** Field names the schema marks required but the current values leave
 * blank — used to disable the install action until every one is filled. */

export function ConfigSchemaForm({
  schema,
  values,
  onChange,
}: {
  schema: MarketConfigSchema | null | undefined;
  values: ConfigFormValues;
  onChange: (values: ConfigFormValues) => void;
}) {
  const formId = useId();
  const properties = schema?.properties ?? {};
  const required = new Set(schema?.required ?? []);
  const keys = Object.keys(properties);

  if (keys.length === 0) {
    return (
      <p className="t-sm t-muted">Nothing to set up. It's ready to install.</p>
    );
  }

  function setValue(key: string, value: ConfigFormValue) {
    onChange({ ...values, [key]: value });
  }

  return (
    <div className="stack stack--3">
      {keys.map((key) => {
        const prop = properties[key] ?? {};
        const label = prop.title || key;
        const optional = !required.has(key);
        const value = values[key];

        if (prop.type === "boolean") {
          return (
            <SwitchRow
              key={key}
              label={label}
              checked={Boolean(value)}
              onChange={(checked) => setValue(key, checked)}
            />
          );
        }

        if (prop.enum && prop.enum.length > 0) {
          const selectId = `${formId}-${key}`;
          return (
            <Field key={key} label={label} optional={optional} controlId={selectId}>
              <select
                id={selectId}
                className="input"
                value={typeof value === "string" ? value : ""}
                onChange={(event) => setValue(key, event.target.value)}
              >
                <option value="" disabled>
                  Choose one…
                </option>
                {prop.enum.map((choice) => (
                  <option key={choice} value={choice}>
                    {choice}
                  </option>
                ))}
              </select>
            </Field>
          );
        }

        if (prop.type === "secret") {
          return (
            <LabeledInput
              key={key}
              label={label}
              optional={optional}
              type="password"
              autoComplete="off"
              hint="Saved in palaia and never shown again."
              value={typeof value === "string" ? value : ""}
              onChange={(event) => setValue(key, event.target.value)}
            />
          );
        }

        if (prop.type === "number") {
          return (
            <LabeledInput
              key={key}
              label={label}
              optional={optional}
              type="number"
              value={value === undefined ? "" : String(value)}
              onChange={(event) =>
                setValue(
                  key,
                  event.target.value === "" ? "" : Number(event.target.value),
                )
              }
            />
          );
        }

        return (
          <LabeledInput
            key={key}
            label={label}
            optional={optional}
            hint={
              prop.format === "path"
                ? "A folder on the server palaia runs on, shared with the add-on."
                : undefined
            }
            value={typeof value === "string" ? value : ""}
            onChange={(event) => setValue(key, event.target.value)}
          />
        );
      })}
    </div>
  );
}
