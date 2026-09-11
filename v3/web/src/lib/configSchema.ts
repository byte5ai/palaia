/** Pure helpers over an add-on's config schema (issue 399 moved
 * `missingRequiredFields` here from `ConfigSchemaForm.tsx`, which exports a
 * component). */
import type { ConfigFormValues } from "../components/ConfigSchemaForm";
import type { MarketConfigSchema } from "./api/client";

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
