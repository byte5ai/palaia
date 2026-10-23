/**
 * - `primary`: the one next step on a view.
 * - `secondary` (default): everything else.
 * - `plain`: a text action in the action colour, no box.
 * - `destructive`: removes or turns something off. Red text on the
 *   secondary box; the filled `danger` version is for the confirm button
 *   inside a confirm dialog only.
 *
 * `signal`, `ghost`, `quiet` and `risk` are earlier names, kept so older
 * screens render in the new style: signal → primary, ghost → plain,
 * quiet → secondary, risk → destructive.
 */
export type ButtonVariant =
  | "primary"
  | "secondary"
  | "plain"
  | "destructive"
  | "danger"
  | "signal"
  | "ghost"
  | "quiet"
  | "risk";
export type ButtonSize = "sm" | "md" | "lg";

const VARIANT_CLASS: Record<ButtonVariant, string> = {
  primary: "btn--primary",
  secondary: "",
  plain: "btn--plain",
  destructive: "btn--destructive",
  danger: "btn--danger",
  signal: "btn--primary",
  ghost: "btn--plain",
  quiet: "",
  risk: "btn--destructive",
};

const SIZE_CLASS: Record<ButtonSize, string> = {
  sm: "btn--sm",
  md: "",
  lg: "btn--lg",
};

export function buttonClass({
  variant = "secondary",
  size = "md",
  block = false,
  className,
}: {
  variant?: ButtonVariant;
  size?: ButtonSize;
  block?: boolean;
  className?: string;
} = {}): string {
  return ["btn", VARIANT_CLASS[variant], SIZE_CLASS[size], block ? "btn--block" : "", className ?? ""]
    .filter(Boolean)
    .join(" ");
}
