import type { HTMLAttributes, ReactNode } from "react";

export type CardVariant = "default" | "flat" | "raised";

const VARIANT_CLASS: Record<CardVariant, string> = {
  default: "",
  flat: "card--flat",
  raised: "card--raised",
};

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

/** The container's own label — quiet, lowercase, secondary — never a
 * heading (system.md §1.2a). Its right slot is a mono meta string. */
export function CardHead({
  title,
  meta,
  children,
}: {
  title?: ReactNode;
  meta?: ReactNode;
  children?: ReactNode;
}) {
  return (
    <div className="card__head">
      {title !== undefined ? <span className="card__title">{title}</span> : null}
      {children}
      {meta !== undefined ? <span className="t-meta">{meta}</span> : null}
    </div>
  );
}

/** The head names a SUBJECT ("Claude Code CLI") rather than the
 * container ("clients") — a real heading, sans, ink (system.md §1.2a). */
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

export function CardFoot({ children, ...rest }: HTMLAttributes<HTMLDivElement>) {
  return (
    <div className="card__foot" {...rest}>
      {children}
    </div>
  );
}
