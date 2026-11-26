/**
 * The description the hub writes when nobody gave one (the engine's
 * `palaia vault '<key>'.` and the gateway's "A palaia memory vault.") is
 * not something the person wrote — show it as missing (report §3.6).
 */
export function isGeneratedDescription(purpose: string | null | undefined, key: string): boolean {
  const text = (purpose ?? "").trim();
  if (!text) return true;
  return (
    text === `palaia vault '${key}'.` ||
    text === `palaia vault ${key}.` ||
    text === "A palaia memory vault."
  );
}
