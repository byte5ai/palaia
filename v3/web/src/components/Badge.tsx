import type { ReactNode } from "react";

import { StatusPill, type StatusTone } from "./StatusPill";

export type BadgeVariant = "neutral" | "ok" | "warn" | "risk" | "info";

const TONE: Record<BadgeVariant, StatusTone> = {
  neutral: "neutral",
  ok: "ok",
  warn: "warn",
  risk: "error",
  info: "info",
};

/** The earlier status API, now a `StatusPill` (`risk` is the `error`
 * tone). New code uses `StatusPill` directly. `live` keeps the pill but
 * marks it as backed by the live event stream. */
export function Badge({
  variant = "neutral",
  dot = true,
  live = false,
  children,
}: {
  variant?: BadgeVariant;
  dot?: boolean;
  live?: boolean;
  children: ReactNode;
}) {
  return (
    <StatusPill tone={live && variant === "neutral" ? "ok" : TONE[variant]} dot={dot}>
      {children}
    </StatusPill>
  );
}

const DOT_CLASS: Record<BadgeVariant, string> = {
  neutral: "",
  ok: "dot--ok",
  warn: "dot--warn",
  risk: "dot--risk",
  info: "dot--info",
};

/** A bare status dot, for places where the word sits right next to it. */
export function Dot({
  variant = "neutral",
  live = false,
}: {
  variant?: BadgeVariant;
  live?: boolean;
}) {
  return (
    <span
      className={["dot", live ? "dot--live" : DOT_CLASS[variant]].filter(Boolean).join(" ")}
      aria-hidden="true"
    />
  );
}

/** A small label: a path, a tag, a short id. */
export function Chip({ mono = false, children }: { mono?: boolean; children: ReactNode }) {
  return <span className={["chip", mono ? "chip--mono" : ""].filter(Boolean).join(" ")}>{children}</span>;
}
