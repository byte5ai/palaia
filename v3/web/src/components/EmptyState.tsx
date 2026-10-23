import type { ReactNode } from "react";

import { Button } from "./Button";
import { Callout } from "./Callout";
import { Disclosure } from "./Disclosure";
import { Skeleton } from "./Skeleton";

/**
 * Nothing here yet, on a page of its own: a 40 px icon, a title, one
 * sentence, and the one action that fills it. For an empty list inside a
 * card use `InlineEmpty` instead — one line, no icon.
 */
export function EmptyState({
  mark,
  title,
  actions,
  children,
}: {
  mark?: ReactNode;
  title: ReactNode;
  actions?: ReactNode;
  children?: ReactNode;
}) {
  return (
    <div className="empty">
      {mark ? (
        <div className="empty__mark" aria-hidden="true">
          {mark}
        </div>
      ) : null}
      <h2 className="empty__title">{title}</h2>
      {children ? <p className="empty__text">{children}</p> : null}
      {actions ? <div className="row row--wrap">{actions}</div> : null}
    </div>
  );
}

/** An empty list inside a card or section: one line. */
export function InlineEmpty({ children }: { children: ReactNode }) {
  return <p className="empty--inline">{children}</p>;
}

/**
 * Loading: grey placeholder lines that appear only after 300 ms, so a
 * fast answer never flashes. `label` is read out to screen readers.
 */
export function LoadingState({ label = "Loading…", lines = 3 }: { label?: string; lines?: number }) {
  return (
    <div className="skeleton-group" role="status" aria-live="polite">
      <span className="sr-only">{label}</span>
      {Array.from({ length: lines }, (_, index) => (
        <Skeleton key={index} width={index === lines - 1 ? "60%" : "100%"} height={16} />
      ))}
    </div>
  );
}

/**
 * Something failed to load. Never rendered as an empty state: it says what
 * could not be loaded, offers Try again, and keeps the raw reason behind
 * "Details" for anyone who needs it.
 */
export function ErrorState({
  title,
  children,
  details,
  onRetry,
}: {
  title: ReactNode;
  children?: ReactNode;
  /** The hub's own error text. */
  details?: ReactNode;
  onRetry?: () => void;
}) {
  return (
    <Callout
      tone="error"
      title={title}
      role="alert"
      actions={
        onRetry ? (
          <Button size="sm" onClick={onRetry}>
            Try again
          </Button>
        ) : undefined
      }
    >
      {children}
      {details ? (
        <Disclosure summary="Details">
          <p className="t-mono">{details}</p>
        </Disclosure>
      ) : null}
    </Callout>
  );
}
