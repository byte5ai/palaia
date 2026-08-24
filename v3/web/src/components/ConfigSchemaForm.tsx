/**
 * SPEC-304 deliverable #2: one shared form renderer for every add-on's
 * `config_schema` — string / number / boolean / enum / secret, the fixed
 * subset the hub's install endpoint understands. Labels come straight
 * from the schema's own `title`s (jargon-free by the marketplace
 * curator's own convention, not by anything this component enforces);
 * a `secret` field never carries its previous value back in — see
 * `Marketplace.tsx`'s install flow for why (the hub never echoes one
 * back either).
 */
import type { MarketConfigSchema } from "../lib/api/client";
import { LabeledInput, SwitchRow } from "./Field";

export type ConfigFormValue = string | number | boolean;
export type ConfigFormValues = Record<string, ConfigFormValue>;

/** Field names the schema marks required but the current values leave
 * blank — used to disable the install action until every one is filled. */
export function missingRequiredFields(
  schema: MarketConfigSchema | null | undefined,
  values: ConfigFormValues,
): string[] {
  const required = schema?.required ?? [];
  return required.filter((key) => {
    const value = values[key];
    return value === undefined || value === "";
  });
}

export function ConfigSchemaForm({
  schema,
  values,
  onChange,
}: {
  schema: MarketConfigSchema | null | undefined;
  values: ConfigFormValues;
  onChange: (values: ConfigFormValues) => void;
}) {
  const properties = schema?.properties ?? {};
  const required = new Set(schema?.required ?? []);
  const keys = Object.keys(properties);

  if (keys.length === 0) {
    return <p className="t-xs t-muted">This add-on needs no setup — it is ready to connect.</p>;
  }

  function setValue(key: string, value: ConfigFormValue) {
    onChange({ ...values, [key]: value });
  }

  return (
    <div className="stack stack--3">
      {keys.map((key) => {
        const prop = properties[key] ?? {};
        const label = prop.title || key;
        const suffix = required.has(key) ? " (required)" : "";
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
          return (
            <div className="field" key={key}>
              <span className="field__label">
                {label}
                {suffix}
              </span>
              <select
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
            </div>
          );
        }

        if (prop.type === "secret") {
          return (
            <LabeledInput
              key={key}
              label={`${label}${suffix}`}
              type="password"
              autoComplete="off"
              hint="Stored safely on this hub and never shown again once you save it."
              value={typeof value === "string" ? value : ""}
              onChange={(event) => setValue(key, event.target.value)}
            />
          );
        }

        if (prop.type === "number") {
          return (
            <LabeledInput
              key={key}
              label={`${label}${suffix}`}
              type="number"
              value={value === undefined ? "" : String(value)}
              onChange={(event) =>
                setValue(key, event.target.value === "" ? "" : Number(event.target.value))
              }
            />
          );
        }

        return (
          <LabeledInput
            key={key}
            label={`${label}${suffix}`}
            hint={
              prop.format === "path"
                ? "A folder on this computer — shared with the add-on."
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
