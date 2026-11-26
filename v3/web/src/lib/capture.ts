/**
 * A captured note is stored as its reason followed by five tagged lines
 * (`palaia_hub.gateway.inbox.compose_capture_body`):
 *
 *     <why keep>
 *
 *     - [entity] <what it concerns>
 *     - [why] <why keep>
 *     - [raw] <the text>
 *     - [source] <where it came from>
 *     - [capture_hash] <hex>
 *
 * That is the storage form, for the curator and for search. A person reads
 * the text, what it is about, why it was kept and where it came from; the
 * tags and the hash are not shown.
 */
export interface Capture {
  /** What it concerns. */
  about: string;
  /** Why it was kept. */
  why: string;
  /** The captured text itself. */
  text: string;
  /** Where it came from ("chat", "agent capture, 23 Oct"). */
  source: string;
}

const CAPTURE =
  /(?:^|\n)- \[entity\] (.*)\n- \[why\] ([\s\S]*?)\n- \[raw\] ([\s\S]*?)\n- \[source\] (.*)\n- \[capture_hash\] [0-9a-f]+\s*$/;

/** The parts of a captured note's body, or `null` for any other note. */
export function parseCapture(body: string): Capture | null {
  const match = CAPTURE.exec(body);
  if (!match) return null;
  const [, about, why, text, source] = match;
  return { about: about!.trim(), why: why!.trim(), text: text!.trim(), source: source!.trim() };
}
