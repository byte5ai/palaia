import type { ReactNode } from "react";

/** A grey placeholder line while something loads. Prefer `LoadingState`,
 * which waits 300 ms before showing any. */
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
      className={["skeleton", className ?? ""].filter(Boolean).join(" ")}
      style={{ width, height }}
      aria-hidden="true"
    />
  );
}

/** Three dots and a sentence saying what is being waited for — for a wait
 * on something outside the dashboard (an AI app's first request). */
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
