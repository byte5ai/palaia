import type { ButtonHTMLAttributes, ReactNode } from "react";

export type ButtonVariant = "secondary" | "primary" | "signal" | "ghost" | "quiet" | "risk";
export type ButtonSize = "sm" | "md" | "lg";

export interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  /** "secondary" (the raised-surface default) unless the action really is
   * the next step. `primary` is capped at one per screen and `signal` at
   * one across the whole visible view (system.md §2, Actions). */
  variant?: ButtonVariant;
  size?: ButtonSize;
  /** Full width — only where the container is genuinely one column wide
   * *and* the action is not the primary (system.md: a full-width accent
   * slab is the loudest object on any screen). */
  block?: boolean;
  /** A keyboard shortcut cap rendered inside the button, e.g. "⌘K". */
  shortcut?: ReactNode;
  children?: ReactNode;
}

const VARIANT_CLASS: Record<ButtonVariant, string> = {
  secondary: "",
  primary: "btn--primary",
  signal: "btn--signal",
  ghost: "btn--ghost",
  quiet: "btn--quiet",
  risk: "btn--risk",
};

const SIZE_CLASS: Record<ButtonSize, string> = {
  sm: "btn--sm",
  md: "",
  lg: "btn--lg",
};

export function Button({
  variant = "secondary",
  size = "md",
  block = false,
  shortcut,
  className,
  children,
  disabled,
  ...rest
}: ButtonProps) {
  const classes = [
    "btn",
    VARIANT_CLASS[variant],
    SIZE_CLASS[size],
    block ? "btn--block" : "",
    className ?? "",
  ]
    .filter(Boolean)
    .join(" ");

  return (
    <button
      type="button"
      className={classes}
      aria-disabled={disabled ? "true" : undefined}
      disabled={disabled}
      {...rest}
    >
      {children}
      {shortcut ? <span className="kbd">{shortcut}</span> : null}
    </button>
  );
}

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
