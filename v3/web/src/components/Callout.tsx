import type { ReactNode } from "react";

import { ErrorIcon, InfoIcon, ReviewIcon, WarningIcon } from "../shell/icons";
import type { StatusTone } from "./StatusPill";

const ICON: Record<StatusTone, (props: { className?: string }) => ReactNode> = {
  ok: ReviewIcon,
  warn: WarningIcon,
  error: ErrorIcon,
  info: InfoIcon,
  neutral: InfoIcon,
};

/**
 * One tinted box for a state worth stopping at: a blocked action, a
 * restart that is due, an error. A one-sentence title, at most one more
 * sentence, and — when the dashboard can fix it — the button that does.
 */
export function Callout({
  tone = "info",
  title,
  children,
  actions,
  role,
}: {
  tone?: StatusTone;
  title: ReactNode;
  children?: ReactNode;
  actions?: ReactNode;
  /** "alert" for an error the person just caused; "status" for a
   * state that changed by itself. Leave unset for a standing state. */
  role?: "alert" | "status";
}) {
  const Icon = ICON[tone];
  return (
    <div className={`callout callout--${tone}`} role={role}>
      <Icon className="icon" />
      <div className="callout__main">
        <p className="callout__title">{title}</p>
        {children ? <div className="callout__text">{children}</div> : null}
        {actions ? <div className="callout__actions">{actions}</div> : null}
      </div>
    </div>
  );
}
