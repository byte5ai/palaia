import type { ReactNode } from "react";

/** The default loading treatment everywhere — never a full-screen spinner
 * (system.md §2, Status; §0 "nothing blinks"). */
export function Skeleton({
  width = "100%",
  height = 14,
  className,
}: {
  width?: number | string;
  height?: number | string;
  className?: string;
}) {
  return (
    <span
      className={["lume-skeleton", className ?? ""].filter(Boolean).join(" ")}
      style={{ display: "block", width, height }}
      aria-hidden="true"
    />
  );
}

/** Three-dot inline indicator with a sentence saying what is being waited
 * for — Lume's one sanctioned non-skeleton loading affordance. */
export function Waiting({ children }: { children: ReactNode }) {
  return (
    <span className="waiting" role="status">
      <i aria-hidden="true" />
      <i aria-hidden="true" />
      <i aria-hidden="true" />
      {children}
    </span>
  );
}
