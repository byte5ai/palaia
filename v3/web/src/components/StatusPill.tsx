import type { ReactNode } from "react";

/**
 * Status is always a word and a colour, never colour alone.
 *
 * - `ok`: Connected, Running, Backed up
 * - `warn`: Needs Cloud mode, Restart needed
 * - `error`: Can't reach, Failed
 * - `info`: Waiting for first use, Indexing
 * - `neutral`: Off, Not set up, Unreviewed
 */
export type StatusTone = "ok" | "warn" | "error" | "info" | "neutral";

export function StatusPill({
  tone = "neutral",
  dot = true,
  title,
  children,
}: {
  tone?: StatusTone;
  /** The small dot before the word; leave it on unless space is tight. */
  dot?: boolean;
  /** A tooltip with the precise value (an exact time, a reason). */
  title?: string;
  children: ReactNode;
}) {
  return (
    <span className={`pill pill--${tone}`} title={title}>
      {dot ? <span className="pill__dot" aria-hidden="true" /> : null}
      {children}
    </span>
  );
}
