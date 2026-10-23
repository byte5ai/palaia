import type { ButtonHTMLAttributes, ReactNode } from "react";
import { Link, type LinkProps } from "react-router-dom";

import { buttonClass, type ButtonSize, type ButtonVariant } from "./buttonClass";

export type { ButtonSize, ButtonVariant } from "./buttonClass";

export interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonVariant;
  size?: ButtonSize;
  /** Full width — for a one-column container, or the actions of a bottom sheet. */
  block?: boolean;
  /** Shows a spinner and disables the button. Pass the verb as children
   * ("Saving…"), so the button says what it is doing. */
  loading?: boolean;
  /** A keyboard shortcut cap rendered inside the button, e.g. "Enter". */
  shortcut?: ReactNode;
  children?: ReactNode;
}

export function Button({
  variant = "secondary",
  size = "md",
  block = false,
  loading = false,
  shortcut,
  className,
  children,
  disabled,
  ...rest
}: ButtonProps) {
  const isDisabled = disabled || loading;
  return (
    <button
      type="button"
      className={buttonClass({ variant, size, block, className })}
      aria-disabled={isDisabled ? "true" : undefined}
      aria-busy={loading ? "true" : undefined}
      disabled={isDisabled}
      {...rest}
    >
      {loading ? <span className="btn__spinner" aria-hidden="true" /> : null}
      {children}
      {shortcut ? <span className="kbd">{shortcut}</span> : null}
    </button>
  );
}

/** A router link that looks like a button: navigation, styled as an action. */
export function LinkButton({
  variant = "secondary",
  size = "md",
  block = false,
  className,
  children,
  ...rest
}: LinkProps & { variant?: ButtonVariant; size?: ButtonSize; block?: boolean }) {
  return (
    <Link className={buttonClass({ variant, size, block, className })} {...rest}>
      {children}
    </Link>
  );
}

/** A 36 px round icon button. `title` is required: it is the accessible
 * name and the tooltip. */
export function IconButton({
  className,
  children,
  title,
  ...rest
}: ButtonHTMLAttributes<HTMLButtonElement> & { title: string }) {
  return (
    <button
      type="button"
      className={["iconbtn", className ?? ""].filter(Boolean).join(" ")}
      title={title}
      aria-label={title}
      {...rest}
    >
      {children}
    </button>
  );
}
