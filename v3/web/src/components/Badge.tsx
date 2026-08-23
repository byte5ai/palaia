import type { ReactNode } from "react";

export type BadgeVariant = "neutral" | "ok" | "warn" | "risk" | "info";

const VARIANT_CLASS: Record<BadgeVariant, string> = {
  neutral: "",
  ok: "badge--ok",
  warn: "badge--warn",
  risk: "badge--risk",
  info: "badge--info",
};

const DOT_CLASS: Record<BadgeVariant, string> = {
  neutral: "",
  ok: "dot--ok",
  warn: "dot--warn",
  risk: "dot--risk",
  info: "",
};

/** Text and an optional dot — never a filled pill (colors_and_type.css
 * §2.6). `live` swaps the dot for the accent pulse used by event-stream-
 * backed liveness (system.md §2, Status). */
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
    <span className={["badge", VARIANT_CLASS[variant]].filter(Boolean).join(" ")}>
      {dot ? (
        <span className={["dot", live ? "dot--live" : DOT_CLASS[variant]].join(" ")} />
      ) : null}
      {children}
    </span>
  );
}

export function Dot({
  variant = "neutral",
  live = false,
}: {
  variant?: BadgeVariant;
  live?: boolean;
}) {
  return <span className={["dot", live ? "dot--live" : DOT_CLASS[variant]].join(" ")} />;
}

export function Chip({ mono = false, children }: { mono?: boolean; children: ReactNode }) {
  return <span className={["chip", mono ? "chip--mono" : ""].filter(Boolean).join(" ")}>{children}</span>;
}
