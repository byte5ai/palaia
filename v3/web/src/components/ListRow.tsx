import type { ReactNode } from "react";
import { Link } from "react-router-dom";

import { ChevronRightIcon } from "../shell/icons";

/**
 * One row of a list: an optional round icon, a title, one line of
 * description, and something on the right (a status pill, a value, a
 * control, or a chevron when the whole row is a link).
 *
 * - `to`: the row is a router link (with a chevron).
 * - `onClick`: the row is a button.
 * - `setting`: label and helper on the left, the control (`trailing`) on
 *   the right; the row itself is not clickable.
 *
 * Without `title`, `children` render as the row's content (the earlier
 * API, still used by a few screens).
 */
export function ListRow({
  icon,
  title,
  description,
  meta,
  trailing,
  to,
  onClick,
  selected = false,
  setting = false,
  chevron,
  labelId,
  children,
}: {
  icon?: ReactNode;
  title?: ReactNode;
  description?: ReactNode;
  /** A second, quieter line (a timestamp, a count). */
  meta?: ReactNode;
  trailing?: ReactNode;
  to?: string;
  onClick?: () => void;
  selected?: boolean;
  setting?: boolean;
  /** Defaults to on for link rows. */
  chevron?: boolean;
  /** An id for the title, so the trailing control can be labelled by it. */
  labelId?: string;
  children?: ReactNode;
}) {
  const className = [
    "listrow",
    setting ? "listrow--setting" : "",
    selected ? "listrow--selected" : "",
  ]
    .filter(Boolean)
    .join(" ");
  const showChevron = chevron ?? Boolean(to);
  const body =
    title !== undefined ? (
      <>
        {icon ? (
          <span className="listrow__icon" aria-hidden="true">
            {icon}
          </span>
        ) : null}
        <span className="listrow__main">
          <span className="listrow__title" id={labelId}>
            {title}
          </span>
          {description ? <span className="listrow__desc">{description}</span> : null}
          {meta ? <span className="listrow__meta">{meta}</span> : null}
        </span>
        {trailing || showChevron ? (
          <span className="listrow__trail">
            {trailing}
            {showChevron ? <ChevronRightIcon className="icon--sm listrow__chevron" /> : null}
          </span>
        ) : null}
      </>
    ) : (
      children
    );

  if (to) {
    return (
      <Link className={className} to={to} aria-current={selected ? "page" : undefined}>
        {body}
      </Link>
    );
  }
  if (onClick) {
    return (
      <button
        type="button"
        className={className}
        onClick={onClick}
        aria-current={selected ? "true" : undefined}
      >
        {body}
      </button>
    );
  }
  return <div className={className}>{body}</div>;
}

export function ListRowTitle({ children }: { children: ReactNode }) {
  return <span className="listrow__title">{children}</span>;
}

export function ListRowMeta({ children }: { children: ReactNode }) {
  return <span className="listrow__meta">{children}</span>;
}
