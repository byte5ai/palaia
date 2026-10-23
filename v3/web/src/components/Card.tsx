import type { HTMLAttributes, ReactNode } from "react";

export type CardVariant = "default" | "flat" | "raised";

const VARIANT_CLASS: Record<CardVariant, string> = {
  default: "",
  flat: "card--flat",
  raised: "card--raised",
};

/** A white surface on the canvas: 14 px corners, a hairline border. Cards
 * group one subject; settings use one card per group of rows. */
export function Card({
  variant = "default",
  className,
  children,
  ...rest
}: HTMLAttributes<HTMLDivElement> & { variant?: CardVariant }) {
  return (
    <div
      className={["card", VARIANT_CLASS[variant], className ?? ""].filter(Boolean).join(" ")}
      {...rest}
    >
      {children}
    </div>
  );
}

/**
 * A card's title row: the title (title-2), an optional one-line
 * description under it, and actions or a status on the right.
 */
export function CardHeader({
  title,
  description,
  actions,
  titleId,
}: {
  title: ReactNode;
  description?: ReactNode;
  actions?: ReactNode;
  /** An id for the title, so a section can be labelled by it. */
  titleId?: string;
}) {
  return (
    <div className="card__head">
      <div className="grow">
        <h2 className="card__title" id={titleId}>
          {title}
        </h2>
        {description ? <p className="card__desc">{description}</p> : null}
      </div>
      {actions ? <div className="card__head-end">{actions}</div> : null}
    </div>
  );
}

/** The earlier head API: a title plus a meta string and actions. New code
 * uses `CardHeader`. */
export function CardHead({
  title,
  meta,
  children,
}: {
  title?: ReactNode;
  meta?: ReactNode;
  children?: ReactNode;
}) {
  const metaNode = meta !== undefined ? <span className="t-meta">{meta}</span> : null;
  // With a title, `children` are the head's actions: they sit at the right
  // edge together with `meta`. Without a title, `children` are the head's
  // left-hand content (e.g. a CardSubject) and stay where they are.
  if (title !== undefined && children !== undefined) {
    return (
      <div className="card__head">
        <span className="card__title">{title}</span>
        <span className="card__head-end">
          {metaNode}
          {children}
        </span>
      </div>
    );
  }
  return (
    <div className="card__head">
      {title !== undefined ? <span className="card__title">{title}</span> : null}
      {children}
      {metaNode}
    </div>
  );
}

/** A head that names its subject ("Claude Code CLI"). */
export function CardSubject({ children }: { children: ReactNode }) {
  return <span className="card__subject">{children}</span>;
}

export function CardBody({
  tight = false,
  className,
  children,
  ...rest
}: HTMLAttributes<HTMLDivElement> & { tight?: boolean }) {
  return (
    <div
      className={["card__body", tight ? "card__body--tight" : "", className ?? ""]
        .filter(Boolean)
        .join(" ")}
      {...rest}
    >
      {children}
    </div>
  );
}

export function CardFoot({ children, className, ...rest }: HTMLAttributes<HTMLDivElement>) {
  return (
    <div className={["card__foot", className ?? ""].filter(Boolean).join(" ")} {...rest}>
      {children}
    </div>
  );
}
