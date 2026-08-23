import type { ReactNode } from "react";

/** An empty screen has nothing selected, so it has nothing to spend
 * accent on — the mark is a neutral raised chip, the title is a real
 * heading (sans, per the serif rule), and it must name the next action
 * (system.md §2, Empty & first-run; principles.md §3). */
export function EmptyState({
  mark,
  title,
  actions,
  children,
}: {
  mark: ReactNode;
  title: ReactNode;
  actions?: ReactNode;
  children?: ReactNode;
}) {
  return (
    <div className="empty">
      <div className="empty__mark">{mark}</div>
      <h2 className="empty__title">{title}</h2>
      {children ? <p className="empty__text">{children}</p> : null}
      {actions ? <div className="row row--wrap">{actions}</div> : null}
    </div>
  );
}

/** The done state: an achievement, not an absence (system.md §1.6). */
export function DoneState({
  mark,
  title,
  recapLabel,
  recap,
  children,
}: {
  mark: ReactNode;
  title: ReactNode;
  recapLabel?: ReactNode;
  recap?: ReactNode;
  children?: ReactNode;
}) {
  return (
    <div className="empty empty--done">
      <div className="empty__mark">{mark}</div>
      <h2 className="empty__title">{title}</h2>
      {children ? <p className="empty__text">{children}</p> : null}
      {recap ? (
        <div className="empty__recap">
          {recapLabel ? <span className="t-over">{recapLabel}</span> : null}
          {recap}
        </div>
      ) : null}
    </div>
  );
}
